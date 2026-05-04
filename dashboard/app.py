import streamlit as st
import duckdb
import pandas as pd
import joblib
import os
import subprocess
from datetime import datetime, timedelta
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from streamlit_autorefresh import st_autorefresh
import feedparser
import urllib.parse
import plotly.graph_objects as go

# Configure page to look clean and wide
st.set_page_config(page_title="Mag 7 Quant Engine", layout="wide", page_icon="📈")

# UI Refresh (5 minutes = 300,000 ms)
st_autorefresh(interval=5 * 60 * 1000, limit=None, key="news_autorefresh")

# Initialize Local NLP
analyzer = SentimentIntensityAnalyzer()

# Inject Custom Apple-Style CSS
st.markdown("""
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #f5f5f7;
    }
    h1, h2, h3 { color: #1d1d1f; font-weight: 600; letter-spacing: -0.015em; }
    p { color: #515154; font-size: 15px; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models', 'saved')
MAG_7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

# --- DATABASE HELPER FUNCTIONS ---
def refresh_market_data():
    base_dir = os.path.join(os.path.dirname(__file__), '..')
    scripts = [
        r"data_ingestion\yfinance_scraper.py",
        r"data_ingestion\fred_scraper.py",
        r"feature_engineering\build_features.py"
    ]
    my_bar = st.progress(0, text="Starting Live Data Sync...")
    for i, script in enumerate(scripts):
        my_bar.progress((i + 1) * 33, text=f"Executing {os.path.basename(script)}...")
        try:
            subprocess.run(["python", os.path.join(base_dir, script)], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            st.error(f"Error running {script}: {e.stderr.decode()}")
            return False
    my_bar.empty()
    st.cache_data.clear()
    return True

@st.cache_data(ttl=3600)
def get_latest_data():
    conn = duckdb.connect(DB_PATH)
    query = "SELECT * FROM features WHERE date = (SELECT MAX(date) FROM features) ORDER BY ticker"
    df = conn.execute(query).df()
    conn.close()
    return df

@st.cache_data(ttl=3600)
def get_historical_data(ticker, days=90):
    conn = duckdb.connect(DB_PATH)
    query = f"SELECT date, close FROM features WHERE ticker = '{ticker}' ORDER BY date DESC LIMIT {days}"
    try:
        df = conn.execute(query).df()
        conn.close()
        return df.sort_values('date') # Ascending for plotting
    except:
        conn.close()
        return pd.DataFrame()

# Portfolio Helpers
def get_active_trades():
    conn = duckdb.connect(DB_PATH)
    try:
        df = conn.execute("SELECT * FROM active_trades WHERE status = 'ACTIVE'").df()
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def log_trade(ticker, date, price, tp, sl, quantity=1.0, is_ai_managed=True):
    conn = duckdb.connect(DB_PATH)
    conn.execute(f"""
        INSERT INTO active_trades (ticker, entry_date, entry_price, take_profit, stop_loss, status, quantity, is_ai_managed)
        VALUES ('{ticker}', '{date}', {price}, {tp}, {sl}, 'ACTIVE', {quantity}, {is_ai_managed})
        ON CONFLICT (ticker) DO UPDATE SET 
            entry_date = excluded.entry_date,
            entry_price = excluded.entry_price,
            take_profit = excluded.take_profit,
            stop_loss = excluded.stop_loss,
            quantity = excluded.quantity,
            is_ai_managed = excluded.is_ai_managed,
            status = 'ACTIVE'
    """)
    conn.close()

def update_stop_loss(ticker, new_sl):
    conn = duckdb.connect(DB_PATH)
    conn.execute(f"UPDATE active_trades SET stop_loss = {new_sl} WHERE ticker = '{ticker}'")
    conn.close()

def close_trade(ticker, status):
    conn = duckdb.connect(DB_PATH)
    conn.execute(f"UPDATE active_trades SET status = '{status}' WHERE ticker = '{ticker}'")
    conn.close()

# --- NEWS & SENTIMENT HELPER ---
@st.cache_data(ttl=300) 
def get_live_news(ticker):
    processed_news = []
    
    # 1. Google News RSS
    try:
        query = urllib.parse.quote(f"{ticker} stock supply chain OR manufacturing OR news")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:3]:
            processed_news.append({
                'title': entry.title,
                'link': entry.link,
                'publisher': entry.source.title if hasattr(entry, 'source') else 'Google News',
                'pubDate_raw': entry.published,
                'source_type': 'Google News'
            })
    except Exception as e:
        pass
        
    # 2. SEC Edgar 8-K
    try:
        feedparser.USER_AGENT = "ThinkBright_Quant_Engine/1.0 (contact@example.com)"
        sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=8-K&output=atom"
        sec_feed = feedparser.parse(sec_url)
        for entry in sec_feed.entries[:2]:
            processed_news.append({
                'title': f"SEC Filing (8-K): {entry.title}",
                'link': entry.link,
                'publisher': 'SEC Edgar',
                'pubDate_raw': entry.updated,
                'source_type': 'SEC Edgar'
            })
    except Exception as e:
        pass

    # 3. Yahoo Finance
    try:
        tk = yf.Ticker(ticker)
        y_news = tk.news
        for article in y_news[:2]:
            content = article.get('content', {})
            if content.get('contentType') != 'STORY': continue
            processed_news.append({
                'title': content.get('title', 'No Title'),
                'link': content.get('clickThroughUrl', {}).get('url', '#'),
                'publisher': content.get('provider', {}).get('displayName', 'Yahoo Finance'),
                'pubDate_raw': content.get('pubDate', ''),
                'source_type': 'Yahoo Finance'
            })
    except:
        pass

    # Categorize
    final_news = []
    for item in processed_news:
        try: pub_time = item['pubDate_raw'][:25]
        except: pub_time = "Recent"

        text_to_analyze = item['title'].lower()
        supply_keywords = ['supply chain', 'supplier', 'tsmc', 'foxconn', 'manufacturing', 'shortage', 'logistics', 'tariff', 'production', 'factory', 'freight', 'export', '8-k']
        
        category = "📰 General News"
        if any(keyword in text_to_analyze for keyword in supply_keywords): category = "🏭 Supply Chain Update"
            
        vs = analyzer.polarity_scores(text_to_analyze)
        compound = vs['compound']
        
        if compound > 0.15: sentiment = "🟢 Bullish"
        elif compound < -0.15: sentiment = "🔴 Bearish"
        else: sentiment = "⚪ Neutral"
            
        final_news.append({
            'title': item['title'],
            'link': item['link'],
            'publisher': f"{item['publisher']} ({item['source_type']})",
            'time': pub_time,
            'category': category,
            'sentiment': sentiment
        })
        
    return final_news[:6]

# --- PLOTLY SPARKLINE ---
def create_sparkline(ticker, current_price, take_profit, stop_loss, is_buy=True):
    hist_df = get_historical_data(ticker)
    if hist_df.empty: return None
        
    fig = go.Figure()
    
    # Base historical line
    fig.add_trace(go.Scatter(
        x=hist_df['date'], 
        y=hist_df['close'], 
        mode='lines',
        line=dict(color='#86868b', width=3),
        hovertemplate='%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>'
    ))
    
    # Current Price Indicator
    last_date = pd.to_datetime(hist_df['date'].iloc[-1])
    fig.add_hline(
        y=current_price, 
        line_dash="dash", 
        line_color="#5f6368", 
        annotation_text=f"Current: ${current_price:.2f}",
        annotation_position="bottom left",
        annotation_font_color="#5f6368"
    )
    
    if is_buy:
        # Future projection setup
        last_date = pd.to_datetime(hist_df['date'].iloc[-1])
        future_date = last_date + timedelta(days=40)
        
        # Target Line Projection
        fig.add_trace(go.Scatter(
            x=[last_date, future_date],
            y=[current_price, take_profit],
            mode='lines+text',
            line=dict(color='#137333', width=2, dash='dot'),
            text=['', f'TARGET: ${take_profit:.2f}'],
            textposition='top right',
            textfont=dict(color='#137333', size=12)
        ))
        
        # Stop Loss Line Projection
        fig.add_trace(go.Scatter(
            x=[last_date, future_date],
            y=[current_price, stop_loss],
            mode='lines+text',
            line=dict(color='#c5221f', width=2, dash='dot'),
            text=['', f'STOP: ${stop_loss:.2f}'],
            textposition='bottom right',
            textfont=dict(color='#c5221f', size=12)
        ))

    # Clean layout to look like a premium app widget
    fig.update_layout(
        showlegend=False,
        margin=dict(l=40, r=80 if is_buy else 40, t=20, b=40),
        height=220,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=False, showticklabels=True, tickfont=dict(color='#86868b')),
        yaxis=dict(showgrid=True, gridcolor='#e0e0e0', showticklabels=True, tickfont=dict(color='#86868b'), tickprefix="$")
    )
    return fig

# --- MAIN UI LAYOUT ---
with st.sidebar:
    st.title("System Info")
    st.markdown("""
    **What this tracks:**
    This system tracks the Magnificent 7 stocks using advanced AI, telling you exactly when to buy and when to sell.
    
    **Auto-Refresh:**
    The dashboard UI and the Live News tab automatically refresh every **5 minutes**.
    """)
    
    if st.button("🔄 Force Market Sync", use_container_width=True, type="primary"):
        with st.spinner("Re-syncing AI..."):
            success = refresh_market_data()
        if success:
            st.success("Successfully updated!")
            st.rerun()

    st.divider()
    st.subheader("Navigation")
    view_selection = st.radio("Select View", ["📊 Simple Action View", "💼 Active Portfolio", "📰 Live News & Supply Chain"], label_visibility="collapsed")

st.title("Magnificent 7 Action Dashboard")

try:
    df_latest = get_latest_data()
except:
    st.error("Could not connect to the database. Please run the backend scripts.")
    st.stop()

if df_latest.empty:
    st.warning("No data found in the database.")
    st.stop()

latest_date = df_latest['date'].iloc[0]

spy_close = df_latest['spy_close'].iloc[0]
spy_sma = df_latest['spy_sma_200'].iloc[0]
macro_safe = spy_close > spy_sma

if view_selection != "📰 Live News & Supply Chain":
    if macro_safe:
        st.success(f"🟢 **BULLISH MACRO REGIME:** S&P 500 (${spy_close:.2f}) is above its 200-Day Moving Average (${spy_sma:.2f}). Tech buying is authorized.")
    else:
        st.error(f"🔴 **BEARISH MACRO REGIME:** S&P 500 (${spy_close:.2f}) is below its 200-Day Moving Average (${spy_sma:.2f}). Defensive cash positions enforced.")

st.divider()

features_cols = [
    'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
    'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
]

if view_selection == "📊 Simple Action View":
    cols = st.columns(3)
    col_idx = 0
    
    for ticker in MAG_7:
        ticker_data = df_latest[df_latest['ticker'] == ticker]
        if ticker_data.empty: continue
            
        row = ticker_data.iloc[0]
        X_pred = ticker_data[features_cols]
        
        # High-Level Complexity Variables (Restored)
        if row['sma_20_dist'] > 0 and row['sma_50_dist'] > 0: trend = "Bullish Trajectory ↗"
        elif row['sma_20_dist'] < 0 and row['sma_50_dist'] < 0: trend = "Bearish Trajectory ↘"
        else: trend = "Stagnant / Sideways ➔"
            
        if row['rsi_14'] > 70: driver = "Driven by heavily overbought momentum (RSI > 70)."
        elif row['rsi_14'] < 30: driver = "Driven by oversold bounce conditions (RSI < 30)."
        elif row['us_10y_yield'] > 4.5: driver = "Pressured by high 10Y Treasury Yields."
        else: driver = f"Driven by normal volatility cycles (ATR: {row['atr_percent']*100:.1f}%)."
            
        model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
        if os.path.exists(model_path):
            model = joblib.load(model_path)
            ai_prob = model.predict_proba(X_pred)[0][1] * 100
        else:
            ai_prob = 0
            
        entry_price = row['close']
        atr = row['atr_percent']
        take_profit = entry_price * (1 + (atr * 2.0))
        stop_loss = entry_price * (1 - (atr * 1.0))
        
        # Traffic Light UI Logic
        is_buy = (ai_prob > 55 and macro_safe)
        
        # Explain AI Reasoning to avoid dissonance
        if not is_buy:
            if not macro_safe:
                ai_reasoning = "<b>AI Verdict:</b> Avoiding due to dangerous macroeconomic conditions (S&P 500 in downtrend)."
            elif "Bullish" in trend:
                if row['rsi_14'] > 60:
                    ai_reasoning = "<b>AI Verdict:</b> The trend is bullish, but the stock is currently overextended. Buying now carries a high risk of a pullback. The AI is holding cash and waiting for a safer entry."
                else:
                    ai_reasoning = "<b>AI Verdict:</b> The trend is bullish, but the mathematical setup lacks the required 3:1 reward-to-risk ratio. The AI requires a stronger statistical edge to authorize a buy."
            elif "Bearish" in trend:
                ai_reasoning = "<b>AI Verdict:</b> The stock is in a confirmed downtrend. The AI will not attempt to 'catch a falling knife' until momentum reverses."
            else:
                ai_reasoning = "<b>AI Verdict:</b> The stock is moving sideways with no clear momentum. The AI is holding cash until a breakout is confirmed."
        else:
            ai_reasoning = "<b>AI Verdict:</b> Statistical edge confirmed. High probability of an asymmetric breakout."
        if is_buy:
            signal = "🟢 BUY NOW"
            bg_color = "#e6f4ea" # Light green
            border_color = "#ceead6"
            text_color = "#137333"
            estimated_exit = (pd.to_datetime(latest_date) + timedelta(days=40)).strftime('%B %d, %Y')
            
            action_html = f"""
                <div style="background-color: {bg_color}; padding: 20px; border-radius: 12px; border: 1px solid {border_color}; margin-bottom: 5px;">
                    <h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${entry_price:.2f}</span></h2>
                    <h1 style="color: {text_color}; margin: 10px 0;">{signal}</h1>
                    <p style="color: #202124; font-size: 14px; margin-top: 15px;"><b>Trend:</b> {trend}</p>
                    <p style="color: #5f6368; font-size: 13px;">{driver}</p>
                    <hr style="border-color: {border_color}; margin: 10px 0;">
                    <p style="color: #202124; font-size: 13px; line-height: 1.4;">{ai_reasoning}</p>
                    <div style="margin-top: 15px;">
                        <p style="color: #202124; font-size: 13px; font-weight: bold; margin: 0 0 5px 0;">AI Buy Confidence: {ai_prob:.1f}%</p>
                        <div style="background-color: #dadce0; border-radius: 4px; width: 100%; height: 8px;">
                            <div style="background-color: {text_color}; width: {ai_prob}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                    </div>
                    <h3 style="color: #202124; margin: 15px 0 5px 0;">🎯 SELL AT: ${take_profit:.2f}</h3>
                    <h3 style="color: #202124; margin: 5px 0;">🛡️ STOP LOSS: ${stop_loss:.2f}</h3>
                    <p style="color: #5f6368; font-size: 15px; margin-top: 15px;"><b>⏳ Est. Exit Date:</b> {estimated_exit}</p>
                </div>
            """
        else:
            signal = "🛑 AVOID (DO NOT BUY)"
            bg_color = "#fce8e6" # Light red
            border_color = "#fad2cf"
            text_color = "#c5221f"
            action_html = f"""
                <div style="background-color: {bg_color}; padding: 20px; border-radius: 12px; border: 1px solid {border_color}; margin-bottom: 5px;">
                    <h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${entry_price:.2f}</span></h2>
                    <h1 style="color: {text_color}; margin: 10px 0; font-size: 28px;">{signal}</h1>
                    <p style="color: #202124; font-size: 14px; margin-top: 15px;"><b>Trend:</b> {trend}</p>
                    <p style="color: #5f6368; font-size: 13px;">{driver}</p>
                    <hr style="border-color: {border_color}; margin: 10px 0;">
                    <p style="color: #202124; font-size: 13px; line-height: 1.4;">{ai_reasoning}</p>
                    <div style="margin-top: 15px;">
                        <p style="color: #202124; font-size: 13px; font-weight: bold; margin: 0 0 5px 0;">AI Buy Confidence: {ai_prob:.1f}%</p>
                        <div style="background-color: #dadce0; border-radius: 4px; width: 100%; height: 8px;">
                            <div style="background-color: {text_color}; width: {ai_prob}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                    </div>
                </div>
            """
        
        with cols[col_idx % 3]:
            # Print the Box
            st.markdown(action_html, unsafe_allow_html=True)
            
            # ALWAYS Print the Plotly Chart for visual context
            fig = create_sparkline(ticker, entry_price, take_profit, stop_loss, is_buy=is_buy)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                
            # Add to Portfolio Button (Only if it's a BUY)
            if is_buy:
                if st.button(f"📥 Add {ticker} to Portfolio", key=f"add_{ticker}", use_container_width=True):
                    log_trade(ticker, latest_date, entry_price, take_profit, stop_loss, quantity=1.0, is_ai_managed=True)
                    st.success(f"{ticker} logged to Portfolio! Go to the Active Portfolio tab to track it.")
                
        col_idx += 1

elif view_selection == "💼 Active Portfolio":
    st.markdown("### 💼 Your Active Portfolio")
    
    # -- IMPORT EXISTING POSITION FORM --
    with st.expander("➕ Import Existing Stock Position", expanded=False):
        with st.form("import_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                imp_ticker = st.selectbox("Stock", MAG_7)
            with col2:
                imp_qty = st.number_input("Quantity of Shares", min_value=0.01, value=10.0, step=1.0)
            with col3:
                imp_price = st.number_input("Average Purchase Price ($)", min_value=1.0, value=150.0, step=1.0)
                
            imp_ai = st.toggle("🤖 Apply AI Swing Trading Algorithm?", value=True, help="If checked, the AI will mathematically calculate a Take-Profit and Stop-Loss target based on your entry price and tell you when to sell.")
            
            if st.form_submit_button("Import to Portfolio", type="primary", use_container_width=True):
                tp, sl = 0.0, 0.0
                if imp_ai:
                    # Get current ATR and Live Price to calculate algorithmic targets from TODAY'S baseline
                    live_row = df_latest[df_latest['ticker'] == imp_ticker]
                    if not live_row.empty:
                        atr = live_row['atr_percent'].iloc[0]
                        live_price_for_calc = live_row['close'].iloc[0]
                        tp = live_price_for_calc * (1 + (atr * 2.0))
                        sl = live_price_for_calc * (1 - (atr * 1.0))
                
                log_trade(imp_ticker, latest_date, imp_price, tp, sl, quantity=imp_qty, is_ai_managed=imp_ai)
                st.success(f"Successfully imported {imp_qty} shares of {imp_ticker}!")
                st.rerun()
                
    st.divider()

    portfolio_df = get_active_trades()
    
    if portfolio_df.empty:
        st.info("You currently have no active trades. Go to the 'Simple Action View' to find stocks to buy, or import an existing position above.")
    else:
        p_cols = st.columns(3)
        p_idx = 0
        for _, trade in portfolio_df.iterrows():
            ticker = trade['ticker']
            entry_price = trade['entry_price']
            tp = trade['take_profit']
            sl = trade['stop_loss']
            qty = trade.get('quantity', 1.0)
            is_ai_managed = trade.get('is_ai_managed', True)
            
            # Get current live price from latest data
            live_row = df_latest[df_latest['ticker'] == ticker]
            if live_row.empty: continue
            
            live_price = live_row['close'].iloc[0]
            atr = live_row['atr_percent'].iloc[0]
            
            profit_loss_per_share = live_price - entry_price
            total_profit = profit_loss_per_share * qty
            pl_percent = (profit_loss_per_share / entry_price) * 100
            total_value = live_price * qty
            
            # AI MANAGED vs MANUAL HOLD ROUTING
            if is_ai_managed:
                # TRAILING STOP LOGIC
                new_theoretical_sl = live_price * (1 - (atr * 1.0))
                if new_theoretical_sl > sl:
                    update_stop_loss(ticker, new_theoretical_sl)
                    sl = new_theoretical_sl 
                    
                # SELL SIGNALS
                if live_price >= tp:
                    status_bg = "#fef7e0" # Gold
                    status_border = "#fce8b2"
                    status_text = "#ea8600"
                    action_signal = "🎯 TARGET HIT. SELL NOW."
                elif live_price <= sl:
                    status_bg = "#fce8e6" # Red
                    status_border = "#fad2cf"
                    status_text = "#c5221f"
                    action_signal = "🛡️ STOP LOSS HIT. SELL NOW."
                else:
                    status_bg = "#e8f0fe" # Blue
                    status_border = "#d2e3fc"
                    status_text = "#1967d2"
                    action_signal = "⏳ HOLDING"
                    
                badge = "🤖 AI Managed"
                target_html = f"<p style='color: #202124; margin: 5px 0; font-size: 15px;'><b>Take-Profit Target:</b> ${tp:.2f}</p><p style='color: #202124; margin: 5px 0; font-size: 15px;'><b>Trailing Stop-Loss:</b> ${sl:.2f}</p>"
            else:
                # MANUAL TRACKER LOGIC
                status_bg = "#f1f3f4" # Gray
                status_border = "#dadce0"
                status_text = "#5f6368"
                action_signal = "👤 MANUAL HOLD"
                badge = "👤 Manual Tracking"
                target_html = "<p style='color: #5f6368; font-size: 14px;'><i>AI is ignoring this stock. Sell whenever you decide.</i></p>"
            
            html = f"""<div style="background-color: {status_bg}; padding: 20px; border-radius: 12px; border: 1px solid {status_border}; margin-bottom: 10px;">
<div style="background-color: #fff; border: 1px solid {status_border}; padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 12px; color: {status_text}; margin-bottom: 10px;"><b>{badge}</b></div>
<h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${live_price:.2f}</span></h2>
<h1 style="color: {status_text}; margin: 10px 0; font-size: 24px;">{action_signal}</h1>
<hr style="border-color: {status_border}; margin: 15px 0;">
<p style="color: #202124; margin: 5px 0; font-size: 15px;"><b>Shares Owned:</b> {qty:.2f} <i>(Valued at ${total_value:,.2f})</i></p>
<p style="color: #202124; margin: 5px 0; font-size: 15px;"><b>Average Entry:</b> ${entry_price:.2f}</p>
<p style="color: #202124; margin: 5px 0; font-size: 15px;"><b>Total Return:</b> <span style="color: {'#137333' if total_profit >= 0 else '#c5221f'}">${total_profit:,.2f} ({pl_percent:.1f}%)</span></p>
<hr style="border-color: {status_border}; margin: 15px 0;">
{target_html}
</div>"""
            
            with p_cols[p_idx % 3]:
                st.markdown(html, unsafe_allow_html=True)
                
                # Chart to track progress (Only draw targets if AI managed)
                if is_ai_managed:
                    fig = create_sparkline(ticker, live_price, tp, sl, is_buy=True)
                else:
                    fig = create_sparkline(ticker, live_price, 0, 0, is_buy=False)
                    
                if fig:
                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                
                # Close Trade Button
                btn_type = "primary" if is_ai_managed and (live_price >= tp or live_price <= sl) else "secondary"
                btn_text = "Close Position" if not is_ai_managed else "Execute Sell Logic"
                if st.button(btn_text, key=f"close_{ticker}", type=btn_type, use_container_width=True):
                    close_status = "CLOSED_PROFIT" if total_profit >= 0 else "CLOSED_LOSS"
                    close_trade(ticker, close_status)
                    st.rerun()
                    
            p_idx += 1

elif view_selection == "📰 Live News & Supply Chain":
    st.markdown("### Live Market Context")
    st.markdown("This tab automatically pulls, categorizes, and runs sentiment analysis on live headlines every 5 minutes.")
    
    for ticker in MAG_7:
        with st.expander(f"{ticker} - Live News & Supply Chain Updates", expanded=False):
            articles = get_live_news(ticker)
            if not articles:
                st.write("No recent stories found.")
            else:
                for article in articles:
                    st.markdown(f"**[{article['title']}]({article['link']})**")
                    st.markdown(f"<p style='font-size:13px; color:gray; margin-top:-10px;'><b>{article['category']}</b> • {article['sentiment']} • {article['publisher']} • {article['time']}</p>", unsafe_allow_html=True)
                    st.markdown("<hr style='margin: 10px 0px; border-top: 1px dashed #e0e0e0;'>", unsafe_allow_html=True)
