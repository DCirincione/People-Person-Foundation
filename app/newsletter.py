"""Persisted mailing list and resumable, individually addressed newsletters."""
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import storage
from app.admin import require_admin, require_write
from app.content import CONTACT_EMAIL

router = APIRouter()


class Signup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    email: str = Field(max_length=254, pattern=r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")


@router.post('/api/newsletter/subscribe')
def subscribe(body: Signup):
    storage.subscribe(body.email.lower())
    return {'message': 'You’re on the list! Thank you for staying connected.'}


@router.post('/newsletter/subscribe', response_class=HTMLResponse)
def subscribe_form(email: str = Form(default="")):
    # Native form submission remains functional when the browser has stale or
    # unavailable JavaScript. Report success only after persistence completes.
    status = 200
    try:
        subscribe(Signup(email=email))
        title = "You’re on the list!"
        message = "Thank you for staying connected with the People Person Foundation."
    except ValidationError:
        status = 422
        title = "Check your email address"
        message = "Please go back and enter a valid email address."
    except storage.StorageError:
        status = 503
        title = "We couldn’t save your signup"
        message = "Please go back and try again in a moment."
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title><link rel="stylesheet" href="/static/css/styles.css"></head>'
        f'<body><main class="container team"><h1>{title}</h1><p>{message}</p>'
        '<a class="button" href="/">Return to the website</a></main></body></html>',
        status_code=status, headers={'Cache-Control': 'no-store'},
    )


@router.get('/newsletter/unsubscribe/{token}', response_class=HTMLResponse)
def unsubscribe_page(token: str):
    if not storage.subscriber_by_token(token):
        raise HTTPException(404, 'This unsubscribe link is invalid.')
    return HTMLResponse('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width"><title>Unsubscribe</title><h1>Leave the email list?</h1><form method="post"><button>Unsubscribe</button></form></html>', headers={'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store'})


@router.post('/newsletter/unsubscribe/{token}', response_class=HTMLResponse)
def unsubscribe(token: str):
    storage.unsubscribe(token)
    return HTMLResponse('<!doctype html><html lang="en"><title>Unsubscribed</title><h1>You’re unsubscribed.</h1><p>You will no longer receive updates from the People Person Foundation.</p><a href="/">Return to the website</a></html>', headers={'Cache-Control': 'no-store'})


def settings():
    username = os.getenv('GMAIL_SMTP_USER', CONTACT_EMAIL)
    password = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '')
    origin = os.getenv('PUBLIC_SITE_URL', '').rstrip('/')
    if not username or not password or not origin.startswith(('https://', 'http://localhost:', 'http://127.0.0.1:')):
        raise HTTPException(503, 'Set Gmail credentials and PUBLIC_SITE_URL before sending newsletters.')
    return username, password, origin


def summary(job):
    counts = {state: sum(r['status'] == state for r in job['recipients']) for state in ('pending', 'sending', 'sent', 'failed', 'skipped')}
    return {key: job[key] for key in ('id', 'subject', 'created_at')} | counts | {'total': len(job['recipients'])}


@router.get('/admin/api/newsletter', dependencies=[Depends(require_admin)])
def overview():
    return {'subscribers': len(storage.list_subscribers()), 'campaigns': [summary(j) for j in storage.list_newsletters()]}


class Campaign(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    id: UUID
    subject: str = Field(min_length=1, max_length=200, pattern=r'^[^\r\n]+$')
    body: str = Field(min_length=1, max_length=20000)


@router.post('/admin/api/newsletter', dependencies=[Depends(require_write)])
def create_campaign(body: Campaign):
    settings()
    existing = storage.get_newsletter(str(body.id))
    if existing:
        return summary(existing)
    subscribers = storage.list_subscribers()
    if not subscribers:
        raise HTTPException(422, 'No one has signed up yet.')
    job = {'id': str(body.id), 'subject': body.subject, 'body': body.body, 'revision': 0,
           'created_at': datetime.now(timezone.utc).isoformat(),
           'recipients': [{'token': r['token'], 'status': 'pending'} for r in subscribers]}
    storage.save_newsletter(job)
    return summary(job)


@router.post('/admin/api/newsletter/{identifier}/send', dependencies=[Depends(require_write)])
def send_next(identifier: UUID):
    username, password, origin = settings()
    job = storage.get_newsletter(str(identifier))
    if not job:
        raise HTTPException(404, 'Email not found.')
    recipient = next((r for r in job['recipients'] if r['status'] == 'pending'), None)
    if not recipient:
        return summary(job)
    # Persist an exclusive claim before SMTP. Ambiguous delivery is never retried.
    recipient['status'] = 'sending'
    storage.save_newsletter(job)
    subscriber = storage.subscriber_by_token(recipient['token'])
    if not subscriber or not subscriber['active']:
        recipient['status'] = 'skipped'
    else:
        message = EmailMessage()
        message['From'] = username
        message['To'] = subscriber['email']
        message['Subject'] = job['subject']
        message.set_content(job['body'] + '\n\n—\nPeople Person Foundation\nUnsubscribe: ' + origin + '/newsletter/unsubscribe/' + recipient['token'])
        try:
            with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(username, password)
                if smtp.send_message(message):
                    raise smtplib.SMTPException('Recipient refused')
            recipient['status'] = 'sent'
        except (smtplib.SMTPException, OSError):
            recipient['status'] = 'failed'
    # Other requests may have claimed another recipient while SMTP was running.
    # Merge this outcome into the latest revision without overwriting their work.
    for attempt in range(5):
        latest = storage.get_newsletter(str(identifier))
        match = next(r for r in latest['recipients'] if r['token'] == recipient['token'])
        match['status'] = recipient['status']
        try:
            storage.save_newsletter(latest)
            return summary(latest) | {'last_failed': recipient['status'] == 'failed'}
        except storage.ConflictError:
            if attempt == 4:
                raise
