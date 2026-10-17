"""Password-protected editor, signed sessions, CSRF checks, and image uploads."""
import hashlib
import hmac
import io
import os
import secrets
import threading
import time
import warnings
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import storage

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
SESSION_COOKIE = "ppf_admin"
MAX_AGE = 8 * 60 * 60
LOGIN_FAILURES = []
LOGIN_LOCK = threading.Lock()


def signer():
    password = os.getenv("ADMIN_PASSWORD", "")
    secret = os.getenv("ADMIN_SESSION_SECRET", "")
    if len(password) < 16 or len(secret) < 32:
        raise HTTPException(503, "Admin is not configured. Set ADMIN_PASSWORD and ADMIN_SESSION_SECRET.")
    # Changing either secret invalidates existing sessions.
    key = hmac.new(secret.encode(), password.encode(), hashlib.sha256).hexdigest()
    return URLSafeTimedSerializer(key, salt="ppf-admin-v1")


def read_session(request):
    try:
        data = signer().loads(request.cookies.get(SESSION_COOKIE, ""), max_age=MAX_AGE)
        return data if data.get("admin") is True else None
    except BadSignature:
        return None


def require_admin(request: Request):
    session = read_session(request)
    if not session:
        raise HTTPException(401, "Please sign in again.")
    return session


def require_write(request: Request, session=Depends(require_admin)):
    token = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(token, session["csrf"]):
        raise HTTPException(403, "Invalid session token. Reload the page.")
    return session


def cookie_options(request):
    return {"httponly": True, "samesite": "strict", "secure": request.url.scheme == "https" or bool(os.getenv("VERCEL")), "path": "/admin"}


@router.get("/admin", include_in_schema=False)
def dashboard(request: Request):
    if not read_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request=request, name="admin/dashboard.html", context={"csrf": read_session(request)["csrf"]})


@router.get("/admin/login", include_in_schema=False)
def login_page(request: Request):
    if read_session(request):
        return RedirectResponse("/admin", status_code=303)
    token = signer().dumps({"nonce": secrets.token_urlsafe(24)})
    response = templates.TemplateResponse(request=request, name="admin/login.html", context={"csrf": token})
    response.set_cookie("ppf_login", token, max_age=900, **cookie_options(request))
    return response


class Login(BaseModel):
    password: str = Field(max_length=512)
    csrf: str = Field(max_length=1024)


@router.post("/admin/login", include_in_schema=False)
def login(request: Request, body: Login):
    if not hmac.compare_digest(body.csrf, request.cookies.get("ppf_login", "")):
        raise HTTPException(403, "Reload the login page and try again.")
    try:
        signer().loads(body.csrf, max_age=900)
    except BadSignature:
        raise HTTPException(403, "Reload the login page and try again.") from None
    with LOGIN_LOCK:
        now = time.monotonic()
        LOGIN_FAILURES[:] = [t for t in LOGIN_FAILURES if now - t < 60]
        if len(LOGIN_FAILURES) >= 10:
            raise HTTPException(429, "Too many attempts. Wait one minute and try again.")
        if not hmac.compare_digest(hashlib.sha256(body.password.encode()).digest(), hashlib.sha256(os.environ["ADMIN_PASSWORD"].encode()).digest()):
            LOGIN_FAILURES.append(now)
            raise HTTPException(401, "Incorrect password.")
    response = Response(status_code=204)
    response.set_cookie(SESSION_COOKIE, signer().dumps({"admin": True, "csrf": secrets.token_urlsafe(32)}), max_age=MAX_AGE, **cookie_options(request))
    response.delete_cookie("ppf_login", path="/admin")
    return response


@router.post("/admin/logout", dependencies=[Depends(require_write)], include_in_schema=False)
def logout():
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return response


class TeamMember(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    image: str | None = None

    @field_validator("image")
    @classmethod
    def image_path(cls, value):
        if value:
            if not value.startswith("/media/"):
                raise ValueError("Upload a photo using the image picker.")
            UUID(value.removeprefix("/media/"))
        return value


class SiteContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    revision: int = Field(ge=0)
    hero_image: str
    hero_alt: str = Field(min_length=1, max_length=500)
    about_title: str = Field(min_length=1, max_length=200)
    about_lead: str = Field(min_length=1, max_length=1000)
    about_body: str = Field(min_length=1, max_length=10000)
    team: list[TeamMember] = Field(max_length=100)

    @field_validator("hero_image")
    @classmethod
    def hero_path(cls, value):
        if value != "/static/images/community.png":
            TeamMember.image_path(value)
            if not value:
                raise ValueError("Choose a homepage photo.")
        return value

    @field_validator("team")
    @classmethod
    def unique_members(cls, value):
        if len({member.id for member in value}) != len(value):
            raise ValueError("Team members must have unique identifiers.")
        return value


@router.get("/admin/api/content", dependencies=[Depends(require_admin)], include_in_schema=False)
def get_content():
    return storage.get_site()


@router.put("/admin/api/content", dependencies=[Depends(require_write)], include_in_schema=False)
def put_content(body: SiteContent):
    return storage.save_site(body.model_dump(mode="json"))


@router.post("/admin/api/images", dependencies=[Depends(require_write)], include_in_schema=False)
def upload_image(file: UploadFile):
    data = file.file.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(413, "Choose an image smaller than 4 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported format")
                if source.width * source.height > 20_000_000:
                    raise ValueError("Image dimensions exceed the limit")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1800, 1800))
                output = io.BytesIO()
                image.save(output, "JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Choose a valid JPG, PNG, or WebP image.") from None
    return {"url": storage.save_image(output.getvalue())}


@router.get("/admin/api/messages", dependencies=[Depends(require_admin)], include_in_schema=False)
def messages(offset: int = 0, is_read: bool | None = None):
    if offset < 0:
        raise HTTPException(422, "Invalid page.")
    return storage.list_messages(offset, is_read)


class MessageState(BaseModel):
    is_read: bool


@router.patch("/admin/api/messages/{message_id}", dependencies=[Depends(require_write)], include_in_schema=False)
def mark_message(message_id: UUID, body: MessageState):
    storage.update_message(str(message_id), is_read=body.is_read)
    return {"ok": True}


@router.get("/media/{image_id}", include_in_schema=False)
def image(image_id: UUID):
    data = storage.get_image(str(image_id))
    if data is None:
        raise HTTPException(404, "Image not found.")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})
