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

    order_info = {
        "album_id": album_id,
        "student_title": session_data["title"],
        "kind": session_data["kind"],
        "total_amount": total_amount,
        "contact_phone": contact_phone,
        "items": parsed_items
    }

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

    send_order_email(order_info, receipt_url)

    return templates.TemplateResponse(request, "success.html", {
        "student_title": session_data["title"],
        "total_amount": total_amount
    })