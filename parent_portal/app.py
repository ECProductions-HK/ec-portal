from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Request, Response, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer
from supabase import create_client, Client
import uuid

BASE_DIR = Path(__file__).resolve().parent

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://zrkyfuhbtrfeklltgbbc.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your-service-role-key")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SECRET_KEY = os.environ.get("SECRET_KEY", "ec-production-super-secret-key-change-me")
SESSION_DAYS = 30
COOKIE_NAME = "ec_session"
OPS_WHATSAPP = "85292653339"

# 🌟 新增：後台管理員設定
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ec2026admin") # 預設密碼
ADMIN_COOKIE_NAME = "ec_admin_session"

app = FastAPI(title="EC Productions Parent Portal")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.cache = None

static_dir = BASE_DIR / "static"
if not static_dir.is_dir() and (BASE_DIR.parent / "static").is_dir():
    static_dir = BASE_DIR.parent / "static"

if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SECRET_KEY, salt="ec-parent-session-v1")

def get_album_by_token(token: str) -> dict[str, Any] | None:
    res = supabase.table("albums").select("*").eq("token", token).execute()
    return res.data[0] if res.data else None

def get_photos_for_album(album_id: str) -> list[dict[str, str]]:
    res = supabase.table("photos").select("filename, watermarked_url").eq("album_id", album_id).execute()
    return res.data

# ==========================================
# 面向家長：前端相簿與下單路由
# ==========================================

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
def gallery_redirect(request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return RedirectResponse("/", status_code=302)
    try:
        session_data = serializer().loads(raw)
        return RedirectResponse(f"/gallery/{session_data['album_id']}", status_code=302)
    except:
        return RedirectResponse("/", status_code=302)

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
    student_name: str = Form(""),
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
    final_student_title = session_data["title"]
    if is_group and student_name.strip():
        final_student_title = f"{session_data['title']} (學生: {student_name.strip()})"

    total_amount = 0
    parsed_items = []

    for entry in item_data:
        parts = entry.split("|")
        if len(parts) == 3:
            filename, opt, qty_str = parts
            try:
                qty = int(qty_str)
            except ValueError:
                qty = 1
        elif len(parts) == 2:
            filename, opt = parts
            qty = 1
        else:
            continue
            
        if qty <= 0:
            continue
        
        if opt == "5r_lam":
            price = 7
            opt_name = "5R過膠"
        elif opt == "5r_frame":
            price = 10
            opt_name = "5R過膠連框裱"
        elif opt == "8r_lam":
            price = 13
            opt_name = "8R過膠"
        elif opt == "8r_frame":
            price = 15
            opt_name = "8R過膠連框裱"
        else:
            price = 7
            opt_name = "5R過膠"
            
        total_amount += price * qty
        parsed_items.append({
            "filename": filename,
            "option_name": opt_name,
            "qty": qty,
            "price": price * qty
        })

    receipt_filename = f"receipts/{uuid.uuid4()}_{receipt.filename}"
    receipt_bytes = await receipt.read()
    
    try:
        supabase.storage.from_("receipts").upload(receipt_filename, receipt_bytes, file_options={"content-type": receipt.content_type})
        receipt_url = supabase.storage.from_("receipts").get_public_url(receipt_filename)
    except Exception as e:
        receipt_url = "upload_failed_or_pending"

    items_text_list = "\n".join([f"- {item['filename']} ({item['option_name']} x {item['qty']}) - ${item['price']} HKD" for item in parsed_items])

    try:
        supabase.table("orders").insert({
            "album_id": album_id,
            "student_title": final_student_title,
            "total_amount": total_amount,
            "contact_phone": contact_phone,
            "receipt_url": receipt_url,
            "payment_status": "pending_verification",
            "items": parsed_items
        }).execute()
    except Exception as e:
        print("DB order insert error:", e)

    whatsapp_message = (
        f"【新選相訂單通知】\n"
        f"對象: {final_student_title}\n"
        f"聯絡電話: {contact_phone}\n"
        f"總金額: ${total_amount} HKD\n\n"
        f"選購明細:\n{items_text_list}\n\n"
        f"轉帳收據截圖: {receipt_url}"
    )

    return templates.TemplateResponse(request, "success.html", {
        "student_title": final_student_title,
        "total_amount": total_amount,
        "whatsapp_message": whatsapp_message,
        "ops_whatsapp": OPS_WHATSAPP,
        "album_id": album_id
    })

@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp

# ==========================================
# 🌟 面向後勤：CMS 圖形化後台管理系統路由
# ==========================================

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    # 檢查是否已登入
    if request.cookies.get(ADMIN_COOKIE_NAME) != "authenticated":
        return templates.TemplateResponse(request, "admin_login.html", {})
    
    # 獲取所有訂單，依照建立時間由新到舊排序
    try:
        res = supabase.table("orders").select("*").order("created_at", desc=True).execute()
        orders_data = res.data
    except Exception as e:
        orders_data = []
        print("Fetch orders error:", e)

    return templates.TemplateResponse(request, "admin.html", {"orders": orders_data})

@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, password: str = Form(...)):
    # 驗證密碼
    if password == ADMIN_PASSWORD:
        resp = RedirectResponse("/admin", status_code=302)
        resp.set_cookie(ADMIN_COOKIE_NAME, "authenticated", max_age=86400 * 7, httponly=True) # 保持登入 7 天
        return resp
    
    return templates.TemplateResponse(request, "admin_login.html", {"error": "密碼錯誤，請重新輸入。"})

@app.post("/admin/update_status")
def admin_update_status(request: Request, order_id: int = Form(...), new_status: str = Form(...)):
    # 檢查權限
    if request.cookies.get(ADMIN_COOKIE_NAME) != "authenticated":
        return RedirectResponse("/admin", status_code=302)
    
    # 更新資料庫中的付款狀態
    try:
        supabase.table("orders").update({"payment_status": new_status}).eq("id", order_id).execute()
    except Exception as e:
        print("Update status error:", e)
        
    return RedirectResponse("/admin", status_code=302)

@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin", status_code=302)
    resp.delete_cookie(ADMIN_COOKIE_NAME, path="/")
    return resp