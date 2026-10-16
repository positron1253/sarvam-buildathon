import base64, hashlib, io, json, os, re, time, zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import knowledge as K

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
load_dotenv(HERE.parent / ".env")
KEY = os.environ.get("SARVAM_API_KEY", "")
BASE = "https://api.sarvam.ai"
CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
HDR = {"api-subscription-key": KEY}
LLM_MAX_TOKENS = 3000  # reasoning is disabled per call; headroom stays high in case it still thinks

app = FastAPI(title="Dawai Dekho")

# ---- spend guard: a hard cap on paid Sarvam calls per server run (protects a small credit balance) ----
PAID_PATHS = {"/api/scan": 3.0, "/api/manual": 1.0, "/api/chat": 1.0, "/api/tts": 2.0, "/api/stt": 1.0}
BUDGET_UNITS = float(os.environ.get("BUDGET_UNITS", "400"))  # ~ one scan = 3 units
_spent = {"u": 0.0}


@app.middleware("http")
async def spend_guard(request, call_next):
    cost = PAID_PATHS.get(request.url.path)
    if cost:
        if _spent["u"] + cost > BUDGET_UNITS:
            return JSONResponse({"error": "budget_reached"}, status_code=429)
        _spent["u"] += cost
    return await call_next(request)


@app.get("/api/budget")
def budget():
    return {"used": _spent["u"], "cap": BUDGET_UNITS}


def _cache_get(name):
    p = CACHE / name
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def _cache_put(name, obj):
    (CACHE / name).write_text(json.dumps(obj, ensure_ascii=False), "utf-8")


def llm(messages, max_tokens=LLM_MAX_TOKENS, temperature=0.2):
    r = requests.post(f"{BASE}/v1/chat/completions", headers={**HDR, "Content-Type": "application/json"},
                      json={"model": "sarvam-105b", "messages": messages, "max_tokens": max_tokens,
                            "temperature": temperature, "reasoning_effort": None}, timeout=90)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


# ------------------------------------------------------------------ Vision OCR
def ocr_image(data: bytes, filename: str, mime: str) -> str:
    from sarvamai import SarvamAI
    client = SarvamAI(api_subscription_key=KEY)
    job = client.doc_ai.digitise(file=[(filename, io.BytesIO(data), mime)], language="en-IN", content_type="mixed")
    for _ in range(40):
        st = client.doc_ai.get_status(job_id=job.job_id)
        s = str(st.status).lower()
        if s in ("completed", "partially_completed"):
            break
        if s in ("failed", "rejected"):
            raise RuntimeError("ocr failed")
        time.sleep(2)
    else:
        raise TimeoutError("ocr timeout")
    dl = client.doc_ai.get_download_url(job_id=job.job_id)
    z = requests.get(dl.url, timeout=60)
    z.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".md", ".html", ".json")) and "metadata" not in n and "manifest" not in n]
        names.sort(key=lambda n: (not n.endswith(".md"), n))
        raw = zf.read(names[0]).decode("utf-8", "ignore") if names else ""
    if names and names[0].endswith((".html", ".htm")) or raw.lstrip().startswith("<"):
        import html as _h
        body = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
        raw = _h.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</(?:script|style)>", " ", body.group(1) if body else raw)))
        raw = re.sub(r"[ 	]+", " ", raw)
    return raw.strip()


EXTRACT_PROMPT = """You read OCR text from an Indian medicine strip/box. Return ONLY JSON:
{"name": brand or product name, "salts": [generic active ingredients, lowercase, no strengths],
 "strength": "e.g. 500 mg or empty", "form": "tablet/capsule/syrup/etc or empty",
 "uses": "a short noun phrase for what it is usually used for, e.g. 'fever and mild pain' or 'bacterial infections' (no verbs, not a sentence)",
 "label_directions": "only what the label itself prints about how to take it, else empty",
 "label_warnings": "only warnings printed on the label, else empty",
 "expiry_text": "the expiry text as printed, else empty",
 "confidence": "high|medium|low"}
Never invent information that is not in the text or common general knowledge about the named drug. If the text is unreadable, set confidence low."""


def structure_medicine(ocr_text: str) -> dict:
    out = llm([{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": ocr_text[:4000]}])
    d = extract_json(out)
    d.setdefault("salts", [])
    d["salts"] = [str(s).lower().strip() for s in d["salts"] if s]
    return d


def _translate_one(text: str, lang: str) -> str:
    """Retries on 429/5xx so a busy moment does not silently fall back to English."""
    for attempt in range(4):
        r = requests.post(f"{BASE}/translate", headers={**HDR, "Content-Type": "application/json"},
                          json={"input": text, "source_language_code": "en-IN", "target_language_code": lang,
                                "model": "mayura:v1", "mode": "formal"}, timeout=40)
        if r.ok:
            return r.json().get("translated_text", text)
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("translate failed")


def translate(text: str, lang: str) -> str:
    """English -> lang. Mayura takes 1000 chars/request, so split on sentences. Falls back to English."""
    if lang == "en-IN" or not text:
        return text
    key = "tr_" + hashlib.sha1(f"{lang}|{text}".encode()).hexdigest() + ".json"
    c = _cache_get(key)
    if c:
        return c["t"]
    try:
        out = " ".join(_translate_one(p, lang) for p in _chunks(text, 800))
    except Exception:
        return text
    if out != text:
        _cache_put(key, {"t": out})
    return out


def spoken_script(med: dict, verdict: dict, class_warn: list, lang: str) -> str:
    """4 short lines: what it is, label directions, warnings, what to ask the doctor. English, then translated."""
    name = (med.get("name") or "").strip() or "a medicine"
    strength = (med.get("strength") or "").strip()
    parts = [f"Medicine name: {name}" + (f", {strength}" if strength and (re.sub(r"\D", "", strength) or strength) not in re.sub(r"\s", "", name.lower()) else "") + ".",
             (f"It is generally used for {med['uses'].strip().rstrip('.')}." if (med.get("uses") or "").strip() else "")]
    if med.get("label_directions"):
        parts.append(f"The label says: {med['label_directions'].strip().rstrip('.')}.")
    parts.append(verdict["msg"])
    parts += [w["msg"] for w in class_warn[:1]]
    parts.append("Ask your doctor or pharmacist how to take it. This is not medical advice.")
    return " ".join(p for p in parts if p)


# ------------------------------------------------------------------ routes
@app.post("/api/scan")
async def scan(image: UploadFile = File(...), lang: str = Form("hi-IN")):
    data = await image.read()
    if len(data) > 8_000_000:
        return JSONResponse({"error": "image_too_large"}, status_code=413)
    h = hashlib.sha1(data).hexdigest()
    base = _cache_get(f"scan_{h}.json")
    try:
        if not base:
            ocr = ocr_image(data, image.filename or "scan.jpg", image.content_type or "image/jpeg")
            words = len(re.findall(r"\w+", ocr))
            if words < 3:
                return JSONResponse({"error": "unreadable", "ocr_text": ocr}, status_code=422)
            med = structure_medicine(ocr)
            base = {"ocr_text": ocr, "med": med}
            _cache_put(f"scan_{h}.json", base)
    except (TimeoutError, requests.RequestException) as e:
        return JSONResponse({"error": "scan_failed", "detail": str(e)[:200]}, status_code=502)
    except Exception as e:  # bad/unsupported image or model could not parse it
        return JSONResponse({"error": "unreadable", "detail": str(e)[:200]}, status_code=422)
    ocr, med = base["ocr_text"], base["med"]
    ym = K.parse_expiry(ocr) or K.parse_expiry("Exp " + (med.get("expiry_text") or ""))
    verdict = K.expiry_verdict(ym)
    cw = K.class_warnings_for(med.get("salts", []) + [med.get("name", "")])
    script_en = spoken_script(med, verdict, cw, lang)
    return {
        "med": med, "ocr_text": ocr, "expiry": verdict, "class_warnings": cw,
        "missing": K.missing_details(ocr),
        "script": translate(script_en, lang), "script_en": script_en,
        "cw_local": [translate(w["msg"], lang) for w in cw],
        "expiry_local": translate(verdict["msg"], lang),
        "disclaimer": translate("This is not medical advice. Ask your doctor or pharmacist.", lang),
        "red_flag_card": None,
    }


class ManualIn(BaseModel):
    name: str
    lang: str = "hi-IN"


@app.post("/api/manual")
def manual(body: ManualIn):
    """Fallback when the photo is unreadable: user types or says the medicine name."""
    try:
        med = structure_medicine(f"Product name: {body.name}")
    except Exception:
        med = {"name": body.name, "salts": [], "uses": "", "confidence": "low"}
    # No label was read, so never present directions/warnings: the model could only be guessing.
    for k in ("label_directions", "label_warnings", "expiry_text"):
        med[k] = ""
    cw = K.class_warnings_for(med.get("salts", []) + [body.name])
    verdict = K.expiry_verdict(None)
    script_en = spoken_script(med, verdict, cw, body.lang)
    return {"med": med, "ocr_text": "", "expiry": verdict, "class_warnings": cw, "missing": [],
            "script": translate(script_en, body.lang), "script_en": script_en,
            "cw_local": [translate(w["msg"], body.lang) for w in cw],
            "expiry_local": translate(verdict["msg"], body.lang),
            "disclaimer": translate("This is not medical advice. Ask your doctor or pharmacist.", body.lang)}


class ChatIn(BaseModel):
    messages: list[dict]
    lang: str = "hi-IN"
    medicines: list[dict] = []


CHAT_SYS = """You are Dawai Dekho, a calm, kind health-information helper for people in India. Reply ONLY in {lang_name}, in short simple sentences (max 5), no markdown, no lists.
Rules: Never diagnose. Never give dose amounts or tell anyone to start, stop or change a medicine. For anything beyond general label-style information, say to ask a doctor or pharmacist.
If the user describes an emergency (chest pain, trouble breathing, heavy bleeding, snakebite, poisoning, fainting, seizure, stroke signs, suicidal thoughts), tell them to call 108 or 112 right now.
The user's saved medicines (for context only): {meds}"""


@app.post("/api/chat")
def chat(body: ChatIn):
    last = next((m["content"] for m in reversed(body.messages) if m.get("role") == "user"), "")
    emergency = K.is_red_flag(last)
    if emergency:
        msg = translate("This may be an emergency. Please call 108 or 112 right now. Do not wait.", body.lang)
        return {"reply": msg, "emergency": True}
    meds = "; ".join(f"{m.get('name')} ({', '.join(m.get('salts', []))})" for m in body.medicines[:12]) or "none"
    sys = CHAT_SYS.format(lang_name=K.LANGS.get(body.lang, "Hindi"), meds=meds)
    try:
        reply = llm([{"role": "system", "content": sys}] + body.messages[-8:])
    except Exception:
        reply = ""
    if not reply:
        reply = translate("Sorry, I could not answer now. Please ask your doctor or pharmacist.", body.lang)
    return {"reply": reply, "emergency": False}


class ListIn(BaseModel):
    medicines: list[dict]
    lang: str = "hi-IN"


@app.post("/api/check-list")
def check_list(body: ListIn):
    w = K.check_list(body.medicines)
    for x in w:
        x["local"] = translate(x["msg"], body.lang)
    note = translate("I only check a limited list, so no warning does not mean safe. Ask your doctor or pharmacist.", body.lang)
    return {"warnings": w, "note": note}


class TtsIn(BaseModel):
    text: str
    lang: str = "hi-IN"
    pace: float = 1.0


def _chunks(text, n=450):
    sents = re.split(r"(?<=[.!?।])\s+", text.strip())
    out, cur = [], ""
    for s in sents:
        if len(cur) + len(s) + 1 > n and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out or [text[:n]]


@app.post("/api/tts")
def tts(body: TtsIn):
    text = body.text.strip()[:1800]
    if not text:
        return {"audios": []}
    key = "tts_" + hashlib.sha1(f"{body.lang}|{body.pace}|{text}".encode()).hexdigest() + ".json"
    c = _cache_get(key)
    if c:
        return c
    audios = []
    for part in _chunks(text):
        r = requests.post(f"{BASE}/text-to-speech", headers={**HDR, "Content-Type": "application/json"},
                          json={"text": part, "target_language_code": body.lang, "model": "bulbul:v3",
                                "speaker": "shubh", "pace": body.pace}, timeout=60)
        if not r.ok:
            return JSONResponse({"error": "tts_failed", "detail": r.text[:200]}, status_code=502)
        audios += r.json().get("audios", [])
    out = {"audios": audios}
    _cache_put(key, out)
    return out


@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), lang: str = Form("hi-IN")):
    data = await audio.read()
    if len(data) > 3_000_000:
        return JSONResponse({"error": "audio_too_long"}, status_code=413)
    files = {"file": (audio.filename or "q.webm", data, audio.content_type or "audio/webm")}
    r = requests.post(f"{BASE}/speech-to-text", headers=HDR, files=files,
                      data={"model": "saaras:v3", "mode": "transcribe", "language_code": lang}, timeout=60)
    if not r.ok:
        return JSONResponse({"error": "stt_failed", "detail": r.text[:200]}, status_code=502)
    return {"transcript": r.json().get("transcript", "")}


@app.get("/api/emergency")
def emergency(lang: str = "hi-IN"):
    return {**K.EMERGENCY, "msg": translate("Call 108 or 112 now. Stay with the person. Share your location.", lang)}



UI_STRINGS = {
    "scan": "Scan", "meds": "My medicines", "ask": "Ask", "sos": "SOS",
    "tap_scan": "Take a photo of your medicine", "gallery": "Choose from gallery",
    "type_name": "Or type the medicine name", "find": "Find", "reading": "Reading your medicine...",
    "replay": "Play again", "slow": "Slow", "save": "Save medicine", "saved": "Saved",
    "share": "Share on WhatsApp", "ask_about": "Ask about this", "no_meds": "No medicines saved yet",
    "type_msg": "Type your question", "send": "Send", "hold_talk": "Tap and speak",
    "listening": "Listening...", "chip1": "When to take it?", "chip2": "Side effects?", "chip3": "Can I take it on an empty stomach?",
    "call_now": "Call now", "share_loc": "Share my location", "doctor": "Talk to a doctor online",
    "family": "Call my family", "set_family": "Save a family number", "retry_photo": "Photo is not clear. Please try again in good light.",
    "morning": "Morning", "noon": "Afternoon", "night": "Night", "today": "Today", "taken": "Taken",
    "warnings": "Check these", "expiry": "Expiry", "not_clear": "Some details were not found on the pack. Check with a licensed chemist and ask for a bill.",
    "language": "Language", "emergency": "This may be an emergency", "ocr_text": "Text read from the pack",
    "meds_short": "My meds", "hospital": "Nearest hospital", "pharmacy": "Nearest pharmacy",
    "privacy": "Your saved medicines stay on this phone. Photos are sent securely to Sarvam AI only to read the label.",
    "wipe": "Delete all my data", "share_list": "Share list with my doctor", "exp_past": "Expired", "exp_soon": "Expires soon",
    "remind": "Remind me", "ok_save": "Save", "delete": "Delete", "helpline": "Health helpline", "calm": "Stay calm. Help is on the way if you call.",
}


@app.get("/api/ui")
def ui(lang: str = "hi-IN"):
    from concurrent.futures import ThreadPoolExecutor
    if lang == "en-IN" or lang not in K.LANGS:
        return UI_STRINGS
    KEEP = {"sos"}  # never translate (mayura turns "SOS" into an unrelated word)

    def one(kv):
        k, v = kv
        if k in KEEP:
            return v
        out = translate(v, lang).strip()
        if not v.rstrip().endswith((".", "?")):  # short labels: drop the full stop mayura adds
            out = out.rstrip(".।॥ ")
        return out

    with ThreadPoolExecutor(3) as ex:
        vals = list(ex.map(one, UI_STRINGS.items()))
    return dict(zip(UI_STRINGS.keys(), vals))


@app.get("/api/langs")
def langs():
    return K.LANGS


@app.get("/sw.js")
def sw():
    return FileResponse(HERE / "static" / "sw.js", media_type="application/javascript")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
