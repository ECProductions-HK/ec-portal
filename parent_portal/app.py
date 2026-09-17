from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Request, Response, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from supabase import create_client, Client
import uuid

BASE_DIR = Path(__file__).resolve().parent

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zrkyfuhbtrfeklltgbbc.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your-service-role-key")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SECRET_KEY = os.environ.get("SECRET_KEY", "ec-production-super-secret-key-change-me")
SESSION_DAYS = 30
COOKIE_NAME = "ec_session"

# 公司接收 WhatsApp 訂單的電話號碼（已直接寫入您的號碼）
OPS_WHATSAPP = "85292653339"

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
    
    resp = RedirectResponse(f"/gallery/{album['id']}", status_code=302)
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
    is_group = session_data["kind"] == "group"
    
    return templates.TemplateResponse(request, "album.html", {
        "album_id": album_id,
        "title": session_data["title"],
        "photos": photos,
        "is_group": is_group
    })

@app.post("/cart/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, selected_photos: list[str] = Form(...), album_id: str = Form(...)):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return RedirectResponse("/", status_code=302)
    try:
        session_data = serializer().loads(raw)
    except:
        return RedirectResponse("/", status_code=302)

    if not selected_photos:
        return RedirectResponse(f"/gallery/{album_id}", status_code=302)

    is_group = session_data["kind"] == "group"
    
    return templates.TemplateResponse(request, "checkout.html", {
        "album_id": album_id,
        "selected_photos": selected_photos,
        "student_title": session_data["title"],
        "is_group": is_group
    })

@app.post("/order/submit", response_class=HTMLResponse)
async def order_submit(
    request: Request,
    album_id: str = Form(...),
    contact_phone: str = Form(...),
    receipt: UploadFile = File(...),
    item_data: list[str] = Form(...)
):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return RedirectResponse("/", status_code=302)
    try:
        session_data = serializer().loads(raw)
    except:
        return RedirectResponse("/", status_code=302)

    is_group = session_data["kind"] == "group"
    total_amount = 0
    parsed_items = []

    for entry in item_data:
        parts = entry.split("|")
        if len(parts) != 2:
            continue
        filename, opt = parts
        
        if not is_group:
            if opt == "dozen2":
                price = 20
                opt_name = "兩打 (20 HKD)"
            else:
                price = 12
                opt_name = "一打 (12 HKD)"
        else:
            if opt == "5r":
                price = 100
                opt_name = "5R 一張 (100 HKD)"
            else:
                price = 50
                opt_name = "4R 一張 (50 HKD)"
                
        total_amount += price
        parsed_items.append({
            "filename": filename,
            "option_name": opt_name,
            "price": price
        })

    receipt_filename = f"receipts/{uuid.uuid4()}_{receipt.filename}"
    receipt_bytes = await receipt.read()
    
    try:
        supabase.storage.from_("receipts").upload(receipt_filename, receipt_bytes, file_options={"content-type": receipt.content_type})
        receipt_url = supabase.storage.from_("receipts").get_public_url(receipt_filename)
    except Exception as e:
        receipt_url = "upload_failed_or_pending"

    items_text_list = "\n".join([f"- {item['filename']} ({item['option_name']}) - ${item['price']} HKD" for item in parsed_items])

    try:
        supabase.table("orders").insert({
            "album_id": album_id,
            "student_title": session_data["title"],
            "total_amount": total_amount,
            "contact_phone": contact_phone,
            "receipt_url": receipt_url,
            "payment_status": "pending_verification"
        }).execute()
    except Exception as e:
        print("DB order insert error:", e)

    whatsapp_message = (
        f"【新選相訂單通知】\n"
        f"學生/相簿: {session_data['title']}\n"
        f"聯絡電話: {contact_phone}\n"
        f"總金額: ${total_amount} HKD\n\n"
        f"選購明細:\n{items_text_list}\n\n"
        f"轉帳收據截圖: {receipt_url}"
    )

    return templates.TemplateResponse(request, "success.html", {
        "student_title": session_data["title"],
        "total_amount": total_amount,
        "whatsapp_message": whatsapp_message,
        "ops_whatsapp": OPS_WHATSAPP
    })

@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp
