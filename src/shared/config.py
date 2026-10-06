import os

APP_NAME = "tools-platform"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
ALLOWED_ORIGINS = [
    item.strip() for item in os.getenv("ALLOWED_ORIGINS", "").split(",") if item.strip()
]
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
MAX_ACCOUNTS = int(os.getenv("MAX_ACCOUNTS", "8"))
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "86400"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
