"""Local SQLite persistence; Supabase REST and Storage on hosted deployments."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from app.content import TEAM

ROOT = Path(__file__).resolve().parent.parent


class StorageError(Exception):
    pass


class ConflictError(StorageError):
    pass


def default_site():
    return {
        "revision": 0,
        "hero_image": "/static/images/community.png",
        "hero_alt": "A child and two young people enjoying a game of football together on a grassy field",
        "about_title": "Big hearts.\nEveryday people.",
        "about_lead": "At the People Person Foundation, it starts with people.",
        "about_body": "A conversation. A shared afternoon. A chance to be there for someone else. We believe the little things can mean a lot.\n\nBeing a People Person is an invitation to connect, lend a hand, and bring a little more kindness into the everyday.",
        "team": [{**person, "id": str(uuid4())} for person in TEAM],
    }


def remote():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if bool(url) != bool(key):
        raise StorageError("Both Supabase URL and server key are required.")
    if not url and os.getenv("VERCEL"):
        raise StorageError("Supabase must be configured on Vercel.")
    return url, key


def api(method, path, **kwargs):
    url, key = remote()
    headers = {"apikey": key}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    headers.update(kwargs.pop("headers", {}))
    try:
        response = httpx.request(method, url + path, headers=headers, timeout=20, **kwargs)
        if response.status_code == 409:
            raise ConflictError("Content changed in another window. Reload before saving.")
        response.raise_for_status()
        return response
    except httpx.HTTPError as exc:
        raise StorageError("Storage is unavailable. Check the database configuration.") from exc


@contextmanager
def db():
    path = Path(os.getenv("LOCAL_DATA_DIR", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path / "site.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS site_content (id TEXT PRIMARY KEY, content TEXT NOT NULL, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS contact_messages (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0, delivery TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, data BLOB NOT NULL);
        ''')
        with connection:
            yield connection
    except sqlite3.Error as exc:
        raise StorageError("Local storage is unavailable.") from exc
    finally:
        connection.close()


def get_site():
    if remote()[0]:
        rows = api("GET", "/rest/v1/site_content", params={"id": "eq.home", "select": "content,revision"}).json()
        row = rows[0] if rows else None
    else:
        with db() as connection:
            row = connection.execute("SELECT content,revision FROM site_content WHERE id='home'").fetchone()
        if row:
            row = {"content": json.loads(row["content"]), "revision": row["revision"]}
    return {**row["content"], "revision": row["revision"]} if row else default_site()


def save_site(content):
    content = dict(content)
    revision = content.pop("revision")
    if remote()[0]:
        if revision == 0:
            api("POST", "/rest/v1/site_content", json={"id": "home", "content": content, "revision": 1})
        else:
            rows = api("PATCH", "/rest/v1/site_content", params={"id": "eq.home", "revision": f"eq.{revision}"}, headers={"Prefer": "return=representation"}, json={"content": content, "revision": revision + 1}).json()
            if not rows:
                raise ConflictError("Content changed in another window. Reload before saving.")
    else:
        with db() as connection:
            if revision == 0:
                try:
                    connection.execute("INSERT INTO site_content VALUES ('home',?,1)", (json.dumps(content),))
                except sqlite3.IntegrityError:
                    raise ConflictError("Content changed in another window. Reload before saving.") from None
            else:
                cursor = connection.execute("UPDATE site_content SET content=?,revision=? WHERE id='home' AND revision=?", (json.dumps(content), revision + 1, revision))
                if cursor.rowcount != 1:
                    raise ConflictError("Content changed in another window. Reload before saving.")
    return {**content, "revision": revision + 1}


def save_message(values):
    row = {"id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **values, "is_read": False, "delivery": "pending"}
    if remote()[0]:
        api("POST", "/rest/v1/contact_messages", json=row)
    else:
        with db() as connection:
            connection.execute("INSERT INTO contact_messages (id,created_at,name,email,phone,message,is_read,delivery) VALUES (:id,:created_at,:name,:email,:phone,:message,:is_read,:delivery)", row)
    return row["id"]


def list_messages(offset=0):
    if remote()[0]:
        return api("GET", "/rest/v1/contact_messages", params={"select": "*", "order": "created_at.desc,id.desc", "limit": 50, "offset": offset}).json()
    with db() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM contact_messages ORDER BY created_at DESC,id DESC LIMIT 50 OFFSET ?", (offset,))]


def update_message(message_id, **changes):
    assert changes and set(changes) <= {"is_read", "delivery"}
    if remote()[0]:
        api("PATCH", "/rest/v1/contact_messages", params={"id": f"eq.{message_id}"}, json=changes)
    else:
        with db() as connection:
            connection.execute("UPDATE contact_messages SET " + ",".join(f"{key}=?" for key in changes) + " WHERE id=?", (*changes.values(), message_id))


def save_image(data):
    identifier = str(uuid4())
    if remote()[0]:
        api("POST", f"/storage/v1/object/site-images/{identifier}.jpg", headers={"Content-Type": "image/jpeg"}, content=data)
    else:
        with db() as connection:
            connection.execute("INSERT INTO media VALUES (?,?)", (identifier, data))
    return f"/media/{identifier}"


def get_image(identifier):
    if remote()[0]:
        return api("GET", f"/storage/v1/object/authenticated/site-images/{identifier}.jpg").content
    with db() as connection:
        row = connection.execute("SELECT data FROM media WHERE id=?", (identifier,)).fetchone()
        return row["data"] if row else None
