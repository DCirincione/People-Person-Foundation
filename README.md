# People Person Foundation

FastAPI, Jinja templates, and static assets with a password-protected website editor.

## Local development

Requires Python 3.12 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Contact: `/contact`. Health: `/health`.
The app loads `.env.local`, then `.env` as a fallback. Existing process environment variables take precedence. Restart the server after changing credentials.

## Admin

Click the **header logo five times consecutively** (less than 750 ms between clicks) or open `/admin`. A single click still opens the homepage after a short delay. The shortcut only opens the login; it does not grant access.

Set `ADMIN_PASSWORD` (at least 16 characters) and `ADMIN_SESSION_SECRET` (at least 32 random characters) in your environment. This local checkout has generated values in its gitignored `.env.local`. Never commit or share this file. To create fresh values, generate each separately with `python -c 'import secrets; print(secrets.token_urlsafe(32))'` and put the results in your private environment settings.

The admin editor supports:

- Replacing the homepage photo and its accessible description.
- Editing the About heading, introduction, and paragraphs.
- Adding, editing, removing, and reordering team members and uploading their portraits.
- Reading contact submissions, viewing notification status, and marking messages read/unread.

Upload JPG, PNG, or WebP images smaller than 4 MB and 20 megapixels. Images are decoded, orientation-corrected, resized to at most 1800 pixels, and re-encoded as JPEG without metadata. Image changes publish with **Save changes**. Team members appear three per row on desktop and two on mobile. Saves detect conflicting edits from other windows instead of overwriting them. Removed/replaced images are retained in storage for now.

Sessions expire after eight hours. Changing either admin secret invalidates all sessions. Cookies are HttpOnly, SameSite Strict, and Secure on HTTPS/Vercel. Changes require a session CSRF token. Admin pages/API responses are private and non-cacheable. Login throttling is per process (10 failed attempts per minute); configure deployment-level rate limits if distributed login protection is needed.

## Supabase and persistence

Without Supabase settings, local development uses `data/site.sqlite3`, including uploaded photos. The directory is gitignored. **Vercel requires Supabase**; the app refuses to write temporary local data there.

1. Create a Supabase project.
2. Configure the content and contact-message tables with row-level security and a private `site-images` bucket in Supabase.
3. Add `SUPABASE_URL` and `SUPABASE_SECRET_KEY` to `.env.local`. A legacy server `SUPABASE_SERVICE_ROLE_KEY` is also supported. Do not use the public/anon key or put a server key in frontend code.
4. Restart the server. All new reads, saves, messages, and image uploads now use Supabase.

Only the FastAPI server accesses the database and bucket. Uploaded website images are served publicly by `/media/{id}`; contact messages require admin authentication. Local SQLite data is not automatically copied when switching to Supabase. Configure Supabase before making content edits you want to keep for deployment, or migrate existing local data explicitly.

References: [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys), [row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security).

## Contact messages and email

The contact page displays `peoplepersonfoundation@gmail.com`, `(631) 905-9595`, and the foundation's Instagram link.

The form posts to `/api/contact`. Submissions are validated and **saved before email notification is attempted**. If storage fails, the visitor sees an error and their inputs remain. Once saved, the visitor gets a receipt even if Gmail is unavailable; the admin inbox shows the notification as failed. Pending status means sending has not finished or the delivery status could not be updated. Historical emails sent before this inbox was added are not imported.

Set `GMAIL_SMTP_USER=peoplepersonfoundation@gmail.com` and `GMAIL_APP_PASSWORD` to a [Google app password](https://support.google.com/accounts/answer/185833). Gmail SMTP uses STARTTLS on port 587. Replies to notification emails go to the visitor. Secrets belong in `.env.local` locally and Vercel environment settings when deployed. Tests do not send live emails.

## Vercel

Import the GitHub repository at the repository root, select the FastAPI framework preset, and use default build/output settings. Configure the admin, Supabase, Gmail, and `PUBLIC_SITE_URL` environment variables described above and below, then deploy. No Node build is required. `.env.local` and local SQLite data are not deployed.

[Official FastAPI deployment documentation](https://vercel.com/docs/frameworks/backend/fastapi).

## Content and source files

- `app/main.py`: public routes and shared page context
- `app/admin.py`: admin authentication, API routes, and image validation
- `app/storage.py`: SQLite/Supabase persistence
- `app/contact.py`: contact validation, storage, and email notification
- `app/templates/`: public and admin templates
- `app/static/`: CSS, JavaScript, and original logo/community image
- `app/content.py`: contact details, signup/donation destinations, and initial team placeholders
- `docs/reference/homepage-reference.png`: supplied layout reference

The default About wording is draft copy. Edit it in admin. The email signup opens the built-in signup form. Donation buttons remain “coming soon” until their URL is set in `app/content.py`.

## Verification

```sh
python -m unittest discover -s tests
node --check app/static/js/admin.js
node --check app/static/js/main.js
```

Tests use temporary SQLite databases and mocked email connections. They cover authentication, CSRF, content persistence/conflicts, escaping, upload validation/resizing, contact-message storage, and notification failure handling. Real Supabase configuration and inbox delivery need an environment-specific check.

## Email list and newsletters

Visitors use **Join the email list** to save their email address. Addresses are normalized and deduplicated. In `/admin`, open **Email list** to see the active subscriber count, write a subject and plain-text message, and send to everyone subscribed at the time the campaign is created. Contact-form submissions do not subscribe visitors.

Hosted storage requires the `newsletter_subscribers` and `newsletters` tables to be configured in Supabase with row-level security and server-only access. This setup is not performed automatically by the application. Local SQLite tables are created automatically. Set `GMAIL_SMTP_USER`, `GMAIL_APP_PASSWORD`, and `PUBLIC_SITE_URL` (the public HTTPS origin, without a trailing slash) in the deployment environment. Local development can use an `http://localhost:PORT` origin. Newsletter records and subscriber addresses are accessible only through authenticated admin APIs; the browser never receives SMTP credentials or unsubscribe tokens.

Each email is individually addressed and includes an unsubscribe link. Opening the link shows a confirmation form; submitting removes the address from future sends. Already queued campaigns recheck subscription status before sending. Signing up again reactivates the address.

Keep the admin page open while sending. The browser processes one recipient per request and records progress in the database. Use **Continue sending** after an interruption; completed recipients are not resent. Sending pauses on a mail-server error. Failed or unconfirmed recipients are not automatically retried because the server may already have accepted their message. “Accepted” means SMTP accepted the message, not confirmed inbox delivery. The dashboard shows the latest 20 campaigns. This uses the existing Gmail account and remains subject to its sending limits; it is not an unattended bulk-mail worker. No live emails are sent by tests.
