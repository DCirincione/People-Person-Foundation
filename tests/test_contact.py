import asyncio
import os
import smtplib
import unittest
import tempfile
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.contact import ContactSubmission, submit_contact
from app.main import app, contact, home
from app import storage


class ContactTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {"LOCAL_DATA_DIR": temp.name, "SUPABASE_URL": "", "SUPABASE_SECRET_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "", "VERCEL": ""})
        env.start()
        self.addCleanup(env.stop)

    def submission(self):
        return ContactSubmission(name="Test Visitor", email="visitor@example.com", message="Hello from the test.")

    def test_recipient_and_reply_to(self):
        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": "test-password"}), patch("app.contact.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            result = submit_contact(self.submission())
            connection = smtp.return_value.__enter__.return_value
            message = connection.send_message.call_args.args[0]
            self.assertEqual(message["To"], "peoplepersonfoundation@gmail.com")
            self.assertEqual(message["Reply-To"], "visitor@example.com")
            connection.starttls.assert_called_once()
            self.assertIn("received", result["message"])
            self.assertEqual(storage.list_messages()[0]["delivery"], "sent")

    def test_missing_credentials_does_not_send(self):
        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": ""}), patch("app.contact.smtplib.SMTP") as smtp:
            result = submit_contact(self.submission())
            self.assertIn("received", result["message"])
            self.assertEqual(storage.list_messages()[0]["delivery"], "failed")
            smtp.assert_not_called()

    def test_delivery_failure_still_saves_message(self):
        with patch.dict(os.environ, {"GMAIL_APP_PASSWORD": "test-password"}), patch("app.contact.smtplib.SMTP", side_effect=smtplib.SMTPException("private diagnostic")):
            result = submit_contact(self.submission())
            self.assertIn("received", result["message"])
            self.assertNotIn("private diagnostic", result["message"])
            self.assertEqual(storage.list_messages()[0]["delivery"], "failed")

    def test_invalid_submissions(self):
        for updates in [{"name": "Visitor\r\nBcc: other@example.com"}, {"email": "not-an-email"}, {"message": "   "}, {"message": "x" * 3001}, {"recipient": "other@example.com"}]:
            values = {"name": "Visitor", "email": "visitor@example.com", "message": "Hello"} | updates
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                ContactSubmission(**values)

    def test_pages_render_with_shared_navigation(self):
        request = Request({"type": "http", "method": "GET", "path": "/", "scheme": "http", "headers": [], "server": ("localhost", 8000), "router": app.router})
        for route in (home, contact):
            html = asyncio.run(route(request)).body.decode()
            self.assertIn('href="/contact"', html)
            self.assertEqual(html.count('<header class="site-header">'), 1)
            self.assertIn('images/logo.png', html)
        html = asyncio.run(contact(request)).body.decode()
        for value in ('peoplepersonfoundation@gmail.com', '(631) 905-9595', 'https://www.instagram.com/peoplepersonfoundation/', 'action="/api/contact"', 'Send message'):
            self.assertIn(value, html)
        self.assertNotIn('northforkmarketing@gmail.com', html)
        self.assertNotIn('joeandfrancis', html)


if __name__ == "__main__":
    unittest.main()
