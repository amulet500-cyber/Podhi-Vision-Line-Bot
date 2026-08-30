let dictionary = {};
let currentThaiContent = "";
let lastRequestedWord = ""; 

const view_mode_init = "1234567890";
const cache_data_id = "1234567890";
const theme_color_code = "123456789012";
const app_config_key = view_mode_init + cache_data_id + theme_color_code;

const AI_TRANSLATE_URL = "https://podhi-vision-line-bot-1.onrender.com/api/translate-word";

// โหลดพจนานุกรม
async function loadDictionary() {
    try {
        const response = await fetch('sys.obj');
        if (!response.ok) throw new Error("ไม่พบไฟล์ sys.obj");
        const arrayBuffer = await response.arrayBuffer();
        const decryptedText = await decryptWithAES(arrayBuffer, app_config_key);
        
        decryptedText.split('\n').forEach(line => {
            const parts = line.split(' – ');
            if (parts.length >= 2) {
                dictionary[parts[0].trim()] = parts.slice(1).join(' – ').trim();
            }
        });

        const localSaved = localStorage.getItem('ai_added_words');
        if (localSaved) {
            const extraDict = JSON.parse(localSaved);
            Object.assign(dictionary, extraDict);
        }
    } catch (e) { console.error("โหลดพจนานุกรมล้มเหลว:", e); }
}

async function decryptWithAES(buffer, keyString) {
    const iv = buffer.slice(0, 16);
    const encryptedData = buffer.slice(16);
    const key = await crypto.subtle.importKey(
        "raw", new TextEncoder().encode(keyString),
        { name: "AES-CBC" }, false, ["decrypt"]
    );
    const decrypted = await crypto.subtle.decrypt(
        { name: "AES-CBC", iv: iv }, key, encryptedData
    );
    return new TextDecoder().decode(decrypted);
}

async function encryptWithAES(text, keyString) {
    const encoder = new TextEncoder();
    const data = encoder.encode(text);
    const iv = crypto.getRandomValues(new Uint8Array(16));
    const key = await crypto.subtle.importKey(
        "raw", encoder.encode(keyString),
        { name: "AES-CBC" }, false, ["encrypt"]
    );
    const encrypted = await crypto.subtle.encrypt(
        { name: "AES-CBC", iv: iv }, key, data
    );
    
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv, 0);
    combined.set(new Uint8Array(encrypted), iv.length);
    return combined.buffer;
}

async function exportNewSysObj() {
    let textLines = [];
    for (const [word, trans] of Object.entries(dictionary)) {
        textLines.push(`${word} – ${trans}`);
    }
    const fullText = textLines.join('\n');
    const encryptedBuffer = await encryptWithAES(fullText, app_config_key);
    
    const blob = new Blob([encryptedBuffer], { type: "application/octet-stream" });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'sys.obj';
    link.click();
}

// ฟังก์ชันแสดงและจัดการตำแหน่งป๊อปอัป (แยกโหมดลอยชิดซ้ายคำศัพท์ กับ โหมดตรึงขอบล่าง)
function updatePopup(text, targetElement = null, isBottomMode = false) {
    const popup = document.getElementById('popup');
    if (!popup) return;

    if (!text || text.trim() === "") {
        popup.classList.remove('active', 'bottom-mode');
        return;
    }

    popup.innerText = text;

    // 1. โหมดแปลเนื้อหาตัวเลข [๑] : ตรึงขอบล่างจอ (แบบเดิม)
    if (isBottomMode) {
        popup.classList.add('bottom-mode', 'active');
        popup.style.top = '';
        popup.style.left = '';
        popup.style.transform = '';
        return;
    }

    // 2. โหมดแปลคำศัพท์ : Label ลอยชิดซ้ายคำศัพท์ + กันตกขอบจอ
    popup.classList.remove('bottom-mode');
    popup.classList.add('active');

    if (targetElement) {
        const rect = targetElement.getBoundingClientRect();
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

        // วางแนวตั้ง (บน หรือ ล่าง)
        let topPos = rect.top + scrollTop - 8;
        if (rect.top < 60) {
            topPos = rect.bottom + scrollTop + 8;
            popup.style.transform = 'translate(0, 0)';
        } else {
            popup.style.transform = 'translate(0, -100%)';
        }

        // วางแนวนอน ชิดซ้ายของคำศัพท์
        let leftPos = rect.left + scrollLeft;
        popup.style.top = topPos + 'px';
        popup.style.left = leftPos + 'px';

        // คำนวณป้องกันไม่ให้ Label หลุดออกนอกขอบจอขวาหรือซ้าย
        requestAnimationFrame(() => {
            const popupWidth = popup.offsetWidth || 200;
            const windowWidth = window.innerWidth;

            if (leftPos + popupWidth > windowWidth - 15) {
                leftPos = windowWidth - popupWidth - 15; // ดันกลับเข้ามาเมื่อยาวล้นขวา
            }
            if (leftPos < 10) leftPos = 10; // ดันกลับเมื่อชิดซ้ายเกินไป

            popup.style.left = leftPos + 'px';
        });
    }
}

// ฟังก์ชันแปลเนื้อหาตามเลขข้อ [๑]
function showTranslation(topicNumber, targetElement) {
    if (!currentThaiContent) {
        updatePopup("กรุณาโหลดเล่มก่อนครับ", targetElement, true);
        return;
    }
    let cleanText = currentThaiContent.replace(/\r\n|\r|\n/g, " ");
    const escapedTopic = topicNumber.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`${escapedTopic}(.*?)(?=\\s\\[[๑-๙๐-๙]+\\]|$)`, 'm');
    const match = regex.exec(cleanText);
    
    // ส่ง isBottomMode = true สำหรับตัวเลข [๑]
    updatePopup(match ? `แปล ${topicNumber}: ${match[1].trim()}` : `ไม่พบข้อมูล ${topicNumber}`, targetElement, true);
}

const selector = document.getElementById('book-selector');
const bookNames = [
    "01 วินย.มหาวิภงฺโค ๑", "02 วินย.มหาวิภงฺโค ๒", "03 วินย.ภิกฺขุนีวิภงฺโค", "04 วินย.มหาวคฺโค ๑", "05 วินย.มหาวคฺโค ๒",
    "06 วินย.จุลฺลวคฺโค ๑", "07 วินย.จุลฺลวคฺโค ๒", "08 วินย.ปริวาโร", "09 สุตฺต ที.สีลกฺขนฺธ", "10 สุตฺต ที.มหาวคฺโค",
    "11 สุตฺต ที.ปาฏิกฺวคฺโค", "12 สุตฺต ม.มูลปณฺณาสกํ", "13 สุตฺต ม.มชฺฌิมปณฺณาสกํ", "14 สุตฺต ม.อุปริปณฺณาสกํ",
    "15 สุตฺต สํ.สคาถวคฺโค", "16 สุตฺต สํ.นิทานวคฺโค", "17 สุตฺต สํ.ขนฺธวารวคฺโค", "18 สุตฺต สํ.สฬายตวคฺโค",
    "19 สุตฺต สํ.มหาวารวคฺโค", "20 สุตฺต องฺ เอก-ทุก-ติก", "21 สุตฺต องฺ จตุกฺก", "22 สุตฺต องฺ ปัญจก-ฉักก",
    "23 สุตฺต องฺ สัตตก-อัฏฐก-นวก", "24 สุตฺต องฺ ทสก-เอกาทสก", "25 สุตฺต ขุ. ขุททกปาฐ-ธรรมบท-อุทาน",
    "26 สุตฺต ขุ. วิมาน-เปต", "27 สุตฺต ขุ. ชาดก ๑", "28 สุตฺต ขุ. ชาดก ๒", "29 สุตฺต ขุ. มหานิทเทส",
    "30 สุตฺต ขุ. จูฬนิทเทส", "31 สุตฺต ขุ. ปฏิสัมภิทามรรค", "32 สุตฺต ขุ. อปทาน ๑", "33 สุตฺต ขุ. อปทาน พุทธวงศ์ ๒",
    "34 อภิ. ธรรมสังคณี", "35 อภิ. วิภังค์", "36 อภิ. ธาตุกถา-ปุคคลปัญญัติ", "37 อภิ. กถาวัตถุ",
    "38 อภิ. ยมก ๑", "39 อภิ. ยมก ๒", "40 อภิ. ปัฏฐาน ๑", "41 อภิ. ปัฏฐาน ๒", "42 อภิ. ปัฏฐาน ๓",
    "43 อภิ. ปัฏฐาน ๔", "44 อภิ. ปัฏฐาน ๕", "45 อภิ. ปัฏฐาน ๖"
];

if (selector) {
    bookNames.forEach((name, i) => {
        let opt = document.createElement('option');
        opt.value = i + 1; 
        opt.textContent = name;
        selector.appendChild(opt);
    });

    selector.addEventListener('change', async (e) => {
        const bookNum = e.target.value;
        const contentDiv = document.getElementById('pali-content');
        if (!contentDiv) return;

        contentDiv.innerText = "กำลังโหลด...";
        currentThaiContent = "";
        updatePopup(""); 
        try {
            const [paliRes, thaiRes] = await Promise.all([fetch(`b${bookNum}.txt`), fetch(`t${bookNum}.txt`)]);
            let paliText = await paliRes.text();
            paliText = paliText.replace(/^(\[[๑-๙๐-๙]+\])/gm, '<span class="pali-number" style="pointer-events: none;">$1</span>');
            contentDiv.innerHTML = paliText;
            currentThaiContent = await thaiRes.text();
        } catch (err) { contentDiv.innerText = "ไม่พบไฟล์เล่มที่ " + bookNum; }
    });
}

function getRangeFromPoint(x, y) {
    if (document.caretRangeFromPoint) {
        return document.caretRangeFromPoint(x, y);
    } else if (document.caretPositionFromPoint) {
        const pos = document.caretPositionFromPoint(x, y);
        if (pos) {
            const range = document.createRange();
            range.setStart(pos.offsetNode, pos.offset);
            range.collapse(true);
            return range;
        }
    }
    return null;
}

const paliContentDiv = document.getElementById('pali-content');
if (paliContentDiv) {
    paliContentDiv.addEventListener('click', (e) => {
        const currentHighlights = document.querySelectorAll('.highlight-pali');
        currentHighlights.forEach(el => {
            const parent = el.parentNode;
            if (parent) {
                parent.replaceChild(document.createTextNode(el.textContent), el);
                parent.normalize();
            }
        });

        const r = getRangeFromPoint(e.clientX, e.clientY);
        if (r) {
            let n = r.startContainer, o = r.startOffset, t = n.textContent;
            if (!t || n.nodeType !== Node.TEXT_NODE) return;

            let start = o, end = o;
            while (start > 0 && t[start - 1] !== ' ' && t[start - 1] !== '\n' && t[start - 1] !== '\t') start--;
            while (end < t.length && t[end] !== ' ' && t[end] !== '\n' && t[end] !== '\t') end++;
            
            let rawWord = t.substring(start, end).trim();
            if (!rawWord) { updatePopup(""); return; }

            const span = document.createElement('span');
            span.className = 'highlight-pali';
            span.textContent = rawWord;

            const range = document.createRange();
            range.setStart(n, start);
            range.setEnd(n, end);
            range.deleteContents();
            range.insertNode(span);

            // หากคลิกที่ตัวเลข [๑] ให้แสดงโหมดขอบล่าง
            if (/^\[[๑-๙๐-๙]+\]$/.test(rawWord)) {
                showTranslation(rawWord, span);
                return;
            }

            // แปลคำศัพท์ทั่วไป ใช้โหมด Label ลอยชิดซ้ายคำ
            const cleanWord = rawWord.replace(/[.,;:\s"”’]/g, "").trim();
            lastRequestedWord = cleanWord;

            if (dictionary[cleanWord]) {
                updatePopup(`${cleanWord} – ${dictionary[cleanWord]}`, span);
                return;
            } else if (dictionary[rawWord]) {
                updatePopup(`${rawWord} – ${dictionary[rawWord]}`, span);
                return;
            }

            let baseWord = cleanWord;
            if (cleanWord.endsWith('ติ')) {
                baseWord = cleanWord.slice(0, -2);
            } else if (cleanWord.endsWith('นฺติ')) {
                baseWord = cleanWord.slice(0, -4);
            }

            if (baseWord !== cleanWord && dictionary[baseWord]) {
                updatePopup(`${cleanWord} [${baseWord} + อิติ] – ${dictionary[baseWord]}`, span);
                return;
            }

            updatePopup(`${cleanWord} – (กำลังให้ AI ช่วยแปล...)`, span);
            
            fetch(AI_TRANSLATE_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word: cleanWord })
            })
            .then(response => {
                if (!response.ok) throw new Error("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้");
                return response.json();
            })
            .then(data => {
                if (lastRequestedWord === cleanWord) {
                    if (data && data.translation) {
                        const cleanTranslation = data.translation.replace(/^.*?\s–\s/, '').trim();
                        
                        dictionary[cleanWord] = cleanTranslation;

                        let localSaved = JSON.parse(localStorage.getItem('ai_added_words') || '{}');
                        localSaved[cleanWord] = cleanTranslation;
                        localStorage.setItem('ai_added_words', JSON.stringify(localSaved));

                        updatePopup(`${cleanWord} – ${cleanTranslation}`, span);
                    } else {
                        updatePopup(`${cleanWord} – ไม่พบคำแปล`, span);
                    }
                }
            })
            .catch(err => {
                console.error("AI Translation Error:", err);
                if (lastRequestedWord === cleanWord) {
                    updatePopup(`${cleanWord} – ไม่พบคำแปลในระบบ`, span);
                }
            });
        }
    });
}

loadDictionary();
const modal = document.getElementById("about-modal");
const btn = document.getElementById("about-btn");
const closeBtn = document.querySelector(".close-btn");

if (btn) btn.onclick = () => { modal.style.display = "block"; }
if (closeBtn) closeBtn.onclick = () => { modal.style.display = "none"; }
window.onclick = (event) => { if (event.target == modal) modal.style.display = "none"; }