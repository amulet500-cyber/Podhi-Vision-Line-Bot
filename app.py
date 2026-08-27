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
GOOGLE_SEARCH_API_KEY = os.getenv('GOOGLE_SEARCH_API_KEY')
SEARCH_ENGINE_ID = os.getenv('SEARCH_ENGINE_ID')

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

# 🏷️ คลังคำสำหรับคัดกรองหมวดอสังหาริมทรัพย์ และ พระเครื่อง
SEARCH_KEYWORDS = [
    "พระเครื่อง", "พระ", "เช่าพระ", "ปล่อยพระ", "ส่องพระ", "เหรียญหลวงพ่อ",
    "ตึก", "อาคาร", "ตึกแถว", "อาคารพานิชย์", "บ้าน", "บ้านเดี่ยว", "ทาวน์เฮาส์", 
    "คอนโด", "ที่ดิน", "ที่ดินเปล่า", "อสังหา", "อสังหาริมทรัพย์", 
    "ซื้อขาย", "ขายเช่า", "ให้เช่า", "ขายบ้าน", "ขายที่ดิน", "ฝากขาย", 
    "ทำเล", "ห้องชุด", "ที่หลุดจำนอง"
]

def start_loading_animation(user_id):
    """เปิดหลอดหมวดจุดไข่ปลา (Loading Animation)"""
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

def search_google_custom_api(query):
    """ค้นหาผ่าน Google Custom Search API เพื่อเอาลิงก์ตรงและหัวข้อประกาศจริงในไทย"""
    api_key = os.getenv('GOOGLE_SEARCH_API_KEY')
    cx = os.getenv('SEARCH_ENGINE_ID')
    
    if not api_key or not cx:
        print("--- DEBUG: GOOGLE_SEARCH_API_KEY or SEARCH_ENGINE_ID is missing ---", flush=True)
        return None

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': api_key,
        'cx': cx,
        'q': query,
        'gl': 'th',
        'hl': 'th',
        'num': 5
    }
    
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        
        items = data.get('items', [])
        if not items:
            return None
            
        lines = [f"🔎 รวมลิงก์ประกาศที่ตรงที่สุดครับ:\n"]
        for i, item in enumerate(items, 1):
            title = item.get('title', 'ประกาศไม่มีชื่อ')
            link = item.get('link', '')
            lines.append(f"{i}. {title}\n👉 {link}")
            
        return "\n\n".join(lines)
    except Exception as e:
        print(f"--- DEBUG Google Custom Search Error: {e} ---", flush=True)
        return None

def ask_gemini(system_instruction, user_msg, image_bytes=None):
    """เรียกใช้ Gemini API ทั่วไป"""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
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

def async_search_and_push(user_id, query):
    """กระบวนการค้นหาหลังบ้าน (Async Thread)"""
    start_loading_animation(user_id)
    
    # ดึงผลลัพธ์ลิงก์ตรงจาก Google API
    reply_text = search_google_custom_api(query)
    
    if not reply_text:
        reply_text = f"ขออภัยครับ ศิษย์น้องไม่สามารถดึงข้อมูลประกาศตรงสำหรับ '{query}' ได้ในขณะนี้"

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
        # 1. ตอบรับทันทีเพื่อเคลียร์ Timeout 5 วินาทีของ LINE
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ศิษย์น้องรับเรื่อง '{user_msg}' แล้วครับ กำลังออกไปค้นหาลิงก์ให้อยู่ รอสักครู่นะครับ...")
        )
        
        # 2. แยก Thread ดึงประกาศจาก Google API หลังบ้าน
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