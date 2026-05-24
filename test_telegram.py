import os
import requests

def send_test_message():
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not all([bot_token, chat_id]):
        print("Error: Missing Telegram credentials in environment variables.")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "👋 Hello from your AI Trading Bot! Your Telegram integration is fully active and working perfectly.",
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Success! Sent test Telegram message.")
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

if __name__ == "__main__":
    send_test_message()
