"""Deterministic safety layer. The LLM never decides these: rules always win."""
import re
from datetime import date

LANGS = {
    "hi-IN": "Hindi", "en-IN": "English", "bn-IN": "Bengali", "ta-IN": "Tamil",
    "te-IN": "Telugu", "kn-IN": "Kannada", "ml-IN": "Malayalam", "mr-IN": "Marathi",
    "gu-IN": "Gujarati", "pa-IN": "Punjabi", "od-IN": "Odia",
}

# ---- Emergency red flags (checked BEFORE any LLM answer; over-trigger on purpose) ----
RED_FLAGS = [
    r"chest\s*pain", r"heart\s*attack", r"can'?t\s*breathe|cannot\s*breathe|short(ness)?\s*of\s*breath|breathless",
    r"faint(ed|ing)?|unconscious|passed\s*out", r"stroke|face\s*droop|slurred", r"seizure|fits\b|convulsion",
    r"heavy\s*bleeding|bleeding\s*(a lot|heavily)|vomit(ing)?\s*blood", r"snake\s*bite|snakebite|bitten\s*by",
    r"poison|overdose|took\s*too\s*many|swallowed\s*(too many|a lot)", r"suicid|kill\s*myself|end\s*my\s*life",
    r"not\s*feeding|baby\s*(not|won'?t)", r"severe\s*allerg|swollen\s*(face|tongue|lips)|anaphyla",
    # Hindi / Hinglish
    r"सीने\s*में\s*दर्द|सांस\s*(नहीं|फूल)|बेहोश|दौरा|साँप|सांप|ज़हर|जहर|खून\s*(बह|आ)|आत्महत्या|ज्यादा\s*गोली|ज़्यादा\s*गोली",
    r"seene\s*me\s*dard|saans\s*nahi|behosh|saanp|zeher|jahar|khoon\s*beh",
    # Tamil, Telugu, Bengali, Kannada, Malayalam, Marathi, Gujarati, Punjabi, Odia
    r"நெஞ்சு\s*வலி|மூச்சு|பாம்பு|விஷம்|மயக்க", r"ఛాతీ\s*నొప్పి|ఊపిరి|పాము|విషం|స్పృహ",
    r"বুকে\s*ব্যথা|শ্বাস|সাপ|বিষ|অজ্ঞান", r"ಎದೆ\s*ನೋವು|ಉಸಿರ|ಹಾವು|ವಿಷ|ಪ್ರಜ್ಞೆ",
    r"നെഞ്ചുവേദന|ശ്വാസ|പാമ്പ്|വിഷം|ബോധം", r"छातीत\s*दुखत|श्वास|साप|विष|बेशुद्ध",
    r"છાતીમાં\s*દુખાવો|શ્વાસ|સાપ|ઝેર|બેભાન", r"ਛਾਤੀ\s*(ਵਿੱਚ)?\s*ਦਰਦ|ਸਾਹ|ਸੱਪ|ਜ਼ਹਿਰ|ਬੇਹੋਸ਼",
    r"ଛାତି\s*ଯନ୍ତ୍ରଣା|ନିଶ୍ୱାସ|ସାପ|ବିଷ|ଅଜ୍ଞାନ",
]
_RED = re.compile("|".join(RED_FLAGS), re.I)


def is_red_flag(text: str) -> bool:
    return bool(text and _RED.search(text))


EMERGENCY = {
    "numbers": [
        {"label": "Emergency (all India)", "tel": "112"},
        {"label": "Ambulance", "tel": "108"},
        {"label": "Mother & child ambulance", "tel": "102"},
        {"label": "Tele-MANAS (mental health)", "tel": "14416"},
    ],
    "doctor": {
        "esanjeevani": "https://esanjeevani.mohfw.gov.in/",
        "helpline_104": "104",
    },
}

# ---- Drug classes -> fixed, reviewed messages (pre-translated at runtime, then cached) ----
CLASS_WARNINGS = [
    {"id": "antibiotic", "salts": ["amoxicillin", "azithromycin", "ofloxacin", "ciprofloxacin", "cefixime",
      "cefpodoxime", "levofloxacin", "doxycycline", "clindamycin", "metronidazole", "norfloxacin", "cefuroxime",
      "clavulanic", "clarithromycin", "linezolid", "cephalexin", "ceftriaxone"],
     "msg": "This looks like an antibiotic. Antibiotics work only on bacteria, not on colds or most fevers. "
            "Take it only if a doctor prescribed it. Finish the course the doctor gave. Do not share it with others."},
    {"id": "steroid", "salts": ["prednisolone", "dexamethasone", "methylprednisolone", "betamethasone", "hydrocortisone", "deflazacort"],
     "msg": "This looks like a steroid. Do not stop it suddenly or take it on your own. Ask the doctor who prescribed it."},
    {"id": "nsaid", "salts": ["diclofenac", "ibuprofen", "naproxen", "aceclofenac", "nimesulide", "ketorolac", "etoricoxib", "piroxicam", "mefenamic"],
     "msg": "This looks like a painkiller of the NSAID type. It can hurt the stomach, kidneys and heart if used too much or for long. "
            "Do not take it together with another painkiller. Ask a doctor if you have kidney, heart or stomach problems."},
    {"id": "sedative", "salts": ["alprazolam", "clonazepam", "diazepam", "lorazepam", "zolpidem", "nitrazepam"],
     "msg": "This looks like a sleep or anxiety medicine. It can cause drowsiness and dependence. Do not drive after taking it. Take it only as a doctor told you."},
    {"id": "codeine", "salts": ["codeine", "dextromethorphan"],
     "msg": "This cough medicine can cause drowsiness. Do not give it to young children unless a doctor says so."},
]

# ---- Small curated high-harm pair table. Only these are flagged. ----
SALT_GROUPS = {
    "nsaid": CLASS_WARNINGS[2]["salts"],
    "paracetamol": ["paracetamol", "acetaminophen"],
    "bloodthinner": ["warfarin", "clopidogrel", "aspirin", "rivaroxaban", "apixaban", "acenocoumarol", "ticagrelor"],
    "ace": ["enalapril", "lisinopril", "ramipril", "perindopril", "telmisartan", "losartan", "ramipril"],
    "potassium": ["potassium", "spironolactone"],
    "pde5": ["sildenafil", "tadalafil", "vardenafil"],
    "nitrate": ["nitroglycerin", "isosorbide", "glyceryl trinitrate"],
    "sedative": CLASS_WARNINGS[3]["salts"],
    "alcohol_like": ["metronidazole", "tinidazole", "ornidazole"],
}
PAIR_RULES = [
    ("nsaid", "nsaid", "Two painkillers of the NSAID type together can harm the stomach and kidneys."),
    ("nsaid", "bloodthinner", "A painkiller (NSAID) with a blood thinner can cause serious bleeding."),
    ("ace", "potassium", "This blood-pressure medicine with potassium can make potassium too high."),
    ("ace", "nsaid", "A painkiller (NSAID) with this blood-pressure medicine can strain the kidneys."),
    ("pde5", "nitrate", "This combination can drop blood pressure dangerously."),
    ("sedative", "sedative", "Two sleep/anxiety medicines together can cause dangerous drowsiness."),
    ("bloodthinner", "bloodthinner", "Two blood thinners together raise the risk of bleeding."),
]


def _groups_for(salt: str):
    s = salt.lower()
    return {g for g, items in SALT_GROUPS.items() if any(i in s for i in items)}


def check_list(meds: list[dict]) -> list[dict]:
    """meds: [{name, salts:[...]}]. Returns warnings. Deterministic, limited list only."""
    out, seen = [], set()
    for i, a in enumerate(meds):
        for j, b in enumerate(meds):
            if j <= i:
                continue
            sa = {s.lower().strip() for s in a.get("salts", []) if s}
            sb = {s.lower().strip() for s in b.get("salts", []) if s}
            same = sa & sb
            if same:
                out.append({"type": "duplicate", "a": a["name"], "b": b["name"], "detail": ", ".join(sorted(same)),
                            "msg": f"{a['name']} and {b['name']} both contain {', '.join(sorted(same))}. Taking both can mean too much of the same medicine."})
            ga = set().union(*[_groups_for(s) for s in sa]) if sa else set()
            gb = set().union(*[_groups_for(s) for s in sb]) if sb else set()
            for g1, g2, msg in PAIR_RULES:
                if (g1 in ga and g2 in gb) or (g2 in ga and g1 in gb):
                    key = (a["name"], b["name"], g1, g2)
                    if key not in seen and not (g1 == g2 and same):
                        seen.add(key)
                        out.append({"type": "interaction", "a": a["name"], "b": b["name"], "msg": msg})
    return out


def class_warnings_for(salts: list[str]) -> list[dict]:
    found = []
    joined = " ".join(s.lower() for s in salts)
    for c in CLASS_WARNINGS:
        if any(x in joined for x in c["salts"]):
            found.append({"id": c["id"], "msg": c["msg"]})
    return found


# ---- Expiry parsing (regex first; the LLM is only a fallback) ----
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_expiry(text: str):
    """Returns (year, month) or None. Looks near EXP/Expiry/Use before keywords."""
    if not text:
        return None
    t = text.replace("\n", " ")
    ctx = re.findall(r"(?:exp(?:iry)?\.?(?:\s*date)?|use\s*before|best\s*before)\s*[:\-.]?\s*([A-Za-z0-9 ./\-]{4,16})", t, re.I)
    for chunk in ctx:
        m = re.search(r"\b(0?[1-9]|1[0-2])\s*[./\-]\s*(20\d{2}|\d{2})\b", chunk)
        if m:
            mo, yr = int(m.group(1)), int(m.group(2))
            return (yr + 2000 if yr < 100 else yr, mo)
        m = re.search(r"\b([A-Za-z]{3})[A-Za-z]*[ ./\-]*(20\d{2}|\d{2})\b", chunk)
        if m and m.group(1).lower() in _MONTHS:
            yr = int(m.group(2))
            return (yr + 2000 if yr < 100 else yr, _MONTHS[m.group(1).lower()])
    return None


def expiry_verdict(ym, today: date | None = None):
    today = today or date.today()
    if not ym:
        return {"status": "unknown", "msg": "I cannot find an expiry date. Please check the strip or ask the pharmacist."}
    y, m = ym
    if (y, m) < (today.year, today.month):
        return {"status": "expired", "date": f"{m:02d}/{y}", "msg": f"Expiry date reads {m:02d}/{y}. This looks past its date. Do not use it. Ask the pharmacist."}
    return {"status": "ok", "date": f"{m:02d}/{y}", "msg": f"Expiry date reads {m:02d}/{y}, which is not past. Please confirm the date on the strip yourself."}


# ---- Suspicious-pack checklist (never a verdict) ----
def missing_details(text: str) -> list[str]:
    t = text or ""
    checks = {
        "batch number": r"b\.?\s*no|batch",
        "manufacturer or licence": r"mfg|manufactur|marketed|lic",
        "price (MRP)": r"m\.?r\.?p|price|rs\.?|₹",
        "expiry date": r"exp|use\s*before",
    }
    return [k for k, p in checks.items() if not re.search(p, t, re.I)]
