# Dawai Dekho

Voice-first medicine helper for India, built on Sarvam AI. Photograph a medicine strip and hear what it is, whether it is expired, and what to watch out for, in your own language.

**Sarvam models used:** Vision (Document AI OCR), Sarvam-105B (extraction + multilingual chat), Saaras (speech-to-text), Bulbul (text-to-speech), Mayura (translation).

## Features
- Scan a strip or type a name; spoken explanation in 11 Indian languages (slow-speed replay)
- Deterministic expiry check, drug-class warnings (antibiotic/steroid/NSAID...), missing-details checklist
- Multilingual voice + text chatbot grounded on your saved medicines
- Duplicate-ingredient and high-risk interaction flags (small curated list; never a "safe" verdict)
- Emergency red-flag triage runs *before* the LLM; SOS screen with 112/108/102/Tele-MANAS, location share, eSanjeevani
- Medicine schedule with in-app reminders and calendar (.ics) export; WhatsApp share; installable PWA

Not medical advice. Never gives dosing or diagnosis.

## Run
```bash
pip install -U sarvamai fastapi "uvicorn[standard]" python-multipart python-dotenv requests
echo SARVAM_API_KEY=your_key > .env
python -m uvicorn server:app --port 8000
```
Open http://localhost:8000 (mic and camera need localhost or https).
