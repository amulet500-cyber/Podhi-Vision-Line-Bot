import os
import random
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from openai import OpenAI

app = Flask(__name__)

# ดึงค่า Keys จากระบบ Render ผ่าน Environment Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

# ตั้งค่า LINE SDK
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ตั้งค่า OpenRouter Client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "https://podhi-vision-line-bot-1.onrender.com",
        "X-Title": "Podhi Vision Bot",
    }
)

# รายชื่อโมเดลฟรีใน OpenRouter (ลำดับการทำงาน: ตัวหลัก -> สำรอง 1 -> สำรอง 2)
FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "google/gemma-2-9b-it:free",
    "qwen/qwen-2.5-72b-instruct:free"
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

def generate_ai_response(system_prompt, user_prompt):
    """เรียกใช้ AI โดยลองทีละโมเดล หากโมเดลแรกติดคิวเต็ม จะข้ามไปโมเดลสำรองทันที"""
    for model_name in FREE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                timeout=10
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"--- Model {model_name} failed: {e} ---")
            continue
            
    return None

def polish_with_hermes(topic_type, raw_text):
    """ส่งข้อความให้ AI เกลาสำนวนให้อ่อนโยน สละสลวย"""
    system_instruction = (
        f"คุณคือผู้เชี่ยวชาญด้านธรรมะและที่ปรึกษาชีวิต ช่วยนำแก่นเนื้อหา{topic_type}นี้ "
        "ไปเกลาสำนวนให้อ่อนโยน สละสลวย ฟังแล้วไพเราะ และเสริมสร้างกำลังใจ โดยยังคงสาระสำคัญเดิมไว้"
    )
    result = generate_ai_response(system_instruction, f"แก่นเนื้อหา: {raw_text}")
    
    if result:
        return result
    
    prefix = "🔮 คำทำนาย: " if topic_type == "ดวงชะตา" else "☸️ ธรรมะเตือนใจ: "
    return f"{prefix}{raw_text}"

def ask_hermes_general(user_msg):
    """ส่งคำถามทั่วไปให้ AI ตอบกลับแบบอิสระ"""
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
    return "Podhi Vision Bot with AI is running 24/7!", 200

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
        reply_text = polish_with_hermes("ดวงชะตา", raw_fortune)
    elif any(keyword in user_msg for keyword in ["ธรรมะ", "เครียด", "ข้อคิด", "ธรรม"]):
        raw_dhamma = random.choice(DHAMMA_LIST)
        reply_text = polish_with_hermes("ธรรมะเตือนใจ", raw_dhamma)
    else:
        # คำถามทั่วไป ส่งให้ AI ประมวลผล
        reply_text = ask_hermes_general(user_msg)
        
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)