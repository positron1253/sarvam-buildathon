@echo off
if not exist .env (copy .env.example .env && echo Edit .env and add your SARVAM_API_KEY, then run start.bat again && exit /b)
pip install -q -r requirements.txt
python -m uvicorn server:app --port 8000
