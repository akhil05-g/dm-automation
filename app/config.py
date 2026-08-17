import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
PSEUDOGRAM_API_KEY = os.getenv("PSEUDOGRAM_API_KEY", "")
PSEUDOGRAM_BASE_URL = os.getenv("PSEUDOGRAM_BASE_URL", "https://pseudogram-api.onrender.com")
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "linkplease.db"))
