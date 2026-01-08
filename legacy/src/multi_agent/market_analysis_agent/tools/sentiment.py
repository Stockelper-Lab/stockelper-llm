import os
import asyncio
from datetime import datetime, timedelta
from typing import Type, Optional, Dict, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
import json
import dotenv


SENTIMENT_SYSTEM_TEMPLATE = "금융 텍스트의 감성을 분석하는 전문가입니다."
SENTIMENT_USER_TEMPLATE = """여러 텍스트의 감성 분석을 진행합니다. 각 텍스트의 긍정/부정 점수를 0과 1 사이의 숫자로만 출력해주세요. 

입력 텍스트:
{formatted_texts}

다음 형식으로만 출력하세요:
[
    {{
        "date": "2025/01/01",
        "positive": 0.8,
        "negative": 0.2,
    }},
    {{
        "date": "2025/01/02",
        "positive": 0.6,
        "negative": 0.4,
    }},
    ...
]"""

TREND_SYSTEM_TEMPLATE = "You are a financial analyst expert."
TREND_USER_TEMPLATE = """다음 금융 감성 분석 데이터를 분석하여 주요 감성 트렌드와 핵심 포인트를 파악해주세요:
{results}

다음 형식으로 분석 결과를 제공해주세요:
1. 전반적인 시장 심리 동향
2. 주요 변곡점과 그 원인
3. 향후 전망에 영향을 미칠 수 있는 핵심 요소"""


class ReportSentimentAnalysisInput(BaseModel):
    ticker_symbol: str = Field(
        description="Stock ticker symbol to analyze. e.g. 005930"
    )

class BaseSentimentAnalysisTool(BaseTool):
    name: str = "base_sentiment_analysis"
    sentiment_analysis_llm: ChatOpenAI
    trend_analysis_llm: ChatOpenAI

    def __init__(self):
        super().__init__(
            sentiment_analysis_llm=ChatOpenAI(model="gpt-5.1", temperature=0.0),
            trend_analysis_llm=ChatOpenAI(model="gpt-5.1", temperature=0.1)
        )

    async def analyze_sentiments_batch(self, texts: List[Dict]) -> List[Dict]:
        """한 번의 API 호출로 여러 텍스트의 감성 분석"""
        if not texts:
            return []
        
        formatted_texts = "\n\n".join([
            f"{text['date']}: {text['summary']}"
            for i, text in enumerate(texts)
        ])

        response = await self.sentiment_analysis_llm.ainvoke(
            [
                SystemMessage(content=SENTIMENT_SYSTEM_TEMPLATE),
                HumanMessage(content=SENTIMENT_USER_TEMPLATE.format(formatted_texts=formatted_texts))
            ]
        )

        try:
            results = response.content.strip()
        except Exception as e: 
            print(e)
            return []
        return results

    async def analyze_trends(self, results: str) -> str:
        """Analyze sentiment trends and key points."""
        response = await self.trend_analysis_llm.ainvoke(
            [
                SystemMessage(content=TREND_SYSTEM_TEMPLATE),
                HumanMessage(content=TREND_USER_TEMPLATE.format(results=results))
            ]
        )

        return response.content.strip()

class ReportSentimentAnalysisTool(BaseSentimentAnalysisTool):
    name: str = "report_sentiment_analysis"
    description: str = "Analyzes sentiment trends from stock market reports."
    args_schema: Type[BaseModel] = ReportSentimentAnalysisInput  
    return_direct: bool = False

    async def get_report_data(self, ticker_symbol: str, days: int = 30) -> List[Dict]:
        """Get report data from MongoDB collection."""
        end_date = datetime.now()
        start_date = (end_date - timedelta(days=days)).strftime("%Y/%m/%d")
        
        mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
        collection = mongo_client['stockelper']['report']
        
        data = []
        async for doc in collection.find(
            {"$and": [{"date": {"$gte": start_date}}, {"code": f"A{ticker_symbol}"}]},
            {"_id": False, "date": True, "summary": True}
        ):
            data.append(doc)
        
        return data
    
    def _run(
        self,
        ticker_symbol: str,
        config: RunnableConfig,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        return asyncio.run(self._arun(ticker_symbol, config, run_manager))
    
    async def _arun(
        self,
        ticker_symbol: str, 
        config: RunnableConfig,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        reports = await self.get_report_data(ticker_symbol)
        reports = sorted(reports, key=lambda x: x['date'])
        results = await self.analyze_sentiments_batch(reports)
        
        try:
            output = json.loads(results)
        except Exception as e:
            output = {"error": str(e)}

        return output
