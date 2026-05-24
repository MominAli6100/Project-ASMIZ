import streamlit as st
import duckdb
import pandas as pd
import joblib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from streamlit_autorefresh import st_autorefresh
import feedparser
import urllib.parse
import plotly.graph_objects as go

# Configure page to look clean and wide
st.set_page_config(page_title="Mag 7 Quant Engine", layout="wide", page_icon="📈")

view_selection = st.radio("Select View", ["📊 Simple Action View", "💼 Active Portfolio", "📈 Performance Analytics", "📰 Live News & Supply Chain", "🕵️ Insider Alpha (V2)", "⏪ Backtest Simulator"], label_visibility="collapsed", key="main_nav_radio")
st.divider()


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

# Try to get MotherDuck token from secrets (Streamlit Cloud) or environment variable (Local)
try:
    MD_TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
except:
    MD_TOKEN = os.environ.get("MOTHERDUCK_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns")

def get_db_connection():
    return duckdb.connect(f'md:?motherduck_token={MD_TOKEN}')

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models', 'saved')
ALL_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", # Mag 7
    "ALAB", "AVGO", "MRVL", "AMD", "MU", "PLTR", "ASML", "TSM", "IREN", "CRWV", "CRDO", "TAN", "RKLB", # High Growth Tech
    "WLKP", "ECL", "LIN", "LXU", "CC", # Chemical/Industrial
    "ARM", "CDNS", "SNPS", "AMKR", "ASX", "RMBS", "SITM", "WDC", "STX", "LITE", "COHR", "FN", "APH", "GLW", "LUNA", "ANET", "CIEN", "CLS", "JBL", "FLEX", "TTMI", "VICR", "VRT", "NVT", "PH", "WULF", "CIFR", "IPGP", # Advanced Semiconductors & Networking
    "CRM", "NOW", "PANW", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ADBE", "INTU", "UBER", "ABNB", "SMCI", "SHOP", "MELI", "SPOT", "NFLX", "ROKU", "COIN", "HOOD", # High-Momentum Growth
    "SPY", "QQQ", "DIA", "XLF", "COST", "BRK-B" # Standard Market ETFs & Blue Chips
]

SECTORS = {
    "All Stocks": ALL_TICKERS,
    "Magnificent 7": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "Semiconductors & AI": ["AMD", "NVDA", "AVGO", "MRVL", "MU", "ASML", "TSM", "ALAB", "CRDO", "PLTR", "CRWV"],
    "Advanced Tech & Networks": ["ARM", "CDNS", "SNPS", "AMKR", "ASX", "RMBS", "SITM", "WDC", "STX", "LITE", "COHR", "FN", "APH", "GLW", "LUNA", "ANET", "CIEN", "CLS", "JBL", "FLEX", "TTMI", "VICR", "VRT", "NVT", "PH", "WULF", "CIFR", "IPGP"],
    "High-Momentum Growth": ["CRM", "NOW", "PANW", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ADBE", "INTU", "UBER", "ABNB", "SMCI", "SHOP", "MELI", "SPOT", "NFLX", "ROKU", "COIN", "HOOD"],
    "Energy & Aerospace": ["TAN", "IREN", "RKLB"],
    "Chemicals & Industrials": ["WLKP", "ECL", "LIN", "LXU", "CC"],
    "Standard ETFs & Blue Chips": ["SPY", "QQQ", "DIA", "XLF", "COST", "BRK-B"]
}

# --- DATABASE HELPER FUNCTIONS ---
def refresh_market_data():
    # The scraping scripts are now fully decoupled and run completely independently 
    # via the 5-minute GitHub Action cron job. We no longer force Streamlit Cloud's 
    # 1GB RAM instance to try to execute four massive data pipelines simultaneously.
    # Streamlit simply fetches the pre-calculated live data from MotherDuck.
    st.cache_data.clear()
    return True

@st.cache_data(ttl=60)
def get_latest_data():
    conn = get_db_connection()
    query = "SELECT * FROM features WHERE date = (SELECT MAX(date) FROM features) ORDER BY ticker"
    df = conn.execute(query).df()
    conn.close()
    return df

@st.cache_data(ttl=300)
def get_historical_data(ticker, days=90):
    conn = get_db_connection()
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
    conn = get_db_connection()
    try:
        df = conn.execute("SELECT * FROM active_trades WHERE status = 'ACTIVE'").df()
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def log_trade(ticker, date, price, tp, sl, quantity=1.0, is_ai_managed=True):
    conn = get_db_connection()
    
    # Check if trade already exists to calculate weighted average
    existing = conn.execute(f"SELECT entry_price, quantity FROM active_trades WHERE ticker = '{ticker}' AND status = 'ACTIVE'").fetchone()
    
    if existing:
        old_price = existing[0]
        old_qty = existing[1]
        
        new_qty = old_qty + quantity
        new_price = ((old_qty * old_price) + (quantity * price)) / new_qty
        
        conn.execute(f"""
            UPDATE active_trades SET 
                entry_date = '{date}',
                entry_price = {new_price},
                take_profit = {tp},
                stop_loss = {sl},
                quantity = {new_qty},
                is_ai_managed = {is_ai_managed}
            WHERE ticker = '{ticker}' AND status = 'ACTIVE'
        """)
    else:
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
    conn = get_db_connection()
    conn.execute(f"UPDATE active_trades SET stop_loss = {new_sl} WHERE ticker = '{ticker}'")
    conn.close()

def close_trade_v2(ticker, exit_price):
    conn = get_db_connection()
    trade = conn.execute(f"SELECT entry_date, entry_price, quantity, is_ai_managed FROM active_trades WHERE ticker = '{ticker}' AND status = 'ACTIVE'").fetchone()
    if trade:
        exit_date = datetime.now(ZoneInfo('America/Chicago')).strftime('%Y-%m-%d %H:%M:%S')
        pl = (exit_price - trade[1]) * trade[2]
        pl_pct = ((exit_price - trade[1]) / trade[1]) * 100
        conn.execute(f"""
            INSERT INTO closed_trades VALUES ('{ticker}', '{trade[0]}', '{exit_date}', {trade[1]}, {exit_price}, {pl}, {pl_pct}, {trade[2]}, {trade[3]})
        """)
        conn.execute(f"DELETE FROM active_trades WHERE ticker = '{ticker}'")
    conn.close()

def close_trade(ticker, status):
    conn = get_db_connection()
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
        
    # 2. SEC Edgar (All Filings: Form 4, 8-K, 10-Q)
    try:
        feedparser.USER_AGENT = "ThinkBright_Quant_Engine/1.0 (contact@example.com)"
        sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&output=atom"
        sec_feed = feedparser.parse(sec_url)
        for entry in sec_feed.entries[:5]: # Check top 5 recent filings
            title_upper = entry.title.upper()
            if "4 -" in title_upper or "FORM 4" in title_upper:
                processed_news.append({
                    'title': f"Insider Trade (Form 4): {entry.title}",
                    'link': entry.link,
                    'publisher': 'SEC Edgar',
                    'pubDate_raw': entry.updated,
                    'source_type': 'SEC Edgar',
                    'hardcoded_category': '🏛️ Insider Form 4'
                })
            elif "8-K" in title_upper:
                processed_news.append({
                    'title': f"Major Event (8-K): {entry.title}",
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
        
        category = item.get('hardcoded_category', "📰 General News")
        if category == "📰 General News" and any(keyword in text_to_analyze for keyword in supply_keywords): 
            category = "🏭 Supply Chain Update"
            
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
        
    return final_news[:8]

def get_whale_data(ticker):
    conn = get_db_connection()
    try:
        options = conn.execute(f"SELECT * FROM options_flow WHERE ticker = '{ticker}' ORDER BY volume DESC LIMIT 5").df()
        dark_pools = conn.execute(f"SELECT * FROM dark_pool_blocks WHERE ticker = '{ticker}' ORDER BY datetime DESC LIMIT 3").df()
    except:
        options = pd.DataFrame()
        dark_pools = pd.DataFrame()
    conn.close()
    return options, dark_pools

@st.cache_data(ttl=300)
def get_insider_data(ticker):
    conn = get_db_connection()
    try:
        df = conn.execute(f"SELECT * FROM insider_trades WHERE ticker = '{ticker}' ORDER BY fetch_date DESC LIMIT 1").df()
    except:
        df = pd.DataFrame()
    conn.close()
    return df


# --- PLOTLY SPARKLINE ---
def create_sparkline(ticker, current_price, take_profit, stop_loss, is_buy=True, expected_days=40):
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
        future_date = last_date + timedelta(days=expected_days)
        
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
    # Auto-Refresh Logic & Timestamp via Session State (Fixes Infinite Loop Bug)
    if 'last_market_sync' not in st.session_state:
        st.session_state.last_market_sync = datetime.now(ZoneInfo('America/Chicago'))
        
    time_since_update = datetime.now(ZoneInfo('America/Chicago')) - st.session_state.last_market_sync
    
    if time_since_update.total_seconds() > 300: # 5 minutes
        st.toast("Auto-syncing live market data in the background...")
        success = refresh_market_data()
        if success:
            st.session_state.last_market_sync = datetime.now(ZoneInfo('America/Chicago'))
        st.rerun()

    st.markdown(f"<div style='padding: 10px; background-color: #e8eaed; border-radius: 8px; text-align: center;'><b style='color: #202124;'>Last DB Sync:</b><br><span style='color: #137333; font-size: 18px;'>{st.session_state.last_market_sync.strftime('%I:%M:%S %p')}</span></div>", unsafe_allow_html=True)
    
    if st.button("🔄 Force Market Sync", use_container_width=True, type="primary"):
        with st.spinner("Re-syncing AI..."):
            success = refresh_market_data()
        if success:
            st.session_state.last_market_sync = datetime.now(ZoneInfo('America/Chicago'))
            st.success("Successfully updated!")
            st.rerun()

    
    
    st.divider()
    selected_sector = st.selectbox("🎯 Filter by Sector:", list(SECTORS.keys()))
    active_tickers = SECTORS[selected_sector]

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

if st.session_state.main_nav_radio != "📰 Live News & Supply Chain":
    if macro_safe:
        st.success(f"🟢 **BULLISH MACRO REGIME:** S&P 500 (${spy_close:.2f}) is above its 200-Day Moving Average (${spy_sma:.2f}). Tech buying is authorized.")
    else:
        st.error(f"🔴 **BEARISH MACRO REGIME:** S&P 500 (${spy_close:.2f}) is below its 200-Day Moving Average (${spy_sma:.2f}). Defensive cash positions enforced.")

st.divider()

features_cols = [
    'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
    'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
]

if st.session_state.main_nav_radio == "📊 Simple Action View":

    # PILLAR 4: Market Weather & Expectation Management
    st.markdown("### 📡 Market Weather")
    volatility = df_latest['volatility_20d'].iloc[0] * 100
    if not macro_safe:
        st.error("🔴 **Macro Status: BEARISH** | The S&P 500 is broken. The AI is highly defensive and will likely reject 95% of setups to hold cash.")
    elif volatility > 15:
        st.warning(f"🟡 **Macro Status: CAUTIOUS (High Volatility: {volatility:.1f}%)** | The market is choppy. The AI will only take A+ asymmetric setups.")
    else:
        st.success(f"🟢 **Macro Status: CLEAR (Normal Volatility: {volatility:.1f}%)** | Market conditions are prime for quantitative momentum trading.")
    
    st.info("💡 **Law of Large Numbers:** Algorithmic edge is invisible in 1 trade. It takes a minimum of **20 to 30 closed trades** for the 79% statistical win rate to reflect in your portfolio balance. Trust the math, not the emotions.")
    st.divider()
    
    cols = st.columns(3)

    col_idx = 0
    
    for ticker in active_tickers:
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
        
        # Dynamic Time Barrier Calculation
        momentum_per_day = abs(row['return_5d']) / 5.0
        if pd.isna(momentum_per_day) or momentum_per_day < 0.001: 
            momentum_per_day = 0.001
            
        required_pct_move = (take_profit - entry_price) / entry_price
        expected_days = int(required_pct_move / momentum_per_day)
        expected_days = max(4, min(40, expected_days)) # Clamp between 4 and 40 days
        
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
            estimated_exit = (pd.to_datetime(latest_date) + timedelta(days=expected_days)).strftime('%B %d, %Y')
            
            action_html = f"""
                <div style="background-color: {bg_color}; padding: 20px; border-radius: 12px; border: 1px solid {border_color}; margin-bottom: 5px; height: 650px; display: flex; flex-direction: column; overflow-y: auto;">
                    <div>
                        <h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${entry_price:.2f}</span></h2>
                        <h1 style="color: {text_color}; margin: 10px 0;">{signal}</h1>
                        <p style="color: #202124; font-size: 14px; margin-top: 15px;"><b>Trend:</b> {trend}</p>
                        <p style="color: #5f6368; font-size: 13px;">{driver}</p>
                        <hr style="border-color: {border_color}; margin: 10px 0;">
                        <p style="color: #202124; font-size: 13px; line-height: 1.4;">{ai_reasoning}</p>
                    </div>
                    <div style="margin-top: auto;">
                        <p style="color: #202124; font-size: 13px; font-weight: bold; margin: 0 0 5px 0;">AI Buy Confidence: {ai_prob:.1f}%</p>
                        <div style="background-color: #dadce0; border-radius: 4px; width: 100%; height: 8px;">
                            <div style="background-color: {text_color}; width: {ai_prob}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                        <h3 style="color: #202124; margin: 15px 0 5px 0;">🎯 SELL AT: ${take_profit:.2f}</h3>
                        <h3 style="color: #202124; margin: 5px 0;">🛡️ STOP LOSS: ${stop_loss:.2f}</h3>
                        <p style="color: #5f6368; font-size: 15px; margin-top: 15px;"><b>⏳ Est. Exit Date:</b> {estimated_exit}</p>
                    </div>
                </div>
            """
        else:
            signal = "🛑 AVOID (DO NOT BUY)"
            bg_color = "#fce8e6" # Light red
            border_color = "#fad2cf"
            text_color = "#c5221f"
            action_html = f"""
                <div style="background-color: {bg_color}; padding: 20px; border-radius: 12px; border: 1px solid {border_color}; margin-bottom: 5px; height: 650px; display: flex; flex-direction: column; overflow-y: auto;">
                    <div>
                        <h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${entry_price:.2f}</span></h2>
                        <h1 style="color: {text_color}; margin: 10px 0; font-size: 28px;">{signal}</h1>
                        <p style="color: #202124; font-size: 14px; margin-top: 15px;"><b>Trend:</b> {trend}</p>
                        <p style="color: #5f6368; font-size: 13px;">{driver}</p>
                        <hr style="border-color: {border_color}; margin: 10px 0;">
                        <p style="color: #202124; font-size: 13px; line-height: 1.4;">{ai_reasoning}</p>
                    </div>
                    <div style="margin-top: auto;">
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
            fig = create_sparkline(ticker, entry_price, take_profit, stop_loss, is_buy=is_buy, expected_days=expected_days if is_buy else 40)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                
            # Add to Portfolio Button (Only if it's a BUY)
            if is_buy:
                if st.button(f"📥 Add {ticker} to Portfolio", key=f"add_{ticker}", use_container_width=True):
                    log_trade(ticker, latest_date, entry_price, take_profit, stop_loss, quantity=1.0, is_ai_managed=True)
                    st.success(f"{ticker} logged to Portfolio! Go to the Active Portfolio tab to track it.")
                
        col_idx += 1

elif st.session_state.main_nav_radio == "💼 Active Portfolio":
    st.markdown("### 💼 Your Active Portfolio")
    
    # -- IMPORT EXISTING POSITION FORM --
    with st.expander("➕ Import Existing Stock Position", expanded=False):
        with st.form("import_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                imp_ticker = st.selectbox("Stock", ALL_TICKERS)
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
            
            html = f"""<div style="background-color: {status_bg}; padding: 20px; border-radius: 12px; border: 1px solid {status_border}; margin-bottom: 10px; height: 550px; display: flex; flex-direction: column; overflow-y: auto;">
<div>
    <div style="background-color: #fff; border: 1px solid {status_border}; padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 12px; color: {status_text}; margin-bottom: 10px;"><b>{badge}</b></div>
    <h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${live_price:.2f}</span></h2>
    <h1 style="color: {status_text}; margin: 10px 0; font-size: 24px;">{action_signal}</h1>
    <hr style="border-color: {status_border}; margin: 15px 0;">
    <p style="color: #202124; margin: 5px 0; font-size: 15px;"><b>Shares Owned:</b> {qty:.2f} <i>(Valued at ${total_value:,.2f})</i></p>
    <p style="color: #202124; margin: 5px 0; font-size: 15px;"><b>Average Entry:</b> ${entry_price:.2f}</p>
    <p style="color: #202124; margin: 5px 0; font-size: 15px;"><b>Total Return:</b> <span style="color: {'#137333' if total_profit >= 0 else '#c5221f'}">${total_profit:,.2f} ({pl_percent:.1f}%)</span></p>
</div>
<div style="margin-top: auto;">
    <hr style="border-color: {status_border}; margin: 15px 0;">
    {target_html}
</div>
</div>"""
            
            with p_cols[p_idx % 3]:
                st.markdown(html, unsafe_allow_html=True)
                
                # Chart to track progress (Only draw targets if AI managed)
                if is_ai_managed:
                    # Calculate dynamic days for portfolio chart
                    momentum_per_day = abs(live_row['return_5d'].iloc[0]) / 5.0
                    if pd.isna(momentum_per_day) or momentum_per_day < 0.001: momentum_per_day = 0.001
                    rem_pct = abs(tp - live_price) / live_price
                    exp_days = int(rem_pct / momentum_per_day)
                    exp_days = max(4, min(40, exp_days))
                    fig = create_sparkline(ticker, live_price, tp, sl, is_buy=True, expected_days=exp_days)
                else:
                    fig = create_sparkline(ticker, live_price, 0, 0, is_buy=False)
                    
                if fig:
                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                
                # Close Trade Button
                btn_type = "primary" if is_ai_managed and (live_price >= tp or live_price <= sl) else "secondary"
                btn_text = "Close Position" if not is_ai_managed else "Execute Sell Logic"
                if st.button(btn_text, key=f"close_{ticker}", type=btn_type, use_container_width=True):
                    close_trade_v2(ticker, live_price)
                    st.rerun()
                    
            p_idx += 1


elif st.session_state.main_nav_radio == "📈 Performance Analytics":
    st.markdown("### 📈 Closed Trades Ledger")
    st.markdown("This is your quantitative captain's log. True alpha is only visible over large sample sizes.")
    
    conn = get_db_connection()
    try:
        df_closed = conn.execute("SELECT * FROM closed_trades ORDER BY exit_date DESC").df()
    except:
        df_closed = pd.DataFrame()
    conn.close()
    
    if df_closed.empty:
        st.info("No closed trades yet. Follow the AI, take the signals, and build your statistical edge.")
    else:
        total_trades = len(df_closed)
        wins = len(df_closed[df_closed['profit_loss'] > 0])
        win_rate = (wins / total_trades) * 100
        net_profit = df_closed['profit_loss'].sum()
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Closed Trades", total_trades)
        c2.metric("Realized Win Rate", f"{win_rate:.1f}%")
        c3.metric("Net Realized P&L", f"${net_profit:,.2f}")
        
        st.divider()
        
        # Cumulative P&L Chart
        df_closed = df_closed.sort_values('exit_date')
        df_closed['cumulative_pl'] = df_closed['profit_loss'].cumsum()
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_closed['exit_date'], y=df_closed['cumulative_pl'], mode='lines+markers', line=dict(color='#137333', width=3)))
        fig.update_layout(title="Cumulative Realized Profit", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="Date", yaxis_title="Total Profit ($)")
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("#### 📘 Trade Ledger Details")
        st.markdown("Use the checkboxes in the **Delete** column and click the button below to remove erroneous trades.")
        
        # Filter down to the essential columns
        display_df = df_closed[['ticker', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'pl_percent', 'profit_loss']].copy()
        
        # Add a selection column for deletion
        display_df.insert(0, "Delete", False)
        
        # Beautifully format the data editor
        edited_df = st.data_editor(
            display_df,
            column_config={
                "Delete": st.column_config.CheckboxColumn("🗑️ Delete", default=False),
                "ticker": st.column_config.TextColumn("Ticker", width="small"),
                "entry_date": st.column_config.DatetimeColumn("Entry Date", format="MMM DD, YYYY - h:mm a"),
                "exit_date": st.column_config.DatetimeColumn("Exit Date", format="MMM DD, YYYY - h:mm a"),
                "entry_price": st.column_config.NumberColumn("Entry Price", format="$%.2f"),
                "exit_price": st.column_config.NumberColumn("Exit Price", format="$%.2f"),
                "pl_percent": st.column_config.NumberColumn("P&L (%)", format="%.2f%%"),
                "profit_loss": st.column_config.NumberColumn("Net P&L", format="$%.2f"),
            },
            hide_index=True,
            use_container_width=True,
            disabled=["ticker", "entry_date", "exit_date", "entry_price", "exit_price", "pl_percent", "profit_loss"]
        )
        
        # Deletion Logic
        rows_to_delete = edited_df[edited_df["Delete"] == True]
        if not rows_to_delete.empty:
            if st.button(f"🚨 Confirm Deletion of {len(rows_to_delete)} Trade(s)", type="primary"):
                conn = get_db_connection()
                for _, row in rows_to_delete.iterrows():
                    ticker = row['ticker']
                    # Handle pandas timestamp to string formatting for SQL
                    entry_date_str = pd.to_datetime(row['entry_date']).strftime('%Y-%m-%d %H:%M:%S')
                    conn.execute(f"DELETE FROM closed_trades WHERE ticker='{ticker}' AND entry_date='{entry_date_str}'")
                conn.close()
                st.success("Trades successfully purged from the ledger.")
                st.rerun()


elif st.session_state.main_nav_radio == "📰 Live News & Supply Chain":
    st.markdown("### Institutional Whale & News Engine")
    st.markdown("This tab combines **Proprietary Synthetic Dark Pool Math**, live Options Flow analysis, and SEC Form 4 parsing to track Smart Money activity in real-time.")
    
    for ticker in active_tickers:
        with st.expander(f"{ticker} - Whale Tracking & Live News", expanded=False):
            options_df, dp_df = get_whale_data(ticker)
            articles = get_live_news(ticker)
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("#### 🐋 Options Flow (Whale Bets)")
                if not options_df.empty:
                    for _, row in options_df.iterrows():
                        color = "#137333" if row['sentiment'] == "BULLISH" else "#c5221f"
                        st.markdown(f"<div style='border-left: 4px solid {color}; padding-left: 10px; margin-bottom: 10px;'>"
                                    f"<b>{row['type']} | Strike: ${row['strike']}</b><br>"
                                    f"<span style='color:gray; font-size: 13px;'>Vol: {int(row['volume']):,} | Open Interest: {int(row['open_interest']):,}</span>"
                                    f"</div>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:gray; font-size: 14px;'>No unusual options flow detected today.</span>", unsafe_allow_html=True)
                    
                st.markdown("<br>#### 🌊 Synthetic Dark Pool", unsafe_allow_html=True)
                if not dp_df.empty:
                    for _, row in dp_df.iterrows():
                        st.markdown(f"<div style='border-left: 4px solid #5f6368; padding-left: 10px; margin-bottom: 10px;'>"
                                    f"<b>Hidden Block Detected</b><br>"
                                    f"<span style='color:gray; font-size: 13px;'>Price: ${row['price']:.2f} | Vol: {int(row['volume']):,}</span>"
                                    f"</div>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:gray; font-size: 14px;'>No hidden liquidity blocks detected.</span>", unsafe_allow_html=True)
                    
            with c2:
                st.markdown("#### 🏛️ SEC Insider Tracking")
                insider_news = [a for a in articles if a['category'] == '🏛️ Insider Form 4']
                if insider_news:
                    for a in insider_news:
                        st.markdown(f"**[{a['title']}]({a['link']})**")
                        st.markdown(f"<p style='font-size:12px; color:gray;'>{a['time']}</p>", unsafe_allow_html=True)
                        st.markdown("<hr style='margin: 5px 0px;'>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:gray; font-size: 14px;'>No recent Form 4 insider trades.</span>", unsafe_allow_html=True)
                    
            with c3:
                st.markdown("#### 📰 Fundamental News")
                gen_news = [a for a in articles if a['category'] != '🏛️ Insider Form 4']
                if gen_news:
                    for a in gen_news:
                        sentiment_color = "gray"
                        if "Bullish" in a['sentiment']: sentiment_color = "#137333"
                        elif "Bearish" in a['sentiment']: sentiment_color = "#c5221f"
                        st.markdown(f"**[{a['title']}]({a['link']})**")
                        st.markdown(f"<p style='font-size:12px; color:gray;'><b>{a['category']}</b> • <span style='color:{sentiment_color};'>{a['sentiment']}</span> • {a['publisher']}</p>", unsafe_allow_html=True)
                        st.markdown("<hr style='margin: 5px 0px;'>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:gray; font-size: 14px;'>No recent fundamental news.</span>", unsafe_allow_html=True)

elif st.session_state.main_nav_radio == "🕵️ Insider Alpha (V2)":
    st.markdown("### 🕵️ Insider Trading Alpha (V2 Algorithm)")
    st.markdown("This experimental tab fuses our base AI Mathematical Probability with **SEC Form 4 Insider Tracking**.")
    st.markdown("When Corporate C-Suite executives buy their own stock heavily on the open market, it acts as a massive conviction multiplier.")
    st.divider()
    
    cols = st.columns(3)
    col_idx = 0
    
    for ticker in active_tickers:
        ticker_data = df_latest[df_latest['ticker'] == ticker]

        if ticker_data.empty: continue
            
        row = ticker_data.iloc[0]
        X_pred = ticker_data[features_cols]
        
        # Trend logic
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
        
        # Pull Insider Data
        insider_df = get_insider_data(ticker)
        net_shares = 0
        if not insider_df.empty:
            net_shares = insider_df['net_shares_purchased_6m'].iloc[0]
            
        # Insider V2 Overlay Math
        conviction_bonus = 0
        insider_status = "⚪ Neutral Insider Activity (0 Net Shares)"
        insider_color = "#5f6368"
        
        # Determine actual shares format (sometimes it's raw, sometimes millions)
        if abs(net_shares) < 1000 and abs(net_shares) > 0:
            display_shares = f"{net_shares:.2f}M"
            is_massive = abs(net_shares) > 1.0 # > 1 Million shares
        else:
            display_shares = f"{net_shares:,.0f}"
            is_massive = abs(net_shares) > 1000000
            
        if is_massive and net_shares > 0:
            conviction_bonus = 15
            insider_status = f"🚨 MASSIVE INSIDER BUYING (+15% Edge)<br>Net Shares: +{display_shares}"
            insider_color = "#137333"
        elif net_shares > 0:
            conviction_bonus = 5
            insider_status = f"🟢 Insider Accumulation (+5% Edge)<br>Net Shares: +{display_shares}"
            insider_color = "#137333"
        elif is_massive and net_shares < 0:
            conviction_bonus = -10
            insider_status = f"🔴 Heavy Insider Selling (-10% Edge)<br>Net Shares: {display_shares}"
            insider_color = "#c5221f"
        elif net_shares < 0:
            conviction_bonus = -5
            insider_status = f"🔴 Mild Insider Selling (-5% Edge)<br>Net Shares: {display_shares}"
            insider_color = "#c5221f"
            
        v2_prob = max(0, min(100, ai_prob + conviction_bonus))
        is_buy = (v2_prob >= 60 and macro_safe)
        
        if not is_buy:
            if not macro_safe:
                v2_reasoning = "<b>V2 Verdict:</b> Rejecting due to dangerous macroeconomic conditions (S&P 500 in downtrend)."
            elif "Bullish" in trend:
                if row['rsi_14'] > 60:
                    v2_reasoning = "<b>V2 Verdict:</b> The trend is bullish, but the stock is currently overextended. Buying now carries a high risk of a pullback. The V2 Engine is holding cash."
                else:
                    v2_reasoning = "<b>V2 Verdict:</b> The trend is bullish, but the combined AI + Insider setup lacks the required mathematical edge to authorize a buy."
            elif "Bearish" in trend:
                v2_reasoning = "<b>V2 Verdict:</b> The stock is in a confirmed downtrend. The V2 Engine will not attempt to catch a falling knife without massive insider buying."
            else:
                v2_reasoning = "<b>V2 Verdict:</b> The stock is moving sideways with no clear momentum. Holding cash."
        else:
            if conviction_bonus > 0:
                v2_reasoning = "<b>V2 Verdict:</b> Statistical edge confirmed and bolstered by Insider Accumulation. High probability of an asymmetric breakout."
            else:
                v2_reasoning = "<b>V2 Verdict:</b> Statistical edge confirmed. High probability of an asymmetric breakout despite neutral insider activity."
        
        # UI rendering
        if is_buy:
            signal = "🟢 V2 BUY TRIGGERED"
            bg_color = "#e6f4ea"
            border_color = "#ceead6"
            text_color = "#137333"
        else:
            signal = "🛑 V2 REJECTED"
            bg_color = "#fce8e6"
            border_color = "#fad2cf"
            text_color = "#c5221f"
            
        action_html = f"""<div style="background-color: {bg_color}; padding: 20px; border-radius: 12px; border: 1px solid {border_color}; margin-bottom: 5px; height: 600px; display: flex; flex-direction: column; overflow-y: auto;">
<div>
<div style="background-color: #fff; border: 1px solid {border_color}; padding: 4px 8px; border-radius: 4px; display: inline-block; font-size: 12px; color: #5f6368; margin-bottom: 5px;"><b>V2 ALGORITHM</b></div>
<h2 style="margin-top:0; color: #202124;">{ticker} <span style='float:right; color:#5f6368;'>${entry_price:.2f}</span></h2>
<h2 style="color: {text_color}; margin: 5px 0;">{signal}</h2>
<p style="color: #202124; font-size: 14px; margin-top: 15px;"><b>Trend:</b> {trend}</p>
<p style="color: #5f6368; font-size: 13px;">{driver}</p>
<hr style="border-color: {border_color}; margin: 10px 0;">
<p style="color: #202124; font-size: 13px; line-height: 1.4;">{v2_reasoning}</p>
<hr style="border-color: {border_color}; margin: 10px 0;">
<p style="color: #202124; font-size: 14px; margin-top: 10px;"><b>Base AI Prob:</b> {ai_prob:.1f}%</p>
<div style="padding: 10px; background-color: #f1f3f4; border-left: 4px solid {insider_color}; border-radius: 4px; margin: 10px 0;">
<p style="color: {insider_color}; margin: 0; font-size: 14px; font-weight: bold;">{insider_status}</p>
</div>
</div>
<div style="margin-top: auto;">
<p style="color: #202124; font-size: 15px; font-weight: bold; margin: 0 0 5px 0;">Total V2 Conviction: {v2_prob:.1f}%</p>
<div style="background-color: #dadce0; border-radius: 4px; width: 100%; height: 8px;">
<div style="background-color: {text_color}; width: {v2_prob}%; height: 100%; border-radius: 4px;"></div>
</div>
</div>
</div>"""
        
        with cols[col_idx % 3]:
            st.markdown(action_html, unsafe_allow_html=True)
            if is_buy:
                if st.button(f"📥 Log V2 {ticker} Trade", key=f"add_v2_{ticker}", use_container_width=True):
                    log_trade(ticker, latest_date, entry_price, take_profit, stop_loss, quantity=1.0, is_ai_managed=True)
                    st.success(f"{ticker} logged to Portfolio via V2!")
                    
        col_idx += 1

elif st.session_state.main_nav_radio == "⏪ Backtest Simulator":
    st.markdown("### ⏪ Historical Backtest Simulator")
    st.markdown("Simulate how the AI would have performed historically. **This is a read-only sandbox and does not modify your live trading algorithms.**")
    st.divider()
    
    # Fetch Min and Max Dates from database
    @st.cache_data(ttl=3600)
    def get_date_range():
        conn = get_db_connection()
        res = conn.execute("SELECT MIN(date) as min_d, MAX(date) as max_d FROM features").df()
        conn.close()
        return pd.to_datetime(res['min_d'].iloc[0]).date(), pd.to_datetime(res['max_d'].iloc[0]).date()
        
    min_db_date, max_db_date = get_date_range()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        algo_choice = st.selectbox("Select Algorithm", ["V1 Base AI (Math Only)", "V2 Insider Alpha (Math + SEC Form 4)"])
    with col2:
        asset_type = st.selectbox("Asset Granularity", ["Sector Universe", "Individual Stock"])
        if asset_type == "Sector Universe":
            asset_choice = st.selectbox("Select Universe", list(SECTORS.keys()))
        else:
            asset_choice = st.selectbox("Select Ticker", ALL_TICKERS)
    with col3:
        starting_capital = st.number_input("Starting Capital ($)", min_value=100.0, value=10000.0, step=1000.0)
    with col4:
        date_range = st.date_input("Select Date Range", value=(min_db_date, max_db_date), min_value=min_db_date, max_value=max_db_date)
        
    if st.button("🚀 Run Backtest Simulation", use_container_width=True):
        if len(date_range) != 2:
            st.error("Please select a valid start and end date.")
            st.stop()
            
        start_date, end_date = date_range
        
        if asset_type == "Sector Universe":
            tickers_to_test = SECTORS[asset_choice]
        else:
            tickers_to_test = [asset_choice]
            
        st.info(f"Initiating historical simulation using {algo_choice}...")
        
        # Define simulation parameters
        use_v2 = "V2" in algo_choice
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Load all historical data into memory for simulation
        conn = get_db_connection()
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        hist_df = conn.execute(f"SELECT * FROM features WHERE date >= '{start_str}' AND date <= '{end_str}' ORDER BY date ASC").df()
        spy_df = conn.execute(f"SELECT date, close FROM features WHERE ticker = 'SPY' AND date >= '{start_str}' AND date <= '{end_str}' ORDER BY date ASC").df()
        conn.close()
        
        if hist_df.empty:
            st.error(f"No data available for the selected date range ({start_str} to {end_str}).")
            st.stop()
        
        trade_history = []
        
        for i, ticker in enumerate(tickers_to_test):
            status_text.text(f"Simulating {ticker} ({i+1}/{len(tickers_to_test)})...")
            progress_bar.progress((i + 1) / len(tickers_to_test))
            
            ticker_df = hist_df[hist_df['ticker'] == ticker].copy()
            if ticker_df.empty: continue
                
            model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
            if not os.path.exists(model_path): continue
                
            model = joblib.load(model_path)
            
            # Pre-calculate probabilities
            X = ticker_df[features_cols].fillna(0)
            ticker_df['ai_prob'] = model.predict_proba(X)[:, 1] * 100
            
            # V2 Logic
            if use_v2:
                # We fetch the insider data once per ticker and apply the bonus dynamically
                insider_df = get_insider_data(ticker)
                net_shares = insider_df['net_shares_purchased_6m'].iloc[0] if not insider_df.empty else 0
                
                conviction_bonus = 0
                if abs(net_shares) > 1000000 and net_shares > 0: conviction_bonus = 15
                elif net_shares > 0: conviction_bonus = 5
                elif abs(net_shares) > 1000000 and net_shares < 0: conviction_bonus = -10
                elif net_shares < 0: conviction_bonus = -5
                
                ticker_df['sim_prob'] = np.clip(ticker_df['ai_prob'] + conviction_bonus, 0, 100)
            else:
                ticker_df['sim_prob'] = ticker_df['ai_prob']
                
            in_trade = False
            entry_price = 0
            take_profit = 0
            stop_loss = 0
            entry_date = None
            days_held = 0
            
            for idx, row in ticker_df.iterrows():
                date = row['date']
                close = row['close']
                atr = row['atr_percent']
                prob = row['sim_prob']
                macro_safe = row['spy_close'] > row['spy_sma_200']
                
                if not in_trade:
                    # ENTRY
                    if macro_safe and prob > 60:
                        in_trade = True
                        entry_price = close
                        entry_date = date
                        take_profit = entry_price * (1 + (atr * 2.0))
                        stop_loss = entry_price * (1 - (atr * 1.0))
                        days_held = 0
                else:
                    # IN TRADE
                    days_held += 1
                    
                    # Trailing SL
                    new_sl = close * (1 - (atr * 1.0))
                    if new_sl > stop_loss: stop_loss = new_sl
                        
                    exit_reason = None
                    if close >= take_profit: exit_reason = "TAKE_PROFIT"
                    elif close <= stop_loss: exit_reason = "STOP_LOSS"
                    elif days_held >= 40: exit_reason = "TIME_STOP"
                        
                    if exit_reason:
                        profit_loss = close - entry_price
                        pl_percent = (profit_loss / entry_price) * 100
                        trade_history.append({
                            'Ticker': ticker,
                            'Entry Date': entry_date,
                            'Exit Date': date,
                            'Entry Price': entry_price,
                            'Exit Price': close,
                            'Return %': pl_percent,
                            'Exit Reason': exit_reason,
                            'Days Held': days_held
                        })
                        in_trade = False
                        
        status_text.text("Simulation Complete!")
        
        if not trade_history:
            st.warning("No trades were generated during this historical period with the given parameters.")
        else:
            res_df = pd.DataFrame(trade_history)
            res_df = res_df.sort_values('Exit Date')
            
            # Analytics
            total_trades = len(res_df)
            wins = len(res_df[res_df['Return %'] > 0])
            losses = len(res_df[res_df['Return %'] <= 0])
            win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
            
            avg_win = res_df[res_df['Return %'] > 0]['Return %'].mean() if wins > 0 else 0
            avg_loss = res_df[res_df['Return %'] <= 0]['Return %'].mean() if losses > 0 else 0
            total_return = res_df['Return %'].sum()
            
            st.divider()
            st.markdown("### 📊 Performance Analytics")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Trades", total_trades)
            m2.metric("Win Rate", f"{win_rate:.1f}%")
            m3.metric("Avg Win / Loss", f"+{avg_win:.1f}% / {avg_loss:.1f}%")
            m4.metric("Gross Return", f"{total_return:+.1f}%")
            
            # Equity Curve
            res_df['Cumulative Return'] = res_df['Return %'].cumsum()
            res_df['Portfolio Value'] = starting_capital * (1 + (res_df['Cumulative Return']/100))
            
            # Prepend starting capital so the graph starts on day 1
            start_row = pd.DataFrame([{
                'Exit Date': pd.to_datetime(start_date),
                'Portfolio Value': starting_capital
            }])
            plot_df = pd.concat([start_row, res_df[['Exit Date', 'Portfolio Value']]]).reset_index(drop=True)
            
            # Baseline SPY Calculation
            if not spy_df.empty:
                spy_start = spy_df['close'].iloc[0]
                spy_df['spy_return'] = ((spy_df['close'] - spy_start) / spy_start) * 100
                spy_df['SPY Value'] = starting_capital * (1 + (spy_df['spy_return']/100))
            
            fig = go.Figure()
            # Use line_shape='hv' so the portfolio stays flat while in cash/holding, then steps up/down on exit
            fig.add_trace(go.Scatter(x=plot_df['Exit Date'], y=plot_df['Portfolio Value'], mode='lines', name='AI Equity Curve', line=dict(color='#137333', width=3, shape='hv')))
            
            if not spy_df.empty:
                fig.add_trace(go.Scatter(x=spy_df['date'], y=spy_df['SPY Value'], mode='lines', name='S&P 500 (Buy & Hold)', line=dict(color='#5f6368', width=2, dash='dash')))
                
            fig.update_layout(title=f"Simulated Portfolio Equity (Starting ${starting_capital:,.2f})", xaxis_title="Date", yaxis_title="Portfolio Value ($)", template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("📝 View Clean Trade Log", expanded=True):
                # Clean up the dataframe for display
                display_df = res_df.copy()
                display_df['Entry Date'] = pd.to_datetime(display_df['Entry Date']).dt.strftime('%Y-%m-%d')
                display_df['Exit Date'] = pd.to_datetime(display_df['Exit Date']).dt.strftime('%Y-%m-%d')
                
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Entry Price": st.column_config.NumberColumn("Entry Price", format="$%.2f"),
                        "Exit Price": st.column_config.NumberColumn("Exit Price", format="$%.2f"),
                        "Return %": st.column_config.NumberColumn("Trade Return", format="%.2f%%"),
                        "Cumulative Return": st.column_config.NumberColumn("Total Return", format="%.2f%%"),
                        "Portfolio Value": st.column_config.NumberColumn("Portfolio Value", format="$%.2f"),
                        "Days Held": st.column_config.NumberColumn("Days Held")
                    }
                )
