from pathlib import Path
from datetime import datetime, timezone

from app.content import TEAM, EMAIL_SIGNUP_URL, DONATE_URL, CONTACT_EMAIL, CONTACT_PHONE, INSTAGRAM_URL

from dotenv import load_dotenv
from app.contact import router as contact_router

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from app.admin import router as admin_router
from app import storage
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env.local")
load_dotenv(BASE_DIR.parent / ".env")

app = FastAPI(title="People Person Foundation")
app.include_router(contact_router)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def page_context(active_page: str):
    def image_path(stem):
        for extension in ("png", "webp", "jpg", "jpeg", "svg"):
            path = f"images/{stem}.{extension}"
            if (BASE_DIR / "static" / path).is_file():
                return path
        return None

    return {
        "team": TEAM,
        "logo": image_path("logo"),
        "hero_image": image_path("community"),
        "current_year": datetime.now(timezone.utc).year,
        "active_page": active_page,
        "contact_email": CONTACT_EMAIL,
        "contact_phone": CONTACT_PHONE,
        "phone_href": "tel:" + "".join(c for c in CONTACT_PHONE if c.isdigit() or c == "+") if CONTACT_PHONE else None,
        "instagram_url": INSTAGRAM_URL,
        "destinations": {"signup": EMAIL_SIGNUP_URL, "donate": DONATE_URL, "contact": "/contact"},
    }


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home(request: Request):
    content = await run_in_threadpool(storage.get_site)
    return templates.TemplateResponse(request=request, name="index.html", context={**page_context("home"), **content})


@app.get("/contact", response_class=HTMLResponse, include_in_schema=False)
async def contact(request: Request):
    return templates.TemplateResponse(request=request, name="contact.html", context=page_context("contact"))



@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(storage.StorageError)
async def storage_failure(request: Request, exc):
    status = 409 if isinstance(exc, storage.ConflictError) else 503
    return JSONResponse({"detail": str(exc)}, status_code=status, headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def protect_admin_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/admin" or request.url.path.startswith("/admin/"):
        response.headers.update({
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'",
        })
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response
