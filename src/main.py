import logging
import os
import sys

import dotenv
import uvicorn

# 환경 변수 로딩을 최우선으로 처리
dotenv.load_dotenv(override=True)

from stockelper_llm.webapp import app  # noqa: E402


DEBUG = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "21009"))

# 서비스 모드:
# - chat: /stock/chat (SSE) + /health
# - all: (레거시) 현재는 chat과 동일 동작
SERVICE_MODE = os.getenv("STOCKELPER_SERVICE", "chat").strip().lower()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    if SERVICE_MODE not in {"chat", "all"}:
        logger.warning(
            "STOCKELPER_SERVICE=%s 는 더 이상 지원되지 않습니다. chat 모드로 동작합니다.",
            SERVICE_MODE,
        )
    try:
        print(f"🚀 Starting Stockelper Server (mode={SERVICE_MODE})...")
        print(f"📍 Server will run on http://{HOST}:{PORT}")
        print(f"🔧 Debug mode: {DEBUG}")

        uvicorn.run(
            app,
            host=HOST,
            port=PORT,
            reload=DEBUG,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)

