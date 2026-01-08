import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stockelper_llm.routers.base import router as base_router
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
app.include_router(stock_router)

