import io
import os
import random
import threading
import requests
from flask import Flask, request, render_template, jsonify, abort
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

# ดึงค่า Keys จาก Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LIFF_ID = os.getenv('LIFF_ID', '') # ใส่ LIFF ID ที่ได้จาก LINE Developers Console

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

FREE_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "openrouter/auto"
]

SYSTEM_INSTRUCTION = (
    "คุณคือ 'ศิษย์น้อง' ผู้ช่วย AI และหมอดูพุทธธรรมประจำระบบ 'โพธิ Vision'\n"
    "หน้าที่หลักของคุณคือ:\n"
    "1. ให้คำปรึกษา ดำเนินการทำนายดวงชะตา นำเสนอหลักธรรมะ ชาดก และการเจริญบารมี 10 ประการ\n"
    "2. สนทนาทั่วไป ให้ความรู้ ตอบคำถามด้วยจิตเมตตา นอบน้อม อ่อนโยน และทรงปัญญา\n"
    "3. สรรพนามที่ใช้: แทนตัวเองว่า 'ศิษย์น้อง' และเรียกผู้ใช้ว่า 'ศิษย์พี่' เสมอ\n"
    "4. ภาษาที่ใช้: กระชับ สละสลวย อ่านง่าย ไม่ใช้สัญลักษณ์หรืออักขระที่แปลกปลอม"
)

# 📜 คลังข้อมูลชาดกตัวอย่าง (สามารถขยายเพิ่มให้ครบ 547 ชาติได้)
JATAKA_DATABASE = [
    {
        "id": 1,
        "name": "เอกปัณณชาดก",
        "barami": "ทมะ / ขันติบารมี",
        "keyword": "ดัดนิสัย ถอดอคติ",
        "image_url": "https://images.unsplash.com/photo-1507692049790-de58290a4334?w=600",
        "predictions": {
            "work": {"predict": "บรรยากาศอึดอัด บริวารเริ่มถอยห่างจากความถือดี", "solution": "เปิดใจรับฟังคำทักท้วง ลดความดื้อรั้น อดทนต่อคำวิจารณ์"},
            "money": {"predict": "รายจ่ายจุกจิกจากความเอาแต่ใจหรือของไม่จำเป็น", "solution": "ยับยั้งชั่งใจ ตัดสิ่งเพลิดเพลินชั่วคราวออกไป"},
            "love": {"predict": "มีความขัดแย้งเรื่องอารมณ์และคำพูดที่ไม่ยอมกัน", "solution": "ใช้น้ำเย็นเข้าลูบ ถอยคนละก้าวด้วยขันติธรรม"},
            "health": {"predict": "ความเครียดสะสม ธาตุไฟกำเริบ ปวดหัว นอนไม่หลับ", "solution": "สวดมนต์ นั่งสมาธิ ปรับลมหายใจให้ผ่อนคลาย"}
        }
    },
    {
        "id": 539,
        "name": "มหาชนกชาดก",
        "barami": "วิริยบารมี",
        "keyword": "ความเพียรไม่ท้อถอย",
        "image_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600",
        "predictions": {
            "work": {"predict": "ภาระงานหนักหน่วง เสมือนว่ายน้ำอยู่กลางมหาสมุทร", "solution": "อย่าเพิ่งท้อถอย พยายามต่อไป ผลสำเร็จรออยู่ที่ฝั่ง"},
            "money": {"predict": "หมุนเงินเหน็ดเหนื่อย แต่ยังมีช่องทางให้รอดพ้นได้", "solution": "ขยันหา วางแผนประหยัด ไม่สร้างหนี้สินเพิ่ม"},
            "love": {"predict": "ต้องประคบประหงมสัมพันธ์ด้วยความอดทนและจริงใจ", "solution": "แสดงความจริงใจให้เห็นผ่านการกระทำมากกว่าคำพูด"},
            "health": {"predict": "เมื่อยล้ากล้ามเนื้อ ร่างกายอ่อนเพลียจากการทำงานหนัก", "solution": "พักผ่อนให้พอ และทานอาหารบำรุงธาตุ"}
        }
    }
]

def start_loading_animation(user_id):
    try:
        url = "https://api.line.me/v2/bot/chat/loading/start"
        headers = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {"chatId": user_id, "loadingSeconds": 60}
        requests.post(url, headers=headers, json=data, timeout=5)
    except Exception as e:
        print(f"--- DEBUG Loading Error: {e} ---", flush=True)

def ask_gemini(system_instruction, user_msg, image_bytes=None):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key: return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-2.0-flash", system_instruction=system_instruction)
        if image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            prompt = user_msg or "ช่วยวิเคราะห์รูปภาพนี้ในมุมมองธรรมะ หรือการทำนายสภาวะให้ศิษย์พี่หน่อยครับ"
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content(user_msg)
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
                timeout=10
            )
            if response and response.choices:
                text = response.choices[0].message.content
                if text: return text.strip()
        except Exception:
            continue
    return None

def generate_ai_response(system_instruction, user_msg, image_bytes=None):
    res = ask_gemini(system_instruction, user_msg, image_bytes)
    if res: return res
    if not image_bytes:
        res = ask_openrouter(system_instruction, user_msg)
        if res: return res
    return "ขออภัยครับศิษย์พี่ ขณะนี้ศิษย์น้องไม่สามารถประมวลผลได้ชั่วคราว โปรดลองใหม่อีกครั้งนะครับ"

def async_process_and_push(user_id, user_msg):
    start_loading_animation(user_id)
    reply_text = generate_ai_response(SYSTEM_INSTRUCTION, user_msg)
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text=reply_text))
    except Exception as e:
        print(f"--- DEBUG Push Error: {e} ---", flush=True)

# 🌐 LIFF Web Routes & API
@app.route("/liff", methods=['GET'])
def liff_page():
    """แสดงหน้าเว็บ LIFF MiniApp"""
    return render_template("index.html", liff_id=LIFF_ID)

@app.route("/api/draw", methods=['GET'])
def api_draw():
    """API สุ่มเลือกชาดกประจำวัน"""
    selected = random.choice(JATAKA_DATABASE)
    return jsonify({"success": True, "data": selected})

# 📩 LINE Webhook Routes
@app.route("/", methods=['GET'])
def health_check():
    return "Podhi Vision Line Bot & LIFF App is running smoothly!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id
    start_loading_animation(user_id)
    threading.Thread(target=async_process_and_push, args=(user_id, user_msg)).start()

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    start_loading_animation(user_id)
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = message_content.content
        vision_instruction = SYSTEM_INSTRUCTION + "\nเพิ่มเติม: ศิษย์พี่ได้ส่งรูปภาพมา ให้ช่วยวิเคราะห์รายละเอียด วัตถุมงคล หรือสภาวะธรรมในภาพด้วยความนอบน้อม"
        reply_text = generate_ai_response(vision_instruction, "ช่วยอธิบาย หรือวิเคราะห์สิ่งที่เห็นในภาพนี้ให้ศิษย์พี่หน่อยครับ", image_bytes)
    except Exception as e:
        reply_text = "เกิดข้อผิดพลาดในการประมวลผลรูปภาพครับศิษย์พี่"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)