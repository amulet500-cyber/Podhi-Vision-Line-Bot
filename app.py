import io
import os
import urllib.parse
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

def generate_thai_search_links(query):
    """สร้างรายการลิงก์ตรงค้นหาจากเว็บอสังหาริมทรัพย์และพระเครื่องชั้นนำของไทย"""
    encoded_query = urllib.parse.quote(query.strip())
    
    # แยกประเภทคีย์เวิร์ด (พระเครื่อง หรือ อสังหาริมทรัพย์)
    is_amulet = any(k in query for k in ["พระเครื่อง", "พระ", "เช่าพระ", "ปล่อยพระ", "ส่องพระ", "เหรียญหลวงพ่อ"])
    
    links = []
    if is_amulet:
        links = [
            {"title": f"ค้นหา '{query}' บน ท่าพระจันทร์ดอทคอม (Thaprachan)", "url": f"https://www.thaprachan.com/search_amulet.php?keyword={encoded_query}"},
            {"title": f"ค้นหา '{query}' บน Kaidee Amulet", "url": f"https://www.kaidee.com/c34-amulet/?q={encoded_query}"},
            {"title": f"ค้นหา '{query}' บน Web-Pra (เว็บพระ)", "url": f"https://www.web-pra.com/auction/search?q={encoded_query}"},
            {"title": f"ค้นหา '{query}' บน Ennxo Amulet", "url": f"https://www.ennxo.com/amulet?q={encoded_query}"},
            {"title": f"ค้นหา '{query}' บน Google ประเทศไทย (ผลลัพธ์พระเครื่อง)", "url": f"https://www.google.co.th/search?q={encoded_query}+ site:thaprachan.com+OR+site:g-pra.com+OR+site:uamulet.com"}
        ]
    else:
        links = [
            {"title": f"ค้นหาประกาศ '{query}' บน DDproperty", "url": f"https://www.ddproperty.com/property-for-sale?freetext={encoded_query}"},
            {"title": f"ค้นหาประกาศ '{query}' บน Kaidee Property", "url": f"https://www.kaidee.com/c16-property/?q={encoded_query}"},
            {"title": f"ค้นหาประกาศ '{query}' บน Propertyhub", "url": f"https://propertyhub.in.th/ค้นหา/{encoded_query}"},
            {"title": f"ค้นหาประกาศ '{query}' บน Ennxo Property", "url": f"https://www.ennxo.com/property?q={encoded_query}"},
            {"title": f"ค้นหาประกาศ '{query}' บน Baania", "url": f"https://baania.com/th/search?q={encoded_query}"}
        ]
        
    lines = [f"🔎 รวมลิงก์ประกาศภาษาไทยที่เกี่ยวข้องครับ:\n"]
    for i, item in enumerate(links, 1):
        lines.append(f"{i}. {item['title']}\n👉 {item['url']}")
        
    return "\n\n".join(lines)

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
    reply_text = generate_thai_search_links(query)
    
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
        
        # 2. แยก Thread สร้างลิงก์ตรงค้นหาเว็บไทยหลังบ้าน
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