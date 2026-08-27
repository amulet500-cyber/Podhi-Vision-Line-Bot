import io
import os
import re
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

# 🌐 รายชื่อเว็บไซต์เป้าหมาย (Whitelist) ตามที่ศิษย์พี่ระบุ
TARGET_DOMAINS = [
    "inno-home.com", "ennxo.com", "interhome.co.th", "ddproperty.com", 
    "taladteedin.com", "kasikornbank.com", "propertyhub.in.th", "baania.com", 
    "tperty.com", "pantipmarket.com", "tb.co.th", "teedin108.com", 
    "baanteedin108.com", "thaihometown.com", "kaidee.com",
    "uamulet.com", "g-pra.com", "thaprachan.com", "pralanna.com", "web-pra.com"
]

def start_loading_animation(user_id):
    """เรียกใช้ LINE API เปิดหลอดหมวดจุดไข่ปลา (Loading Animation) สูงสุด 60 วินาที"""
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
    """ทำการค้นหาลิงก์สด เน้นสกัดจากรายชื่อเว็บไซต์ที่ศิษย์พี่กำหนด"""
    results = []
    
    # สตรีม HTTP Header ป้องกันการโดนบล็อก
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'th-TH,th;q=0.9,en;q=0.8'
    }

    try:
        # ใช้ DuckDuckGo ค้นหาโดยพ่วง site: เจาะจงโดเมน Whitelist
        from duckduckgo_search import DDGS
        
        # ค้นหารอบที่ 1: เจาะจงเว็บเป้าหมายไทย
        search_query = f"{query.strip()} (site:ddproperty.com OR site:kaidee.com OR site:ennxo.com OR site:thaprachan.com OR site:uamulet.com OR site:g-pra.com OR site:web-pra.com OR site:taladteedin.com)"
        
        with DDGS() as ddgs:
            search_gen = ddgs.text(search_query, region='th-th', safesearch='off', max_results=max_results)
            if search_gen:
                for r in search_gen:
                    url = r.get("href", "")
                    title = r.get("title", "")
                    snippet = r.get("body", "")
                    if url:
                        results.append({"title": title, "url": url, "snippet": snippet})
                        
    except Exception as e:
        print(f"--- DEBUG DDGS Search Error: {e} ---", flush=True)

    # หากรอบแรกไม่ได้ผลลัพธ์ ให้ค้นหา Google HTML Direct (วิธีสำรองที่แม่นยำที่สุด)
    if not results:
        try:
            google_url = f"https://www.google.co.th/search?q={requests.utils.quote(query.strip())}&hl=th&cr=countryTH"
            resp = requests.get(google_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                # ดึง URL จาก HTML หน้า Google
                urls = re.findall(r'/url\?q=(https?://[^&]+)', resp.text)
                for u in urls:
                    if not any(block in u for block in ['google.com', 'youtube.com', 'support.google']):
                        # ตรวจว่าเป็นเว็บตรงกับ Whitelist หรือไม่
                        domain_match = any(domain in u for domain in TARGET_DOMAINS)
                        title = u.split('/')[2] if domain_match else u
                        results.append({"title": f"ประกาศจาก {title}", "url": u, "snippet": ""})
                        if len(results) >= 5:
                            break
        except Exception as ex:
            print(f"--- DEBUG Direct Google Fallback Error: {ex} ---", flush=True)

    return results

def ask_gemini(system_instruction, user_msg, image_bytes=None):
    """เรียกใช้ Gemini API เป็นตัวหลัก"""
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

def format_links_with_ai(query, raw_results):
    """จัดรูปแบบรายการ 'ชื่อประกาศ + ลิงก์'"""
    if not raw_results:
        return f"ขออภัยครับ ศิษย์น้องไม่พบลิงก์ประกาศที่ตรงเงื่อนไขเกี่ยวกับ '{query}' ในขณะนี้"

    lines = [f"🔎 รวมลิงก์ประกาศที่เกี่ยวข้องครับ:\n"]
    for i, r in enumerate(raw_results[:5], 1):
        lines.append(f"{i}. {r['title']}\n👉 {r['url']}")
    return "\n\n".join(lines)

def async_search_and_push(user_id, query):
    """กระบวนการค้นหาหลังบ้าน (Async Thread)"""
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
        # 1. ตอบรับทันทีเพื่อเคลียร์ Timeout 5 วินาทีของ LINE
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ศิษย์น้องรับเรื่อง '{user_msg}' แล้วครับ กำลังออกไปค้นหาลิงก์ให้อยู่ รอสักครู่นะครับ...")
        )
        
        # 2. แยก Thread สแกนค้นสดหลังบ้าน
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