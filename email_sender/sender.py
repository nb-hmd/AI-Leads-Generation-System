import smtplib
import logging
from email.message import EmailMessage
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SENDER_NAME

logger = logging.getLogger(__name__)

def send_email(to_email, subject, body):
    """
    Send an email via SMTP.
    Returns True if successful, False otherwise.
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        logger.error("SMTP Configuration is incomplete. Cannot send email.")
        return False
        
    if not to_email:
        logger.error("Recipient email is missing.")
        return False

    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = f"{SENDER_NAME} <{SMTP_USER}>"
    msg['To'] = to_email

    try:
        logger.info(f"Connecting to SMTP server {SMTP_HOST}:{SMTP_PORT}...")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            
        logger.info(f"Email successfully sent to {to_email}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP Authentication Error: Check your username and password/app password.")
        return False
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
