import os
import random
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from openai import OpenAI

app = Flask(__name__)

# ดึงค่า Keys จากระบบ Render ผ่าน Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

# ตั้งค่า LINE SDK
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# รายชื่อโมเดลฟรี OpenRouter ชุดปัจจุบันที่ใช้งานได้จริง
FREE_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-small-24b-instruct-2501:free"
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

def ask_gemini(system_instruction, user_msg):
    """เรียกใช้ Gemini API เป็นตัวหลัก"""
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("--- DEBUG: GEMINI_API_KEY is MISSING in Render! ---", flush=True)
        return None

    try:
        genai.configure(api_key=api_key)
        # ปรับเป็น gemini-2.0-flash ซึ่งเป็นรุ่นเสถียรปัจจุบัน
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=system_instruction
        )
        response = model.generate_content(user_msg)
        if response and response.text:
            print("--- DEBUG: Successfully generated with Gemini API ---", flush=True)
            return response.text.strip()
    except Exception as e:
        print(f"--- DEBUG Gemini Error: {type(e).__name__} -> {e} ---", flush=True)
        
    return None

def ask_openrouter(system_instruction, user_msg):
    """เรียกใช้ OpenRouter เป็นระบบสำรอง (Fallback)"""
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
                timeout=15
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

def generate_ai_response(system_instruction, user_msg):
    print("--- DEBUG: Start AI Generation ---", flush=True)
    
    # 1. เรียก Gemini เป็นลำดับแรก
    result = ask_gemini(system_instruction, user_msg)
    if result:
        return result

    # 2. หาก Gemini ไม่ตอบ ให้สลับมาใช้ OpenRouter
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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)