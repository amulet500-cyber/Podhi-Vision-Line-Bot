import io
import os
import threading
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    ImageMessage
)
import google.generativeai as genai
from openai import OpenAI
from PIL import Image

app = Flask(__name__)

# ดึงค่า Keys จากระบบผ่าน Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

# ตั้งค่า LINE SDK
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# รายชื่อโมเดล OpenRouter (สำรอง)
FREE_MODELS = [
    "openrouter/auto",
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free"
]

# 🏷️ คลังคำสำหรับคัดกรองหมวดอสังหาริมทรัพย์ พระเครื่อง และการซื้อขายเช่า
SEARCH_KEYWORDS = [
    "พระเครื่อง", "พระ", "เช่าพระ", "ปล่อยพระ", "ส่องพระ", "เหรียญหลวงพ่อ",
    "ตึก", "อาคาร", "ตึกแถว", "อาคารพานิชย์", "บ้าน", "บ้านเดี่ยว", "ทาวน์เฮาส์", 
    "คอนโด", "ที่ดิน", "ที่ดินเปล่า", "อสังหา", "อสังหาริมทรัพย์", 
    "ซื้อขาย", "ขายเช่า", "ให้เช่า", "ขายบ้าน", "ขายที่ดิน", "ฝากขาย", 
    "ทำเล", "ห้องชุด", "ที่หลุดจำนอง"
]

def start_loading_animation(user_id):
    """เรียกใช้ LINE API เปิดหลอดหมวดจุดไข่ปลา (Loading Animation) สูงสุด 60 วินาที ฟรีไม่เสียโควตา"""
    try:
        url = "https://api.line.me/v2/bot/chat/loading/start"
        headers = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {
            "chatId": user_id,
            "loadingSeconds": 60
        }
        requests.post(url, headers=headers, json=data, timeout=5)
    except Exception as e:
        print(f"--- DEBUG Loading Animation Error: {e} ---", flush=True)

def live_search_web(query, max_results=15):
    """ทำการค้นหาลิงก์สดบนอินเทอร์เน็ต"""
    results = []
    try:
        from duckduckgo_search import DDGS
        # คลีนข้อความ ตัดคำกริยา/คำขยะออกเพื่อให้คำค้นหากระชับ
        clean_query = query.replace("หา", "").replace("อยากได้", "").replace("ราคา", "").strip()
        
        with DDGS() as ddgs:
            search_gen = ddgs.text(clean_query, region='th-th', max_results=max_results)
            if search_gen:
                for r in search_gen:
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")
                    })
    except Exception as e:
        print(f"--- DEBUG Live Search Error: {e} ---", flush=True)
    return results

def ask_gemini(system_instruction, user_msg, image_bytes=None):
    """เรียกใช้ Gemini API เป็นตัวหลัก"""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("--- DEBUG: GEMINI_API_KEY is MISSING! ---", flush=True)
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=system_instruction
        )
        
        if image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            response = model.generate_content([user_msg or "ช่วยอธิบายรายละเอียด หรือวิเคราะห์สิ่งที่เห็นในภาพนี้ให้หน่อยครับ", img])
        else:
            response = model.generate_content(user_msg)
            
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"--- DEBUG Gemini Error: {type(e).__name__} -> {e} ---", flush=True)
        
    return None

def ask_openrouter(system_instruction, user_msg):
    """เรียกใช้ OpenRouter เป็นระบบสำรอง"""
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        return None

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://podhi-vision-line-bot-1.onrender.com",
            "X-Title": "Podhi Vision Bot",
        }
    )

    for model_name in FREE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_msg}
                ],
                timeout=5
            )
            if response and response.choices and len(response.choices) > 0:
                text = response.choices[0].message.content
                if text:
                    return text.strip()
        except Exception as e:
            continue

    return None

def generate_ai_response(system_instruction, user_msg, image_bytes=None):
    result = ask_gemini(system_instruction, user_msg, image_bytes)
    if result:
        return result

    if not image_bytes:
        result = ask_openrouter(system_instruction, user_msg)
        if result:
            return result

    return None

def format_links_with_ai(query, raw_results):
    """ให้ AI สกัดจัดรูปแบบ 'ชื่อประกาศ + ลิงก์'"""
    if not raw_results:
        return f"ขออภัยครับ ศิษย์น้องไม่พบลิงก์ประกาศที่เกี่ยวข้องกับ '{query}' ในขณะนี้"

    text_block = "\n".join([f"- {r['title']} | URL: {r['url']}" for r in raw_results[:5]])
    
    system_instruction = (
        "คุณคือผู้ช่วยสรุปรายการประกาศ แสดงรายการลิงก์ทั้งหมดที่ได้รับมา ห้ามตัดลิงก์ทิ้ง "
        "ห้ามตอบว่าไม่พบข้อมูล ให้แสดงรายการตามโครงสร้างนี้เท่านั้น:\n"
        "🔎 รวมลิงก์ประกาศที่เกี่ยวข้องครับ:\n\n"
        "1. [ชื่อประกาศสั้นๆ]\n👉 [URL]\n\n"
        "2. [ชื่อประกาศสั้นๆ]\n👉 [URL]"
    )
    
    prompt = f"หัวข้อการค้นหา: {query}\n\nรายการข้อมูลดิบ:\n{text_block}"
    formatted = generate_ai_response(system_instruction, prompt)
    
    # ถ้า AI ตอบกลับมาแบบปกติและไม่มีคำปฏิเสธ ให้ใช้ค่าจาก AI
    if formatted and "ไม่พบ" not in formatted:
        return formatted

    # สำรอง: ดึง 5 ลิงก์แรกมาแสดงตรงๆ ป้องกัน AI ปฏิเสธข้อมูล
    lines = [f"🔎 รวมลิงก์ประกาศที่พบสำหรับ '{query}' ครับ:\n"]
    for i, r in enumerate(raw_results[:5], 1):
        lines.append(f"{i}. {r['title']}\n👉 {r['url']}")
    return "\n\n".join(lines)

def async_search_and_push(user_id, query):
    """กระบวนการค้นหาหลังบ้าน (Async Thread) เพื่อไม่ให้ชน Timeout 5 วินาที"""
    start_loading_animation(user_id)
    raw_results = live_search_web(query, max_results=15)
    reply_text = format_links_with_ai(query, raw_results)
    
    try:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        print(f"--- DEBUG Push Message Error: {e} ---", flush=True)

def ask_general_ai(user_msg):
    system_instruction = (
        "คุณคือผู้ช่วย AI ของระบบ 'โพธิ Vision' ตอบคำถามทั่วไปอย่างสุภาพ อ่อนโยน มีเมตตา "
        "กระชับ สละสลวย และให้ข้อมูลที่เป็นประโยชน์แก่ผู้ถาม"
    )
    result = generate_ai_response(system_instruction, user_msg)
    if result:
        return result
    return "ขออภัยครับ ขณะนี้ระบบประมวลผลขัดข้องชั่วคราว โปรดลองใหม่อีกครั้ง"

@app.route("/", methods=['GET'])
def health_check():
    return "Podhi Vision Bot is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 📩 จัดการข้อความตัวอักษร
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id

    # ตรวจสอบว่าเข้าเงื่อนไขคีย์เวิร์ด ซื้อ ขาย เช่า พระเครื่อง อสังหาฯ หรือไม่
    is_search_query = any(keyword in user_msg for keyword in SEARCH_KEYWORDS)

    if is_search_query:
        # 1. ตอบรับทันทีเพื่อเคลียร์ Timeout 5 วินาทีของ LINE (ไม่เสียโควตา)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ศิษย์น้องรับเรื่อง '{user_msg}' แล้วครับ กำลังออกไปค้นหาลิงก์ให้อยู่ รอสักครู่นะครับ...")
        )
        
        # 2. แยก Thread สแกนค้นสดหลังบ้าน + ยิง Push Message คำตอบจริงกลับทีหลัง
        threading.Thread(target=async_search_and_push, args=(user_id, user_msg)).start()
        
    else:
        # พูดคุยทั่วไปกับ AI ตามปกติ
        reply_text = ask_general_ai(user_msg)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

# 🖼️ จัดการข้อความรูปภาพ (Vision)
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = message_content.content

        system_instruction = (
            "คุณคือผู้ช่วย AI ของระบบ 'โพธิ Vision' ช่วยวิเคราะห์ หรืออธิบายรูปภาพที่ผู้ใช้ส่งมา "
            "เช่น พระเครื่อง อสังหาริมทรัพย์ สิ่งของ หรือสถานที่ ตอบอย่างสุภาพ สละสลวย และชัดเจน"
        )
        
        reply_text = generate_ai_response(
            system_instruction=system_instruction, 
            user_msg="ช่วยอธิบาย หรือวิเคราะห์สิ่งที่เห็นในภาพนี้ให้หน่อยครับ", 
            image_bytes=image_bytes
        )

        if not reply_text:
            reply_text = "ขออภัยครับ ไม่สามารถวิเคราะห์รูปภาพได้ในขณะนี้ โปรดลองใหม่อีกครั้ง"

    except Exception as e:
        print(f"--- DEBUG Image Handler Error: {e} ---", flush=True)
        reply_text = "เกิดข้อผิดพลาดในการประมวลผลรูปภาพครับ"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)