import io
import os
import random
import threading
import sqlite3
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, request, jsonify, abort, render_template
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    ImageMessage, QuickReply, QuickReplyButton, MessageAction, URIAction
)
import google.generativeai as genai
from openai import OpenAI
from PIL import Image

app = Flask(__name__, static_folder='static', template_folder='templates')

# ดึงค่า Keys และ LIFF URL จาก Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LIFF_URL = os.getenv('LIFF_URL', 'https://liff.line.me/YOUR_LIFF_ID')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# รายชื่อโมเดลฟรีจาก OpenRouter (เน้นความเร็ว)
FREE_MODELS = [
    "google/gemini-2.0-flash-lite-001:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-7b-instruct:free",
    "mistralai/mistral-7b-instruct:free"
]

# System Instruction ปรับให้ตอบได้ทุกเรื่องแบบผู้ช่วย AI
SYSTEM_INSTRUCTION = (
    "คุณคือ 'ศิษย์น้อง' ผู้ช่วย AI ประจำระบบ 'โพธิ Vision'\n"
    "หน้าที่หลักของคุณคือ:\n"
    "1. ตอบคำถาม ให้คำปรึกษา เขียนโค้ด แปลภาษา วิเคราะห์ข้อมูล และทำนายดวงชะตาพุทธธรรม/ชาดก ได้ทุกเรื่องตามที่ผู้ใช้ถาม\n"
    "2. สรรพนามที่ใช้: แทนตัวเองว่า 'ศิษย์น้อง' และเรียกผู้ใช้ว่า 'ศิษย์พี่' เสมอ ด้วยความนอบน้อมและมีจิตเมตตา\n"
    "3. ภาษาที่ใช้: กระชับ ชัดเจน สละสลวย อ่านง่าย ไม่ใช้สัญลักษณ์แปลกปลอม"
)

# ตั้งค่าฐานข้อมูล SQLite สำหรับจำกัดสิทธิ์ดูดวงรายวัน
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_topic_limits (
            user_id TEXT,
            topic TEXT,
            last_date TEXT,
            PRIMARY KEY (user_id, topic)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_thailand_today():
    """ดึงวันที่ปัจจุบัน เวลาประเทศไทย (UTC+7)"""
    tz_th = timezone(timedelta(hours=7))
    return datetime.now(tz_th).strftime('%Y-%m-%d')

def check_topic_limit(user_id, topic):
    today = get_thailand_today()
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT last_date FROM user_topic_limits WHERE user_id = ? AND topic = ?', (user_id, topic))
    row = cursor.fetchone()
    
    if row and row[0] == today:
        conn.close()
        return False
    
    cursor.execute('''
        INSERT OR REPLACE INTO user_topic_limits (user_id, topic, last_date)
        VALUES (?, ?, ?)
    ''', (user_id, topic, today))
    conn.commit()
    conn.close()
    return True

def get_quick_reply_menu():
    """สร้าง Quick Reply แบบ Label ปุ่มลอยด้านล่าง สะดวกไม่บังหน้าจอ"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🔮 ดวงวันนี้", text="ขอคำทำนายดวงวันนี้จากชาดก")),
        QuickReplyButton(action=MessageAction(label="💼 การงาน", text="ขอคำทำนายการงานจากไพ่ไม้เท้า")),
        QuickReplyButton(action=MessageAction(label="💰 การเงิน", text="ขอคำทำนายการเงินจากไพ่เหรียญ")),
        QuickReplyButton(action=MessageAction(label="❤️ ความรัก", text="ขอคำทำนายความรักจากไพ่ถ้วย")),
        QuickReplyButton(action=MessageAction(label="🛡️ สุขภาพ", text="ขอคำทำนายสุขภาพจากไพ่ดาบ")),
        QuickReplyButton(action=MessageAction(label="⚔️ อุปสรรค", text="ขอคำทำนายอุปสรรคจากไพ่ดาบ")),
        QuickReplyButton(action=MessageAction(label="✍️ พิมพ์ถามได้ทุกเรื่อง", text="ขอคำปรึกษา")),
        QuickReplyButton(action=URIAction(label="📖 เณรZenAiแปลพระไตรปิฏก", uri=LIFF_URL))
    ])

def trigger_loading(user_id, seconds=30):
    try:
        url = "https://api.line.me/v2/bot/chat/loading/start"
        headers = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {"chatId": user_id, "loadingSeconds": seconds}
        requests.post(url, headers=headers, json=data, timeout=3)
    except Exception as e:
        print(f"--- DEBUG Loading Error: {e} ---", flush=True)

def ask_gemini(system_instruction, user_msg, image_bytes=None):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key: return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=system_instruction)
        if image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            prompt = user_msg or "ช่วยวิเคราะห์รูปภาพนี้ในมุมมองธรรมะ..."
            response = model.generate_content([prompt, img], request_options={"timeout": 10})
        else:
            response = model.generate_content(user_msg, request_options={"timeout": 10})
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"--- DEBUG Gemini Error: {e} ---", flush=True)
    return None

def ask_openrouter(system_instruction, user_msg):
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key: return None
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={"HTTP-Referer": "https://podhi-vision-line-bot.onrender.com", "X-Title": "Podhi Vision Bot"}
    )
    for model_name in FREE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": user_msg}],
                timeout=7
            )
            if response and response.choices:
                text = response.choices[0].message.content
                if text: return text.strip()
        except Exception as e:
            print(f"--- DEBUG OpenRouter ({model_name}) Error: {e} ---", flush=True)
            continue
    return None

def generate_ai_response(system_instruction, user_msg, image_bytes=None):
    res = ask_gemini(system_instruction, user_msg, image_bytes)
    if res: return res
    if not image_bytes:
        res = ask_openrouter(system_instruction, user_msg)
        if res: return res
    return "ขออภัยครับศิษย์พี่ ขณะนี้ระบบประมวลผลปลายทางขัดข้องชั่วคราว โปรดลองถามใหม่อีกครั้งนะครับ"

def send_line_reply(reply_token, user_id, message_obj):
    """ส่งตอบกลับด้วย reply_token หาก Token หมดอายุ ให้สลับส่ง push_message อัตโนมัติ"""
    try:
        line_bot_api.reply_message(reply_token, message_obj)
    except Exception as e:
        print(f"--- DEBUG Reply Expired/Failed, Push fallback: {e} ---", flush=True)
        try:
            line_bot_api.push_message(user_id, message_obj)
        except Exception as pe:
            print(f"--- DEBUG Push Failed: {pe} ---", flush=True)

def async_process_and_reply(reply_token, user_id, user_msg):
    trigger_loading(user_id, 30)

    # ตรวจสอบการกดดูดวงเฉพาะหัวข้อเพื่อเช็คสิทธิ์รายวัน
    topic = None
    if "ชาดก" in user_msg or "ดวงวันนี้" in user_msg:
        topic = "jataka"
    elif "ไม้เท้า" in user_msg or "การงาน" in user_msg:
        topic = "work"
    elif "เหรียญ" in user_msg or "การเงิน" in user_msg:
        topic = "money"
    elif "ถ้วย" in user_msg or "ความรัก" in user_msg:
        topic = "love"
    elif "สุขภาพ" in user_msg:
        topic = "health"
    elif "อุปสรรค" in user_msg or "ดาบ" in user_msg:
        topic = "obstacle"

    # ถ้าตรงกับหัวข้อดูดวง 6 เมนูหลัก ให้เช็คจำกัดสิทธิ์รายวัน
    if topic:
        if not check_topic_limit(user_id, topic):
            msg = TextSendMessage(
                text="ศิษย์พี่ได้ใช้สิทธิ์ดูดวงหัวข้อนี้ในวันนี้ไปแล้วครับ โปรดเลือกดูหัวข้ออื่น หรือพิมพ์สอบถามเรื่องอื่นๆ ได้เลยครับ", 
                quick_reply=get_quick_reply_menu()
            )
            send_line_reply(reply_token, user_id, msg)
            return

    # กำหนด Prompt สำหรับส่งให้ AI
    dynamic_instruction = SYSTEM_INSTRUCTION
    ai_prompt = user_msg

    if topic == "jataka":
        jataka_num = random.randint(1, 547)
        ai_prompt = (
            f"ช่วยสุ่มและทำนายดวงชะตาจากชาดก 547 ชาติมา 1 เรื่อง (อิงจากชาดกเรื่องที่ {jataka_num}) "
            f"และขอรูปแบบการแสดงผลตามโครงสร้างนี้เป๊ะๆ:\n\n"
            f"[{jataka_num}] ชื่อชาดก\n"
            f"คำจำกัดความ : (ต้องสั้นกระชับมาก ไม่เกิน 3 คำเท่านั้น ห้ามยาวยืดเยื้อ)\n"
            f"บารมีประจำชาติ : ...บารมี\n"
            f"สภาวะหลัก : (ระบุสถานการณ์หรือปัญหาที่กำลังเผชิญ)\n"
            f"ธรรมะ ทางแก้ : (เสนอแนวทางธรรมะสั้นๆ เพื่อแก้ปัญหา)\n\n"
            f"ขอให้ภาษาคมคาย ลึกซึ้ง ตรงประเด็นครับศิษย์น้อง"
        )
    elif topic == "work":
        card_num = random.randint(1, 10)
        ai_prompt = f"สุ่มไพ่ไม้เท้า 1 ใบจากสำรับ 1-10 (เช่น ไพ่ไม้เท้าใบที่ {card_num}) ทำนายดวงชะตาด้าน 'การงาน' ให้ลึกซึ้ง แม่นยำ"
    elif topic == "money":
        card_num = random.randint(1, 10)
        ai_prompt = f"สุ่มไพ่เหรียญ 1 ใบจากสำรับ 1-10 (เช่น ไพ่เหรียญใบที่ {card_num}) ทำนายดวงชะตาด้าน 'การเงิน' ให้ลึกซึ้ง แม่นยำ"
    elif topic == "love":
        card_num = random.randint(1, 10)
        ai_prompt = f"สุ่มไพ่ถ้วย 1 ใบจากสำรับ 1-10 (เช่น ไพ่ถ้วยใบที่ {card_num}) ทำนายดวงชะตาด้าน 'ความรักและความสัมพันธ์'"
    elif topic == "health":
        card_num = random.randint(1, 10)
        ai_prompt = f"สุ่มไพ่ดาบ 1 ใบจากสำรับ 1-10 (เช่น ไพ่ดาบใบที่ {card_num}) ทำนายเจาะลึกด้าน 'สุขภาพและโรคภัยไข้เจ็บ'"
    elif topic == "obstacle":
        card_num = random.randint(1, 10)
        ai_prompt = f"สุ่มไพ่ดาบ 1 ใบจากสำรับ 1-10 (เช่น ไพ่ดาบใบที่ {card_num}) ทำนายเจาะลึกด้าน 'อุปสรรค ปัญหาข้อขัดแย้ง'"

    # หากไม่ใช่ 6 หัวข้อดูดวง (topic = None) ระบบจะใช้ข้อความ ai_prompt ดั้งเดิมของผู้ใช้ และส่งให้ AI ตอบได้ทุกเรื่องทันที
    reply_text = generate_ai_response(dynamic_instruction, ai_prompt)
    quick_reply = get_quick_reply_menu()
    msg = TextSendMessage(text=reply_text, quick_reply=quick_reply)
    send_line_reply(reply_token, user_id, msg)

# ==================== ROUTE หน้าเว็บ ====================

@app.route("/", methods=['GET'])
@app.route("/jataka", methods=['GET'])
def jataka_page():
    try:
        return render_template('jataka/index.html')
    except Exception:
        return "Podhi Vision System is Running!", 200

@app.route("/pali", methods=['GET'])
@app.route("/liff", methods=['GET'])
def pali_page():
    try:
        return render_template('pali/index.html')
    except Exception:
        return "Pali Translator System is Running!", 200

# ==================== ROUTE API & LINE BOT ====================

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route('/api/translate-word', methods=['POST', 'OPTIONS'])
def translate_pali_word():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response, 200

    data = request.get_json() or {}
    word = data.get('word', '').strip()
    
    if not word:
        res = jsonify({'translation': 'ไม่พบคำศัพท์'})
        res.headers.add('Access-Control-Allow-Origin', '*')
        return res, 400
    
    pali_instruction = (
        "คุณคือผู้เชี่ยวชาญด้านภาษาบาลีหน้าที่ของคุณคือแปลคำศัพท์ภาษาบาลีเป็นภาษาไทย "
        "ตอบให้กระชับ ชัดเจน ตรงประเด็น ความหมายสั้นๆ ไม่ต้องมีคำเกริ่นนำ"
    )
    prompt = f"แปลคำศัพท์ภาษาบาลีคำว่า '{word}' เป็นภาษาไทย ขอความหมายกระชับ ชัดเจน"
    result = generate_ai_response(pali_instruction, prompt)
    
    res = jsonify({'translation': f"{word} – {result}"})
    res.headers.add('Access-Control-Allow-Origin', '*')
    return res

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id
    reply_token = event.reply_token
    threading.Thread(target=async_process_and_reply, args=(reply_token, user_id, user_msg)).start()

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    trigger_loading(user_id, 30)
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = message_content.content
        vision_instruction = SYSTEM_INSTRUCTION + "\nเพิ่มเติม: ศิษย์พี่ได้ส่งรูปภาพมา ให้ช่วยวิเคราะห์รายละเอียด วัตถุมงคล หรือสภาวะธรรมในภาพด้วยความนอบน้อม"
        reply_text = generate_ai_response(vision_instruction, "ช่วยอธิบาย หรือวิเคราะห์สิ่งที่เห็นในภาพนี้ให้ศิษย์พี่หน่อยครับ", image_bytes)
    except Exception as e:
        reply_text = "เกิดข้อผิดพลาดในการประมวลผลรูปภาพครับศิษย์พี่"
    
    quick_reply = get_quick_reply_menu()
    msg = TextSendMessage(text=reply_text, quick_reply=quick_reply)
    send_line_reply(reply_token, user_id, msg)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)