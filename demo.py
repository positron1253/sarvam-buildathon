"""One-command demo of every Sarvam-powered step, no browser needed.

    python demo.py                 # Hindi
    python demo.py --lang ta-IN    # any of: hi-IN en-IN bn-IN ta-IN te-IN kn-IN ml-IN mr-IN gu-IN pa-IN od-IN
    python demo.py --no-audio      # skip text-to-speech (saves credits)

Costs roughly Rs 5-8 of Sarvam credits per run (cached results are free on re-runs).
Audio is written to ./demo_out/*.wav so you can play it.
"""
import argparse, base64, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")

import server as S  # noqa: E402  (loads .env)
import knowledge as K  # noqa: E402


def hr(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def save_audio(name, text, lang):
    j = S.tts(S.TtsIn(text=text, lang=lang))
    audios = j["audios"] if isinstance(j, dict) else []
    if not audios:
        print("   (audio unavailable)")
        return
    out = HERE / "demo_out"
    out.mkdir(exist_ok=True)
    p = out / f"{name}.wav"
    p.write_bytes(b"".join(base64.b64decode(a) for a in audios[:1]))
    print(f"   audio saved: {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="hi-IN", choices=list(K.LANGS))
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()

    if not S.KEY or S.KEY.startswith("your_"):
        sys.exit("Set SARVAM_API_KEY in .env first (copy .env.example). Get a key at https://dashboard.sarvam.ai")

    # 1. Scan the sample strips: Vision OCR -> 105B extraction -> deterministic checks -> translation
    meds = []
    for f, label in [("expired_paracetamol.jpg", "An EXPIRED strip"), ("painkiller_nsaid.jpg", "A painkiller (NSAID)"),
                     ("antibiotic.jpg", "An antibiotic")]:
        hr(f"SCAN: {label}")
        data = (HERE / "samples" / f).read_bytes()
        ocr = S.ocr_image(data, f, "image/jpeg")
        med = S.structure_medicine(ocr)
        verdict = K.expiry_verdict(K.parse_expiry(ocr))
        cw = K.class_warnings_for(med.get("salts", []) + [med.get("name", "")])
        print(f"   OCR text : {ocr[:110]}")
        print(f"   Medicine : {med.get('name')} | salts={med.get('salts')} | {med.get('strength')}")
        print(f"   Expiry   : [{verdict['status'].upper()}] {verdict['msg']}")
        for w in cw:
            print(f"   Card     : {w['id']}: {S.translate(w['msg'], a.lang)[:110]}")
        script = S.translate(S.spoken_script(med, verdict, cw, a.lang), a.lang)
        print(f"   Spoken   : {script[:230]}")
        meds.append({"name": med.get("name", f), "salts": med.get("salts", [])})
        if not a.no_audio and f == "expired_paracetamol.jpg":
            save_audio("scan_result", script, a.lang)

    # 2. Safety checks across the saved list (deterministic, curated list only)
    hr("INTERACTION CHECK on the saved list")
    meds.append({"name": "Brufen 400", "salts": ["ibuprofen"]})
    for w in K.check_list(meds):
        print("  -", S.translate(w["msg"], a.lang))

    # 3. Chatbot: normal question, then an emergency (red-flag rules run before the LLM)
    hr(f"CHAT ({K.LANGS[a.lang]})")
    q = "Can I take paracetamol on an empty stomach?"
    print("  Q:", q)
    r = S.chat(S.ChatIn(messages=[{"role": "user", "content": q}], lang=a.lang, medicines=meds))
    print("  A:", r["reply"])
    q = "I have chest pain and trouble breathing"
    print("  Q:", q)
    r = S.chat(S.ChatIn(messages=[{"role": "user", "content": q}], lang=a.lang))
    print(f"  A: [EMERGENCY={r['emergency']}]", r["reply"])
    if not a.no_audio:
        save_audio("emergency_reply", r["reply"], a.lang)

    hr("DONE")
    print("Run the full app:  python -m uvicorn server:app --port 8000   then open http://localhost:8000")


if __name__ == "__main__":
    main()
