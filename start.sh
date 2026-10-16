#!/usr/bin/env bash
set -e
[ -f .env ] || { cp .env.example .env; echo "Edit .env and add your SARVAM_API_KEY, then run ./start.sh again"; exit 0; }
pip install -q -r requirements.txt
python -m uvicorn server:app --port 8000
