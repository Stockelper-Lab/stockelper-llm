import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel, Field, field_validator
from langchain_core.tools import BaseTool
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
import asyncio
import os
import numpy as np
import base64
import mojito
import dotenv
from multi_agent.utils import get_user_kis_credentials
from sqlalchemy.ext.asyncio import create_async_engine


CHART_USER_TEMPLATE = """이 {stock_code} ({company_name}) 주식 차트를 분석하고 다음 정보를 제공해주세요:
1. 주요 기술적 패턴 및 현재 추세
2. 볼린저 밴드, 이동평균선, MACD 신호 분석
3. RSI와 스토캐스틱 지표 해석
4. 거래량 변화와 그 의미
5. 주요 지지/저항 레벨
6. 향후 가능한 가격 움직임에 대한 기술적 전망
7. 투자자에게 유용한 실행 가능한 인사이트"""


class StockChartAnalysisInput(BaseModel):
    """차트 분석 도구의 입력 파라미터를 정의하는 클래스"""
    
    stock_name: str = Field(..., description="분석할 주식 이름 (예: '삼성전자')")
    stock_code: str = Field(..., description="분석할 주식 코드 (예: '005930' for 삼성전자)")
    
    period_days: int = Field(
        default=180,
        description="분석할 기간 (일)",
        ge=1,
        le=3650
    )
    
    rsi_period: int = Field(
        default=14,
        description="RSI 계산 기간",
        ge=1,
        le=50
    )
    
    bb_period: int = Field(
        default=20,
        description="볼린저 밴드 계산 기간",
        ge=1,
        le=50
    )
    
    ma_periods: List[int] = Field(
        default=[20, 60, 120],
        description="이동평균선 계산 기간 리스트"
    )
    
    company_name: Optional[str] = Field(
        default="",
        description="회사명 (선택사항)"
    )
    
    stoch_k_period: int = Field(
        default=14,
        description="스토캐스틱 K 기간",
        ge=1,
        le=50
    )
    
    stoch_d_period: int = Field(
        default=3,
        description="스토캐스틱 D 기간",
        ge=1,
        le=20
    )
    
    @field_validator('stock_code')
    def validate_stock_code(cls, v):
        if not v.isdigit():
            raise ValueError("한국 주식 코드는 숫자로만 이루어져 있어야 합니다")
        if len(v) != 6:
            raise ValueError("한국 주식 코드는 6자리 숫자여야 합니다")
        return v

class StockChartAnalyzer:
    """한국 주식 차트 생성 및 AI 분석 클래스"""
    
    def __init__(self, llm, async_database_url: str):
        # 차트 스타일 설정
        plt.style.use('default')
        plt.rcParams.update({
            'figure.figsize': (12, 6),
            'axes.grid': True,
            'grid.alpha': 0.3,
        })
        
        # 마이너스 기호 깨짐 방지 설정만 유지
        plt.rcParams['axes.unicode_minus'] = False
        
        # Vision 모델 초기화
        self.llm = llm
        
        # 환경변수 로드
        dotenv.load_dotenv()

        self.async_engine = create_async_engine(async_database_url, echo=False)

    async def get_stock_data(self, stock_code: str, period_days: int, user_id: int):
        """한국 주식 데이터 조회 - mojito(한국투자증권 API) 사용"""
        try:
            # 환경변수에서 API 키 및 계좌번호 가져오기
            user_info = await get_user_kis_credentials(self.async_engine, user_id)
            
            # mojito 브로커 객체 생성
            broker = mojito.KoreaInvestment(api_key=user_info['kis_app_key'], api_secret=user_info['kis_app_secret'], acc_no=user_info['account_no'])
            
            # 일봉 데이터 조회
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)
            resp = broker.fetch_ohlcv(stock_code, "D", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
            
            # 응답 데이터를 DataFrame으로 변환
            data = resp['output2']
            
            # 데이터 정리
            df_data = []
            for item in data:
                date = pd.to_datetime(item['stck_bsop_date'])
                open_price = float(item['stck_oprc'])
                high_price = float(item['stck_hgpr'])
                low_price = float(item['stck_lwpr'])
                close_price = float(item['stck_clpr'])
                volume = int(item['acml_vol'])
                
                # 전일 대비 변화율 계산
                prdy_vrss = float(item['prdy_vrss'])  # 전일 대비 가격 차이
                
                # 전일가 계산 및 변화율 계산
                if prdy_vrss != 0:
                    prev_close = close_price - prdy_vrss
                    change = prdy_vrss / prev_close
                else:
                    change = 0.0
                
                df_data.append({
                    'Date': date,
                    'Open': open_price,
                    'High': high_price,
                    'Low': low_price,
                    'Close': close_price,
                    'Volume': volume,
                    'Change': change
                })
            
            # DataFrame 생성
            df = pd.DataFrame(df_data)
            df = df.set_index('Date')
            df = df.sort_index()  # 날짜 순으로 정렬
            
            return df
                
        except Exception as e:
            return None

    def _calculate_rsi(self, data: pd.DataFrame, period: int) -> pd.Series:
        """RSI 계산"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
        
    def _calculate_stochastic(self, data: pd.DataFrame, k_period: int, d_period: int) -> tuple:
        """스토캐스틱 계산"""
        low_min = data['Low'].rolling(window=k_period).min()
        high_max = data['High'].rolling(window=k_period).max()
        
        k = 100 * ((data['Close'] - low_min) / (high_max - low_min))
        d = k.rolling(window=d_period).mean()
        return k, d

    async def create_chart(self, input_data: StockChartAnalysisInput, user_id: int) -> str:
        """차트 생성 및 저장"""
        try:
            df = await self.get_stock_data(input_data.stock_code, input_data.period_days, user_id)
            info = {"longName": input_data.stock_name}
            if df is None:
                return None, None
            
            # 기술적 지표 계산
            # MACD
            exp1 = df['Close'].ewm(span=12, adjust=False).mean()
            exp2 = df['Close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            
            # 볼린저 밴드
            bb_middle = df['Close'].rolling(window=input_data.bb_period).mean()
            bb_std = df['Close'].rolling(window=input_data.bb_period).std()
            bb_upper = bb_middle + (bb_std * 2)
            bb_lower = bb_middle - (bb_std * 2)
            
            # RSI
            rsi = self._calculate_rsi(df, input_data.rsi_period)
            
            # 스토캐스틱
            k, d = self._calculate_stochastic(df, input_data.stoch_k_period, input_data.stoch_d_period)

            # 차트 생성 (5개 차트로 구성)
            fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(5, 1, figsize=(12, 20),
                                                     gridspec_kw={'height_ratios': [3, 1, 1, 1, 1]})
            
            # 메인 차트
            ax1.plot(df.index, df['Close'], label='Close', color='blue', alpha=0.7)
            ax1.plot(df.index, bb_upper, 'r--', alpha=0.3, label='BB Upper')
            ax1.plot(df.index, bb_middle, 'g--', alpha=0.3, label='BB Middle')
            ax1.plot(df.index, bb_lower, 'r--', alpha=0.3, label='BB Lower')
            
            for period in input_data.ma_periods:
                ma = df['Close'].rolling(window=period).mean()
                ax1.plot(df.index, ma, label=f'MA{period}', alpha=0.7)

            # 거래량 차트
            ax2.bar(df.index, df['Volume'], label='Volume', color='darkgray', alpha=0.7)
            
            # MACD 차트
            ax3.plot(df.index, macd, label='MACD', color='blue')
            ax3.plot(df.index, signal, label='Signal', color='orange')
            ax3.bar(df.index, macd - signal, label='MACD Histogram', color='gray', alpha=0.3)
            
            # 스토캐스틱 차트
            ax4.plot(df.index, k, label='%K', color='blue')
            ax4.plot(df.index, d, label='%D', color='red')
            ax4.axhline(y=80, color='r', linestyle='--', alpha=0.3)
            ax4.axhline(y=20, color='g', linestyle='--', alpha=0.3)
            ax4.set_ylabel('Stochastic')
            
            # RSI 차트
            ax5.plot(df.index, rsi, label='RSI', color='purple')
            ax5.axhline(y=70, color='r', linestyle='--', alpha=0.3)
            ax5.axhline(y=30, color='g', linestyle='--', alpha=0.3)
            ax5.set_ylabel('RSI')
            ax5.set_ylim([0, 100])
            
            # 차트 스타일링
            company_name = input_data.company_name or info.get('longName', 'Unknown')
            ax1.set_title(f'{input_data.stock_code} Technical Analysis Chart')
            ax1.legend(loc='upper left')
            ax2.legend(loc='upper left')
            ax3.legend(loc='upper left')
            ax4.legend(loc='upper left')
            ax5.legend(loc='upper left')
            
            ax5.set_xlabel('Date')
            ax1.set_ylabel('Price')
            ax2.set_ylabel('Volume')
            ax3.set_ylabel('MACD')
            ax4.set_ylabel('Stochastic')
            ax5.set_ylabel('RSI')

            plt.tight_layout()
            
            # 차트 저장
            save_path = 'charts'
            os.makedirs(save_path, exist_ok=True)
            chart_path = os.path.join(save_path, f"{input_data.stock_code}_analysis.png")
            plt.savefig(chart_path)
            plt.close()

            return chart_path, company_name
        except Exception as e:
            print(f"차트 생성 실패: {str(e)}")
            return None, None

    async def analyze_chart(self, chart_path: str, stock_code: str, company_name: str) -> str:
        """차트 이미지 분석"""
        try:
            # 이미지를 base64로 인코딩
            with open(chart_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode()

            # Vision 모델에 전송할 메시지 구성
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": CHART_USER_TEMPLATE.format(stock_code=stock_code, company_name=company_name)
                        }
                    ]
                }
            ]

            # 분석 실행
            response = await self.llm.ainvoke(messages)
            return response.content.strip()

        except Exception as e:
            return f"차트 분석 중 오류 발생: {str(e)}"

class StockChartAnalysisTool(BaseTool):
    """한국 주식 차트 생성 및 AI 분석 도구"""
    
    name: str = "korean_stock_chart_analysis"
    description: str = """
    한국 주식의 기술적 차트를 생성하고 AI를 통해 차트 패턴, 추세, 기술적 지표를 분석합니다.
    볼린저 밴드, 이동평균선, MACD, RSI, 스토캐스틱 등의 기술 지표를 포함한 차트를 생성하고
    GPT-5.1을 통해 차트의 패턴과 가능한 가격 움직임을 자세히 분석합니다.
    """
    args_schema: Type[BaseModel] = StockChartAnalysisInput
    analyzer: StockChartAnalyzer
    return_direct: bool = False

    def __init__(self, async_database_url: str):
        llm = ChatOpenAI(
            model="gpt-5.1",
            max_tokens=32768,
            temperature=0
        ) 
        super().__init__(
            analyzer=StockChartAnalyzer(llm=llm, async_database_url=async_database_url)
        )

    def _run(
        self,
        stock_name: str,
        stock_code: str,
        period_days: int = 180,
        rsi_period: int = 14,
        bb_period: int = 20,
        ma_periods: List[int] = None,
        company_name: str = "",
        stoch_k_period: int = 14,
        stoch_d_period: int = 3,
        config: RunnableConfig = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """동기 실행 메서드"""
        if ma_periods is None:
            ma_periods = [20, 60, 120]
            
        return asyncio.run(self._arun(
            stock_name=stock_name,
            stock_code=stock_code,
            period_days=period_days,
            rsi_period=rsi_period,
            bb_period=bb_period,
            ma_periods=ma_periods,
            company_name=company_name,
            stoch_k_period=stoch_k_period,
            stoch_d_period=stoch_d_period,
            config=config,
            run_manager=run_manager
        ))

    async def _arun(
        self,
        stock_name: str,
        stock_code: str,
        period_days: int = 180,
        rsi_period: int = 14,
        bb_period: int = 20,
        ma_periods: List[int] = None,
        company_name: str = "",
        stoch_k_period: int = 14,
        stoch_d_period: int = 3,
        config: RunnableConfig = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        try:
            if ma_periods is None:
                ma_periods = [20, 60, 120]
                
            # 입력 데이터 생성
            input_data = StockChartAnalysisInput(
                stock_name=stock_name,
                stock_code=stock_code,
                period_days=period_days,
                rsi_period=rsi_period,
                bb_period=bb_period,
                ma_periods=ma_periods,
                company_name=company_name,
                stoch_k_period=stoch_k_period,
                stoch_d_period=stoch_d_period
            )
            
            # 차트 생성
            chart_path, company_name = await self.analyzer.create_chart(input_data, user_id=config["configurable"]["user_id"])
            if not chart_path:
                return {"error": "차트 생성에 실패했습니다."}
            
            # 차트 AI 분석
            analysis = await self.analyzer.analyze_chart(chart_path, stock_code, company_name)
            
            output = {
                "stock_code": stock_code,
                "company_name": company_name,
                "analysis": analysis,
            }

            return output
            
        except Exception as e:
            return {"error": f"분석 중 오류 발생: {str(e)}"}
