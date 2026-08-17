import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
PSEUDOGRAM_API_KEY = os.getenv("PSEUDOGRAM_API_KEY", "")
PSEUDOGRAM_BASE_URL = os.getenv("PSEUDOGRAM_BASE_URL", "https://pseudogram-api.onrender.com")
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "linkplease.db"))

RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60.0
LEASE_DURATION_SECONDS = 30
MAX_JOB_RETRIES = 5
RECONCILIATION_INTERVAL_SECONDS = 2.0
