from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from supabase import create_client, Client

BASE_DIR = Path(__file__).resolve().parent

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zrkyfuhbtrfeklltgbbc.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inpya3lmdWhidHJmZWtsbHRnYmJjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4ODcxMTkyOCwiZXhwIjoyMTA0Mjg3OTI4fQ.ZE0gFAhlxJXmd8UdOfqwinaYhm9zHbSLr5SdBXL1NEU")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SECRET_KEY = os.environ.get("SECRET_KEY", "ec-production-super-secret-key-change-me")
SESSION_DAYS = 30
COOKIE_NAME = "ec_session"

app = FastAPI(title="EC Productions Parent Portal")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.cache = None

if (BASE_DIR / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SECRET_KEY, salt="ec-parent-session-v1")

def get_album_by_token(token: str) -> dict[str, Any] | None:
    res = supabase.table("albums").select("*").eq("token", token).execute()
    if not res.data:
        return None
    return res.data[0]

def get_photos_for_album(album_id: str) -> list[dict[str, str]]:
    res = supabase.table("photos").select("filename, watermarked_url").eq("album_id", album_id).execute()
    return res.data

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "invalid.html", {
        "title": "請掃學生卡上的 QR Code", 
        "detail": "此網站不提供公開目錄。請使用派發的實體卡進入。"
    })

@app.get("/g/s/{token}")
@app.get("/g/c/{token}")
def qr_login(token: str, request: Request):
    album = get_album_by_token(token)
    if not album:
        return templates.TemplateResponse(request, "invalid.html", {
            "title": "無效或未啟用的 QR Code", 
            "detail": "請確認卡片是否正確，或聯絡 EC Productions。"
        }, status_code=404)
    
    resp = RedirectResponse("/gallery", status_code=302)
    session_data = {
        "album_id": album["id"], 
        "title": album["title"], 
        "kind": album["kind"],
        "student_id": album.get("student_id", "")
    }
    token_str = serializer().dumps(session_data)
    resp.set_cookie(
        COOKIE_NAME, token_str,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True, samesite="lax", path="/"
    )
    return resp

@app.get("/gallery", response_class=HTMLResponse)
def gallery(request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return RedirectResponse("/", status_code=302)
    try:
        session_data = serializer().loads(raw)
    except:
        return RedirectResponse("/", status_code=302)

    photos = get_photos_for_album(session_data["album_id"])
    albums = [{
        "id": session_data["album_id"],
        "title": session_data["title"],
        "count": len(photos),
        "cover": photos[0]["watermarked_url"] if photos else None,
        "is_group": session_data["kind"] == "group"
    }]
    return templates.TemplateResponse(request, "gallery.html", {
        "student_title": session_data["title"],
        "albums": albums
    })

@app.get("/gallery/{album_id}", response_class=HTMLResponse)
def album_page(album_id: str, request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return RedirectResponse("/", status_code=302)
    try:
        session_data = serializer().loads(raw)
    except:
        return RedirectResponse("/", status_code=302)
        
    if session_data["album_id"] != album_id:
        raise HTTPException(status_code=403, detail="Forbidden")
        
    photos = get_photos_for_album(album_id)
    return templates.TemplateResponse(request, "album.html", {
        "album_id": album_id,
        "title": session_data["title"],
        "photos": photos
    })

@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp
