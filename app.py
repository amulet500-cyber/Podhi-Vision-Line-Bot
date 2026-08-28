import io
import os
import random
import threading
import requests
from flask import Flask, request, jsonify, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    ImageMessage, QuickReply, QuickReplyButton, MessageAction,
    FlexSendMessage
)
import google.generativeai as genai
from openai import OpenAI
from PIL import Image

app = Flask(__name__)

# ดึงค่า Keys จาก Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "openrouter/auto"
]

SYSTEM_INSTRUCTION = (
    "คุณคือ 'ศิษย์น้อง' ผู้ช่วย AI และหมอดูพุทธธรรมประจำระบบ 'โพธิ Vision'\n"
    "หน้าที่หลักของคุณคือ:\n"
    "1. ให้คำปรึกษา ทำนายดวงชะตา นำเสนอหลักธรรมะ ชาดก 547 ชาติ และไพ่ทาโรต์ (เหรียญ, ไม้เท้า, ถ้วย, ดาบ) ด้วยความลึกซึ้ง แม่นยำ และมีจิตเมตตา\n"
    "2. สรรพนามที่ใช้: แทนตัวเองว่า 'ศิษย์น้อง' และเรียกผู้ใช้ว่า 'ศิษย์พี่' เสมอ\n"
    "3. ภาษาที่ใช้: กระชับ สละสลวย อ่านง่าย ไม่ใช้สัญลักษณ์หรืออักขระที่แปลกปลอม"
)

def get_quick_reply_menu():
    """สร้าง Quick Reply 5 ปุ่มเมนูหลักในแชทบอทไลน์โดยตรง"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🔮 ดวงวันนี้(ชาดก)", text="ขอคำทำนายดวงวันนี้จากชาดก")),
        QuickReplyButton(action=MessageAction(label="💼 การงาน(ไม้เท้า)", text="ขอคำทำนายการงานจากไพ่ไม้เท้า")),
        QuickReplyButton(action=MessageAction(label="💰 การเงิน(เหรียญ)", text="ขอคำทำนายการเงินจากไพ่เหรียญ")),
        QuickReplyButton(action=MessageAction(label="❤️ ความรัก(ถ้วย)", text="ขอคำทำนายความรักจากไพ่ถ้วย")),
        QuickReplyButton(action=MessageAction(label="⚔️ สุขภาพ/อุปสรรค(ดาบ)", text="ขอคำทำนายสุขภาพและอุปสรรคจากไพ่ดาบ"))
    ])

def create_menu_flex_card():
    """สร้าง Flex Message เมนูหลัก 5 ปุ่ม"""
    flex_contents = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://images.unsplash.com/photo-1507692049790-de58290a4334?w=600",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🔮 โพธิ Vision พุทธธรรมพยากรณ์",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1DB446"
                },
                {
                    "type": "text",
                    "text": "เลือกหัวข้อคำทำนายที่ศิษย์พี่ต้องการได้เลยครับ",
                    "wrap": True,
                    "color": "#666666",
                    "size": "sm",
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#1DB446",
                    "action": {"type": "message", "label": "🔮 ดวงวันนี้ (ชาดก)", "text": "ขอคำทำนายดวงวันนี้จากชาดก"}
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {"type": "message", "label": "💼 การงาน (ไม้เท้า)", "text": "ขอคำทำนายการงานจากไพ่ไม้เท้า"}
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {"type": "message", "label": "💰 การเงิน (เหรียญ)", "text": "ขอคำทำนายการเงินจากไพ่เหรียญ"}
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {"type": "message", "label": "❤️ ความรัก (ถ้วย)", "text": "ขอคำทำนายความรักจากไพ่ถ้วย"}
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {"type": "message", "label": "⚔️ สุขภาพ/อุปสรรค (ดาบ)", "text": "ขอคำทำนายสุขภาพและอุปสรรคจากไพ่ดาบ"}
                }
            ]
        }
    }
    return FlexSendMessage(alt_text="🔮 เมนูพุทธธรรมพยากรณ์ โพธิ Vision", contents=flex_contents)

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
        model = genai.GenerativeModel(model_name="gemini-1.5-flash", system_instruction=system_instruction)
        if image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            prompt = user_msg or "ช่วยวิเคราะห์รูปภาพนี้ในมุมมองธรรมะ..."
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
    
    trigger_keywords = ["เมนู", "คำทำนาย", "เริ่มต้น", "สวัสดี", "ดวง"]
    if user_msg in trigger_keywords or any(k in user_msg for k in ["เมนู", "เริ่มต้น"]):
        flex_card = create_menu_flex_card()
        try:
            line_bot_api.push_message(user_id, flex_card)
            return
        except Exception as e:
            print(f"--- DEBUG Flex Push Error: {e} ---", flush=True)

    dynamic_instruction = SYSTEM_INSTRUCTION
    if "ชาดก" in user_msg or "ดวงวันนี้" in user_msg:
        jataka_num = random.randint(1, 547)
        user_msg = (
            f"ช่วยสุ่มและทำนายดวงชะตาจากชาดก 547 ชาติมา 1 เรื่อง (โดยอิงจากชาดกเรื่องที่ {jataka_num} หรือเรื่องที่เกี่ยวข้อง) "
            f"และขอรูปแบบการแสดงผลตามโครงสร้างมาตรฐานนี้เป๊ะๆ:\n\n"
            f"[{jataka_num}] ชื่อชาดก (ความหมายสั้นๆ)\n"
            f"คำจำกัดความ : \"...\"\n"
            f"บารมีประจำชาติ/วัน : ...บารมี\n"
            f"สภาวะหลัก : (ระบุสถานการณ์หรือปัญหาที่กำลังเผชิญอยู่ในปัจจุบัน)\n"
            f"ธรรมะ ทางแก้ : (เสนอแนวทางธรรมะสั้นๆ กระชับเพื่อแก้ปัญหา)\n\n"
            f"ขอให้ภาษาคมคาย ลึกซึ้ง และตรงประเด็นตามสไตล์พุทธธรรมพยากรณ์ครับศิษย์น้อง"
        )
    elif "ไม้เท้า" in user_msg or "การงาน" in user_msg:
        card_num = random.randint(1, 10)
        user_msg = f"สุ่มไพ่ไม้เท้า 1 ใบจากสำรับ 1-10 (เช่น ไพ่ไม้เท้าใบที่ {card_num}) ทำนายดวงชะตาด้าน 'การงาน' ให้ลึกซึ้ง แม่นยำ อ่านสภาวะการงานและแนวทางแก้ไขในรูปแบบพุทธธรรม"
    elif "เหรียญ" in user_msg or "การเงิน" in user_msg:
        card_num = random.randint(1, 10)
        user_msg = f"สุ่มไพ่เหรียญ 1 ใบจากสำรับ 1-10 (เช่น ไพ่เหรียญใบที่ {card_num}) ทำนายดวงชะตาด้าน 'การเงิน' ให้ลึกซึ้ง แม่นยำ วิเคราะห์กระแสเงินสดและสติในการบริหารเงิน"
    elif "ถ้วย" in user_msg or "ความรัก" in user_msg:
        card_num = random.randint(1, 10)
        user_msg = f"สุ่มไพ่ถ้วย 1 ใบจากสำรับ 1-10 (เช่น ไพ่ถ้วยใบที่ {card_num}) ทำนายดวงชะตาด้าน 'ความรักและความสัมพันธ์' ด้วยความซาบซึ้งและเข้าใจจิตใจมนุษย์"
    elif "ดาบ" in user_msg or "สุขภาพ" in user_msg or "อุปสรรค" in user_msg:
        card_num = random.randint(1, 10)
        user_msg = f"สุ่มไพ่ดาบ 1 ใบจากสำรับ 1-10 (เช่น ไพ่ดาบใบที่ {card_num}) ทำนายเจาะลึกด้าน 'อุปสรรคปัญหา หรือโรคภัยไข้เจ็บทางร่างกาย' พร้อมวิธีตั้งสติรับมือ"

    reply_text = generate_ai_response(dynamic_instruction, user_msg)
    quick_reply = get_quick_reply_menu()
    
    try:
        line_bot_api.push_message(
            user_id, 
            TextSendMessage(text=reply_text, quick_reply=quick_reply)
        )
    except Exception as e:
        print(f"--- DEBUG Push Error: {e} ---", flush=True)

@app.route("/", methods=['GET'])
def health_check():
    return "Podhi Vision Line Bot is running smoothly!", 200

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
    
    quick_reply = get_quick_reply_menu()
    line_bot_api.reply_message(
        event.reply_token, 
        TextSendMessage(text=reply_text, quick_reply=quick_reply)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)