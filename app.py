import io
import os
import random
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

# ดึงค่า Keys จากระบบ Render ผ่าน Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

# ตั้งค่า LINE SDK
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# รายชื่อโมเดล OpenRouter (เอา openrouter/auto ขึ้นก่อนเพื่อความเร็วสูงสุด)
FREE_MODELS = [
    "openrouter/auto",
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free"
]

# 🔮 คลังแก่นคำทำนายดวงชะตา
FORTUNE_LIST = [
    "ช่วงนี้มีเกณฑ์ได้รับการสนับสนุนจากผู้ใหญ่ สิ่งที่ลงมือทำด้วยความเพียรจะเริ่มเห็นผลสำเร็จ",
    "ให้ระวังเรื่องการใช้จ่ายและสติในการตัดสินใจ แต่จะมีโชคลาภเล็กๆ น้อยๆ จากการเดินทาง",
    "เป็นช่วงเวลาที่ดีในการเริ่มต้นเรียนรู้สิ่งใหม่ ความคิดสร้างสรรค์แจ่มใส เหมาะแก่การลงมือทำโครงการใหม่"
]

# ☸️ คลังแก่นข้อคิดธรรมะเตือนใจ
DHAMMA_LIST = [
    "สพฺเพ ธมฺมา นาลํ อภินิเวสาย - สิ่งทั้งหลายทั้งปวงไม่ควรยึดมั่นถือมั่น ปล่อยวางได้ ใจก็เป็นสุข",
    "โกรธเขา เหมือนจุดไฟเผาตัวเอง เมื่อมีเรื่องร้อนใจ ให้กลับมาอยู่กับลมหายใจเข้าออก",
    "ความดีทำง่ายเมื่อใจพร้อม เริ่มต้นวันใหม่ด้วยสติ และการมีเมตตาต่อตนเองและผู้อื่น"
]

def ask_gemini(system_instruction, user_msg, image_bytes=None):
    """เรียกใช้ Gemini API เป็นตัวหลัก (รองรับทั้ง ข้อความ และ รูปภาพ)"""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("--- DEBUG: GEMINI_API_KEY is MISSING in Render! ---", flush=True)
        return None

    try:
        genai.configure(api_key=api_key)
        # ปรับรุ่นโมเดลหลักเป็น gemini-3.6-flash ตามที่ Google API แนะนำ
        model = genai.GenerativeModel(
            model_name="gemini-3.6-flash",
            system_instruction=system_instruction
        )
        
        if image_bytes:
            img = Image.open(io.BytesIO(image_bytes))
            response = model.generate_content([user_msg or "ช่วยอธิบายรายละเอียด หรือวิเคราะห์สิ่งที่เห็นในภาพนี้ให้หน่อยครับ", img])
        else:
            response = model.generate_content(user_msg)
            
        if response and response.text:
            print("--- DEBUG: Successfully generated with Gemini API ---", flush=True)
            return response.text.strip()
    except Exception as e:
        print(f"--- DEBUG Gemini Error: {type(e).__name__} -> {e} ---", flush=True)
        
    return None

def ask_openrouter(system_instruction, user_msg):
    """เรียกใช้ OpenRouter เป็นระบบสำรอง (Fallback สำหรับข้อความ)"""
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        print("--- DEBUG: OPENROUTER_API_KEY is MISSING in Render! ---", flush=True)
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
                timeout=5  # กระชับเวลา Timeout ไม่ให้เกินขีดจำกัดของ LINE Webhook
            )
            if response and response.choices and len(response.choices) > 0:
                text = response.choices[0].message.content
                if text:
                    print(f"--- DEBUG: Successfully generated with OpenRouter: {model_name} ---", flush=True)
                    return text.strip()
        except Exception as e:
            print(f"--- DEBUG OpenRouter {model_name} Error: {type(e).__name__} -> {e} ---", flush=True)
            continue

    return None

def generate_ai_response(system_instruction, user_msg, image_bytes=None):
    print("--- DEBUG: Start AI Generation ---", flush=True)
    
    # 1. เรียก Gemini เป็นลำดับแรก
    result = ask_gemini(system_instruction, user_msg, image_bytes)
    if result:
        return result

    # 2. หาก Gemini ไม่ตอบ และไม่มีรูปภาพ ให้สลับมาใช้ OpenRouter สำรองทันที
    if not image_bytes:
        print("--- DEBUG: Gemini failed. Falling back to OpenRouter... ---", flush=True)
        result = ask_openrouter(system_instruction, user_msg)
        if result:
            return result

    return None

def polish_with_ai(topic_type, raw_text):
    system_instruction = (
        f"คุณคือผู้เชี่ยวชาญด้านธรรมะและที่ปรึกษาชีวิต ช่วยนำแก่นเนื้อหา{topic_type}นี้ "
        "ไปเกลาสำนวนให้อ่อนโยน สละสลวย ฟังแล้วไพเราะ และเสริมสร้างกำลังใจ โดยยังคงสาระสำคัญเดิมไว้"
    )
    result = generate_ai_response(system_instruction, f"แก่นเนื้อหา: {raw_text}")
    
    if result:
        return result
    
    prefix = "🔮 คำทำนาย: " if topic_type == "ดวงชะตา" else "☸️ ธรรมะเตือนใจ: "
    return f"{prefix}{raw_text}"

def ask_general_ai(user_msg):
    system_instruction = (
        "คุณคือผู้ช่วย AI ของระบบ 'โพธิ Vision' ตอบคำถามอย่างสุภาพ อ่อนโยน มีเมตตา "
        "กระชับ สละสลวย และให้ข้อคิดหรือคำตอบที่เป็นประโยชน์แก่ผู้ถาม"
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
    
    if any(keyword in user_msg for keyword in ["ดูดวง", "ทำนาย", "ดวง"]):
        raw_fortune = random.choice(FORTUNE_LIST)
        reply_text = polish_with_ai("ดวงชะตา", raw_fortune)
    elif any(keyword in user_msg for keyword in ["ธรรมะ", "เครียด", "ข้อคิด", "ธรรม"]):
        raw_dhamma = random.choice(DHAMMA_LIST)
        reply_text = polish_with_ai("ธรรมะเตือนใจ", raw_dhamma)
    else:
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
            "ตอบอย่างมีเมตตา สุภาพ สละสลวย และให้ข้อคิดธรรมะหรือประโยชน์ที่สอดคล้องกับภาพ"
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