import os
from dotenv import load_dotenv

load_dotenv()

ZAI_API_KEY = os.getenv("ZAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")