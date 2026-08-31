import io
import os
import random
import threading
import sqlite3
import base64
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, request, jsonify, abort, render_template
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    ImageMessage, QuickReply, QuickReplyButton, MessageAction, URIAction,
    FlexSendMessage
)

app = Flask(__name__, static_folder='static', template_folder='templates')

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

# LIFF URL สำหรับเปิดมินิแอพแปลพระไตรปิฎก
LIFF_URL = os.getenv('LIFF_URL', 'https://liff.line.me/2011300777-uomwbIjN')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# รายชื่อโมเดล Gemini สำรองเรียงตามลำดับ
GEMINI_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro"
]

# รายชื่อโมเดล OpenRouter ฟรีที่ใช้งานได้จริงในปัจจุบัน
OPENROUTER_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "openrouter/auto"
]

SYSTEM_INSTRUCTION = (
    "คุณคือ 'ศิษย์น้อง' ผู้ช่วย AI ประจำระบบ 'โพธิ Vision'\n"
    "หน้าที่หลักของคุณคือ:\n"
    "1. ตอบคำถาม ให้คำปรึกษา เขียนโค้ด แปลภาษา และทำนายดวงชะตาพุทธธรรม/ชาดก 547 ชาติ ไพ่ทาโรต์ ได้ทุกเรื่อง\n"
    "2. สรรพนามที่ใช้: แทนตัวเองว่า 'ศิษย์น้อง' และเรียกผู้ใช้ว่า 'ศิษย์พี่' เสมอ ด้วยความนอบน้อมและมีจิตเมตตา\n"
    "3. ภาษาที่ใช้: กระชับ ชัดเจน สละสลวย อ่านง่าย ไม่ใช้สัญลักษณ์แปลกปลอม"
)

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
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🔮 ดวงวันนี้", text="ขอคำทำนายดวงวันนี้จากชาดก")),
        QuickReplyButton(action=MessageAction(label="💼 การงาน", text="ขอคำทำนายการงานจากไพ่ไม้เท้า")),
        QuickReplyButton(action=MessageAction(label="💰 การเงิน", text="ขอคำทำนายการเงินจากไพ่เหรียญ")),
        QuickReplyButton(action=MessageAction(label="❤️ ความรัก", text="ขอคำทำนายความรักจากไพ่ถ้วย")),
        QuickReplyButton(action=MessageAction(label="🛡️ สุขภาพ", text="ขอคำทำนายสุขภาพจากไพ่ดาบ")),
        QuickReplyButton(action=MessageAction(label="⚔️ อุปสรรค", text="ขอคำทำนายอุปสรรคจากไพ่ดาบ")),
        QuickReplyButton(action=MessageAction(label="✍️ ถามได้ทุกเรื่อง", text="ขอคำปรึกษา")),
        QuickReplyButton(action=URIAction(label="📖 แปลพระไตรปิฎก", uri=LIFF_URL))
    ])

def create_menu_flex_card():
    flex_contents = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🔮 โพธิ Vision พุทธธรรมพยากรณ์", "weight": "bold", "size": "lg", "color": "#1DB446"},
                {"type": "text", "text": "เลือกหัวข้อขอคำทำนาย หรือใช้งานแอปแปลพระไตรปิฎกด้านล่างได้เลยครับ", "wrap": True, "color": "#666666", "size": "sm", "margin": "md"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#1DB446", "action": {"type": "message", "label": "🔮 ดวงวันนี้ (ชาดก)", "text": "ขอคำทำนายดวงวันนี้จากชาดก"}},
                {"type": "button", "style": "secondary", "action": {"type": "message", "label": "💼 การงาน (ไม้เท้า)", "text": "ขอคำทำนายการงานจากไพ่ไม้เท้า"}},
                {"type": "button", "style": "secondary", "action": {"type": "message", "label": "💰 การเงิน (เหรียญ)", "text": "ขอคำทำนายการเงินจากไพ่เหรียญ"}},
                {"type": "button", "style": "secondary", "action": {"type": "message", "label": "❤️ ความรัก (ถ้วย)", "text": "ขอคำทำนายความรักจากไพ่ถ้วย"}},
                {"type": "button", "style": "secondary", "action": {"type": "message", "label": "🛡️ สุขภาพ (ดาบ)", "text": "ขอคำทำนายสุขภาพจากไพ่ดาบ"}},
                {"type": "button", "style": "secondary", "action": {"type": "message", "label": "⚔️ อุปสรรค (ดาบ)", "text": "ขอคำทำนายอุปสรรคจากไพ่ดาบ"}},
                {"type": "button", "style": "primary", "color": "#06C755", "action": {"type": "uri", "label": "📖 แปลพระไตรปิฎก", "uri": LIFF_URL}}
            ]
        }
    }
    return FlexSendMessage(alt_text="🔮 เมนูพุทธธรรมพยากรณ์ & แปลพระไตรปิฎก", contents=flex_contents)

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
    if not api_key:
        return None
    
    for m_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        
        parts = []
        if user_msg:
            parts.append({"text": user_msg})
        if image_bytes:
            img_b64 = base64.b64encode(image_bytes).decode('utf-8')
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": img_b64
                }
            })
            
        payload = {
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [{"parts": parts}]
        }
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                text = data['candidates'][0]['content']['parts'][0]['text']
                if text:
                    return text.strip()
            else:
                print(f"--- DEBUG Gemini Model {m_name} Error ({res.status_code}): {res.text} ---", flush=True)
        except Exception as e:
            print(f"--- DEBUG Gemini Exception ({m_name}): {e} ---", flush=True)
            continue
    return None

def ask_openrouter(system_instruction, user_msg):
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        return None
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://podhi-vision-line-bot-1.onrender.com",
        "X-Title": "PodhiVisionBot",
        "Content-Type": "application/json"
    }

    for model_name in OPENROUTER_MODELS:
        try:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_msg}
                ]
            }
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            if res.status_code == 200:
                data = res.json()
                text = data['choices'][0]['message']['content']
                if text:
                    return text.strip()
            else:
                print(f"--- DEBUG OpenRouter {model_name} Error ({res.status_code}): {res.text} ---", flush=True)
        except Exception as e:
            print(f"--- DEBUG OpenRouter Exception ({model_name}): {e} ---", flush=True)
            continue
    return None

def generate_ai_response(system_instruction, user_msg, image_bytes=None):
    res = ask_gemini(system_instruction, user_msg, image_bytes)
    if res:
        return res

    if not image_bytes:
        res = ask_openrouter(system_instruction, user_msg)
        if res:
            return res

    return "ขออภัยครับศิษย์พี่ ขณะนี้ระบบ AI ปลายทางกำลังปรับปรุงระบบชั่วคราว โปรดลองถามใหม่อีกครั้งในอีกสักครู่นะครับ"

def send_line_reply(reply_token, user_id, message_obj):
    try:
        line_bot_api.reply_message(reply_token, message_obj)
    except Exception as e:
        print(f"--- DEBUG Reply Error, Fallback to Push: {e} ---", flush=True)
        try:
            line_bot_api.push_message(user_id, message_obj)
        except Exception as e2:
            print(f"--- DEBUG Push Failed: {e2} ---", flush=True)

def async_process_and_reply(reply_token, user_id, user_msg):
    menu_triggers = ["เมนู", "เริ่มต้น", "สวัสดี", "help", "menu"]
    if user_msg.lower() in menu_triggers:
        send_line_reply(reply_token, user_id, create_menu_flex_card())
        return

    trigger_loading(user_id, 30)

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

    if topic:
        if not check_topic_limit(user_id, topic):
            msg = TextSendMessage(
                text="ศิษย์พี่ได้ใช้สิทธิ์ดูดวงหัวข้อนี้ในวันนี้ไปแล้วครับ โปรดเลือกดูหัวข้ออื่น หรือพิมพ์สอบถามเรื่องอื่นๆ ได้เลยครับ", 
                quick_reply=get_quick_reply_menu()
            )
            send_line_reply(reply_token, user_id, msg)
            return

    ai_prompt = user_msg

    if topic == "jataka":
        jataka_num = random.randint(1, 547)
        ai_prompt = (
            f"ช่วยสุ่มและทำนายดวงชะตาจากชาดก 547 ชาติมา 1 เรื่อง (อิงจากชาดกเรื่องที่ {jataka_num}) "
            f"และขอรูปแบบการแสดงผลตามโครงสร้างนี้เป๊ะๆ:\n\n"
            f"[{jataka_num}] ชื่อชาดก\n"
            f"คำจำกัดความ : (ต้องสั้นกระชับมาก ไม่เกิน 3 คำเท่านั้น)\n"
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

    reply_text = generate_ai_response(SYSTEM_INSTRUCTION, ai_prompt)
    msg = TextSendMessage(text=reply_text, quick_reply=get_quick_reply_menu())
    send_line_reply(reply_token, user_id, msg)

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
        "คุณคือผู้เชี่ยวชาญด้านภาษาบาลี หน้าที่ของคุณคือแปลคำศัพท์ภาษาบาลีเป็นภาษาไทย "
        "โดยจัดเรียงคำแปลตามโครงสร้างประโยคภาษาไทยเป็นหลัก คำตอบต้องกระชับ ชัดเจน ตรงประเด็น ความหมายสั้นๆ ไม่ต้องมีคำเกริ่นนำ"
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
        vision_instruction = SYSTEM_INSTRUCTION + "\nเพิ่มเติม: ศิษย์พี่ได้ส่งรูปภาพมา ให้ช่วยวิเคราะห์รายละเอียด วัตถุมงคล หรือสภาวะธรรมในภาพ"
        reply_text = generate_ai_response(vision_instruction, "ช่วยอธิบาย หรือวิเคราะห์สิ่งที่เห็นในภาพนี้ให้ศิษย์พี่หน่อยครับ", image_bytes)
    except Exception:
        reply_text = "เกิดข้อผิดพลาดในการประมวลผลรูปภาพครับศิษย์พี่"
    
    msg = TextSendMessage(text=reply_text, quick_reply=get_quick_reply_menu())
    send_line_reply(reply_token, user_id, msg)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)