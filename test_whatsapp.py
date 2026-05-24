import os
from twilio.rest import Client

def send_test_message():
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_num = os.environ.get('TWILIO_FROM_NUMBER')
    to_num = os.environ.get('TWILIO_TO_NUMBER')
    
    if not all([account_sid, auth_token, from_num, to_num]):
        print("Error: Missing Twilio credentials in environment variables.")
        return
        
    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            from_=from_num,
            body="👋 Hello from your AI Trading Bot! Your WhatsApp integration is fully active and working perfectly.",
            to=to_num
        )
        print(f"Success! Sent test WhatsApp message. Message SID: {message.sid}")
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")

if __name__ == "__main__":
    send_test_message()
