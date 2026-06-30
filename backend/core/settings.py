"""Project Atlas — environment + shared settings."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ.get("JWT_SECRET", "devsecret")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
EMERGENT_BASE_URL = os.environ.get(
    "EMERGENT_BASE_URL", "https://integrations.emergentagent.com/llm/openai/v1"
)
APP_VERSION = "2.0.0"
PROJECT_NAME = "Project Atlas"
