"""Secrets loaded from .env (copy .env.example to .env for local development)."""

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "")
FLIGHTY_AUTH_TOKEN = os.environ.get("FLIGHTY_AUTH_TOKEN", "")
FLIGHTY_BUILD_TOKEN = os.environ.get("FLIGHTY_BUILD_TOKEN", "")
