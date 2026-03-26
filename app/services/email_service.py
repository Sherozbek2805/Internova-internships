from flask import current_app, url_for
from flask_mail import Message
from app.extensions import mail


def send_verification(email, token):
    verify_url = url_for("auth.verify_email", token=token, _external=True)

    msg = Message(
        subject="Verify your Internova account",
        sender=current_app.config["MAIL_DEFAULT_SENDER"],
        recipients=[email]
    )

    msg.body = f"""
Verify your Internova account by clicking the link below:

{verify_url}

This link will expire soon. If you did not create an account, you can ignore this email.
"""

    mail.send(msg)