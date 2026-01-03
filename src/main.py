import logging
import sys
import os
import dotenv

# 환경 변수 로딩을 최우선으로 처리
dotenv.load_dotenv(override=True)

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.base import router as base_router
from routers.stock import router as stock_router


DEBUG = False
HOST = "0.0.0.0"
PORT = 21009

# 서비스 모드:
# - chat: /stock (SSE chat) + /health
# - all: (레거시) 현재는 chat과 동일 동작
#
# NOTE: 포트폴리오/백테스팅 도메인은 별도 레포로 분리됨:
# - stockelper-portfolio (21010)
# - stockelper-backtesting (21011)
SERVICE_MODE = os.getenv("STOCKELPER_SERVICE", "chat").strip().lower()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# FastAPI 애플리케이션 생성
app = FastAPI(debug=DEBUG)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(base_router)
app.include_router(stock_router)

if SERVICE_MODE not in {"chat", "all"}:
    logger.warning(
        "STOCKELPER_SERVICE=%s 는 더 이상 지원되지 않습니다. chat 모드로 동작합니다.",
        SERVICE_MODE,
    )

if __name__ == "__main__":
    try:
        print(f"🚀 Starting Stockelper Server (mode={SERVICE_MODE})...")
        print(f"📍 Server will run on http://{HOST}:{PORT}")
        print(f"🔧 Debug mode: {DEBUG}")
        
        uvicorn.run(
            app, 
            host=HOST, 
            port=PORT, 
            reload=DEBUG,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1) 