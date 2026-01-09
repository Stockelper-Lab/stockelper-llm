import os

import dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# .env 환경변수를 항상 로딩(uvicorn으로 직접 실행되는 경우도 커버)
dotenv.load_dotenv(override=True)

from stockelper_llm.routers.base import router as base_router
from stockelper_llm.routers.backtesting import router as backtesting_router
from stockelper_llm.routers.stock import router as stock_router


DEBUG = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}


app = FastAPI(debug=DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(base_router)
app.include_router(backtesting_router)
app.include_router(stock_router)

