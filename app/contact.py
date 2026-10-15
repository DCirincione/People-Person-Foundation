"""Validated contact submissions delivered through Gmail SMTP."""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.content import CONTACT_EMAIL
from app import storage

router = APIRouter()


class ContactSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120, pattern=r"^[^\r\n]+$")
    email: str = Field(max_length=254, pattern=r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")
    phone: str = Field(default="", max_length=40, pattern=r"^[0-9+().\s\-xX]*$")
    message: str = Field(min_length=1, max_length=3000)


@router.post("/api/contact")
def submit_contact(submission: ContactSubmission):
    try:
        message_id = storage.save_message(submission.model_dump())
    except storage.StorageError:
        raise HTTPException(503, "We couldn’t save your message. Please try again or email us directly.") from None

    def delivery_status(value):
        try:
            storage.update_message(message_id, delivery=value)
        except storage.StorageError:
            logging.getLogger(__name__).warning("Could not update contact notification status for %s", message_id)

    received = {"message": "Thank you! Your message has been received."}
    username = os.getenv("GMAIL_SMTP_USER", CONTACT_EMAIL)
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not username or not password:
        delivery_status("failed")
        return received

    message = EmailMessage()
    message["Subject"] = f"Website contact: {submission.name}"
    message["From"] = username
    message["To"] = CONTACT_EMAIL
    message["Reply-To"] = submission.email
    message.set_content(
        f"Name: {submission.name}\nEmail: {submission.email}\n"
        f"Phone: {submission.phone or 'Not provided'}\n\n{submission.message}"
    )
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username, password)
            refused = smtp.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
    except (smtplib.SMTPException, OSError):
        delivery_status("failed")
        return received
    delivery_status("sent")
    return received
