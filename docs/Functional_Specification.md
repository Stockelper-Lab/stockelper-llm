# Stockelper AI 챗봇 기능명세서

## 📋 개요

**Stockelper AI 챗봇**은 LangGraph 기반 다중 에이전트 시스템을 활용한 지능형 주식 투자 어시스턴트입니다. 실시간 시장 분석부터 실제 거래 실행까지 종합적인 투자 서비스를 제공합니다.

### 🎯 핵심 목표
- AI 기반 종합 주식 분석 서비스 제공
- 실시간 시장 데이터와 뉴스 분석
- 개인화된 투자 전략 수립
- 안전한 실제 거래 실행 지원

---

## 🤖 AI 에이전트 시스템

### 1. SupervisorAgent (관리자 에이전트)

#### 📌 주요 기능
- **질문 분석 및 라우팅**: 사용자 질문을 분석하여 적절한 전문 에이전트에게 작업 할당
- **에이전트 조율**: 여러 에이전트의 협업 관리 및 결과 통합
- **거래 결정**: 투자 전략 에이전트 결과를 바탕으로 실제 거래 제안
- **주식 정보 추출**: 질문에서 주식명/코드 자동 추출 및 관련 정보 수집

#### 🔄 워크플로우
```
사용자 질문 → 질문 분석 → 에이전트 선택 → 병렬 실행 → 결과 통합 → 응답 생성
                                                    ↓
                                            거래 제안 → 인간 승인 → 실제 거래
```

#### 🔧 에이전트 초기화와 의존성 주입(DI)
- 에이전트는 애플리케이션 import 시점이 아니라, 요청 처리 시점에 `get_multi_agent(async_database_url)`로 생성됩니다.
- 최초 1회 생성 후 캐시되어 재사용되며, `ASYNC_DATABASE_URL` 또는 `DATABASE_URL`이 필요합니다. (`DATABASE_URL=postgresql://...`도 자동으로 asyncpg URL로 변환됩니다.)

#### 📊 상태 관리
- `messages`: 대화 히스토리
- `query`: 현재 사용자 질문
- `agent_results`: 각 에이전트 분석 결과
- `trading_action`: 거래 액션 정보
- `stock_name/code`: 추출된 주식 정보
- `subgraph`: Neo4j 서브그래프 데이터

### 2. MarketAnalysisAgent (시장 분석 에이전트)

#### 📌 주요 기능
- **실시간 뉴스 분석**: Perplexity API를 통한 관련 뉴스 검색 및 감성 분석
- **투자 리포트 분석**: MongoDB에서 전문가 리포트 검색 및 감정 분석
- **소셜 미디어 트렌드**: YouTube 주식 관련 콘텐츠 분석
- **관계 분석**: Neo4j 지식그래프를 통한 기업 관계 분석

#### 🛠️ 사용 도구
- `SearchNewsTool`: 뉴스 검색 및 요약
- `SearchReportTool`: 투자 리포트 검색
- `ReportSentimentAnalysisTool`: 리포트 감정 분석
- `YouTubeSearchTool`: YouTube 콘텐츠 검색
- `GraphQATool`: 지식그래프 질의응답

### 3. FundamentalAnalysisAgent (기업 분석 에이전트)

#### 📌 주요 기능
- **재무제표 분석**: DART API를 통한 공시 정보 수집 및 분석
- **기업 가치 평가**: DCF, PER, PBR 등 밸류에이션 모델 적용
- **경쟁사 비교**: 동종업계 기업들과의 재무 지표 비교
- **ESG 평가**: 환경, 사회, 지배구조 요소 분석

#### 🛠️ 사용 도구
- `AnalysisFinancialStatementTool`: 재무제표 종합 분석

### 4. TechnicalAnalysisAgent (기술 분석 에이전트)

#### 📌 주요 기능
- **차트 패턴 분석**: 멀티모달 AI를 활용한 차트 이미지 분석
- **기술적 지표 계산**: RSI, MACD, 볼린저밴드 등 주요 지표 분석
- **주가 예측**: Prophet, ARIMA 모델을 활용한 단기 주가 예측 (FDR에 Change 컬럼이 없을 경우 Close 기반 pct_change로 자동 생성)
- **매매 타이밍**: 기술적 분석 기반 매수/매도 시점 추천

#### 🛠️ 사용 도구
- `AnalysisStockTool`: 종합 주식 정보 분석
- `StockChartAnalysisTool`: 차트 이미지 생성 및 분석
- `PredictStockTool`: AI 기반 주가 예측

### 5. PortfolioAnalysisAgent (포트폴리오 분석 에이전트)

#### 📌 주요 기능
- **포트폴리오 최적화**: 현대 포트폴리오 이론 기반 자산 배분
- **리스크 분석**: VaR, 샤프 비율 등 위험 지표 계산
- **성과 평가**: 벤치마크 대비 수익률 및 위험 조정 수익률 분석
- **리밸런싱 제안**: 목표 자산 배분 대비 조정 방안 제시

#### 🛠️ 사용 도구
- `PortfolioAnalysisTool`: 포트폴리오 종합 분석

### 6. InvestmentStrategyAgent (투자 전략 에이전트)

#### 📌 주요 기능
- **개인화 전략**: 사용자 리스크 프로파일 기반 맞춤 전략 수립
- **거래 실행**: KIS API 연동을 통한 실제 매매 주문 (hashkey 헤더 포함, 헤더 키 통일)
- **계정 관리**: 사용자 투자 계정 정보 조회 및 관리
- **전략 검색**: 시장 상황에 맞는 투자 전략 검색 및 추천

#### 🛠️ 사용 도구
- `GetAccountInfoTool`: 계정 정보 조회
- `InvestmentStrategySearchTool`: 투자 전략 검색

---

## 🌐 API 명세

### 기본 정보
- **Base URL**: `http://localhost:21009`
- **Protocol**: HTTP/HTTPS
- **Response Format**: JSON, Server-Sent Events (SSE)

### 엔드포인트

#### 1. 주식 챗봇 대화 API

```http
POST /stock/chat
Content-Type: application/json
```

**요청 모델**
```json
{
  "user_id": 1,
  "thread_id": "unique-thread-id",
  "message": "삼성전자 주식 분석해줘",
  "human_feedback": null
}
```

**응답 형식** (Server-Sent Events)
```
data: {"type": "progress", "step": "supervisor", "status": "start"}
data: {"type": "progress", "step": "MarketAnalysisAgent", "status": "start"}
data: {"type": "progress", "step": "SearchNewsTool", "status": "start"}
...
data: {"type": "final", "message": "분석 결과...", "subgraph": {...}, "trading_action": {...}}
data: [DONE]
```

요청 처리 시 내부 동작 요약
- PostgreSQL 체크포인터로 LangGraph 상태를 저장/복구합니다.
- 멀티에이전트는 `get_multi_agent(to_async_sqlalchemy_url(os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL")))`로 획득합니다.
- 각 에이전트/도구 실행 상황은 `progress` 이벤트로 스트리밍됩니다.

#### 2. 기본 상태 확인 API

```http
GET /health
```

**응답**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-XX 18:14:24"
}
```

---

## 💾 데이터 모델

### 사용자 정보 (PostgreSQL)
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    kis_app_key TEXT NOT NULL,
    kis_app_secret TEXT NOT NULL,
    kis_access_token TEXT,
    account_no TEXT NOT NULL,
    investor_type TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 대화 상태 (LangGraph State)
```python
@dataclass
class State:
    messages: List[BaseMessage]           # 대화 히스토리
    query: str                           # 현재 질문
    agent_messages: List[dict]           # 에이전트 메시지
    agent_results: List[dict]            # 에이전트 결과
    execute_agent_count: int             # 실행된 에이전트 수
    trading_action: dict                 # 거래 액션
    stock_name: str                      # 주식명
    stock_code: str                      # 주식 코드
    subgraph: dict                       # Neo4j 서브그래프
```

### 거래 액션 모델
```python
class TradingAction(BaseModel):
    stock_code: str                      # 주식 코드
    order_side: str                      # "buy" or "sell"
    order_type: str                      # "market" or "limit"
    order_price: Optional[float]         # 지정가 (시장가시 None)
    order_quantity: int                  # 주문 수량
```

---

## 🔧 시스템 요구사항

### 환경 변수
```bash
# AI 서비스
OPENAI_API_KEY=sk-...                   # OpenAI GPT 모델
OPENROUTER_API_KEY=sk-...               # Perplexity API

# 데이터베이스
DATABASE_URL=postgresql://.../stockelper_web        # 사용자 DB (stockelper_web.users)
ASYNC_DATABASE_URL=postgresql+asyncpg://.../stockelper_web  # (선택) 미지정 시 DATABASE_URL로부터 변환
CHECKPOINT_DATABASE_URI=postgresql://.../checkpoint  # (선택) 미지정 시 DATABASE_URL 사용
MONGO_URI=mongodb://...
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# 외부 API
OPEN_DART_API_KEY=...                   # DART 공시 시스템
YOUTUBE_API_KEY=...                     # YouTube API
# KIS_BASE_URL/TR_ID 는 (선택)이며, 사용자별 자격증명(app_key/secret/account_no/token)은
# stockelper_web.users에서 user_id로 조회/갱신합니다.
KIS_BASE_URL=https://openapivts.koreainvestment.com:29443
KIS_TR_ID_BALANCE=VTTC8434R
KIS_TR_ID_ORDER_BUY=VTTC0802U
KIS_TR_ID_ORDER_SELL=VTTC0011U
```

### 운영 안정성(최근 반영)
- 주문 API: `hashkey` 헤더 추가 및 `appkey/appsecret` 통일
- 토큰 만료: “유효하지 않은 token” / “기간이 만료된 token” 모두 인식
- 타임아웃: aiohttp `ClientTimeout(total=30)` 적용
- 지연 초기화: Mongo/DART 클라이언트는 실제 호출 시 생성
- 데이터 보강: FDR Change 컬럼 자동 생성
- 캐싱: KRX 상장 목록 1회 로드/캐시

### 시스템 의존성
- **Python 3.11+**
- **Docker & Docker Compose**
- **PostgreSQL 15+**
- **Neo4j 5.0+**
- **MongoDB 6.0+**

---

## 🚀 사용자 인터페이스

### 1. 웹 인터페이스 (Streamlit)
```bash
streamlit run src/frontend/streamlit_app.py
```

#### 주요 기능
- **실시간 채팅**: SSE 기반 실시간 대화
- **진행상황 표시**: 각 에이전트 실행 상태 시각화
- **거래 승인**: 실제 거래 전 사용자 확인 인터페이스
- **포트폴리오 대시보드**: 계정 정보 및 보유 종목 현황

### 2. API 클라이언트
```python
import requests

# 채팅 요청
response = requests.post(
    "http://localhost:21009/stock/chat",
    json={
        "user_id": 1,
        "thread_id": "test-thread",
        "message": "삼성전자 투자 분석해줘"
    },
    stream=True
)

# SSE 응답 처리
for line in response.iter_lines():
    if line.startswith(b'data: '):
        data = json.loads(line[6:])
        print(data)
```

---

## 🔒 보안 및 안전 기능

### 거래 안전장치
1. **인간 승인 필수**: 모든 실제 거래는 사용자 승인 후 실행
2. **거래 한도**: 계정별 일일/월간 거래 한도 설정
3. **리스크 체크**: 과도한 위험 거래 시 경고 및 차단
4. **감사 로그**: 모든 거래 내역 및 결정 과정 기록

### 데이터 보안
1. **API 키 암호화**: 민감한 API 키 정보 암호화 저장
2. **접근 제어**: 사용자별 데이터 접근 권한 관리
3. **세션 관리**: 안전한 세션 토큰 기반 인증
4. **데이터 마스킹**: 로그에서 민감 정보 마스킹

---

## 📊 모니터링 및 관찰성

### Langfuse 통합
- **대화 추적**: 전체 대화 플로우 및 에이전트 실행 과정 기록
- **성능 모니터링**: 응답 시간, 토큰 사용량, 에러율 추적
- **사용자 분석**: 사용 패턴 및 만족도 분석
- **비용 관리**: AI 모델 사용 비용 추적 및 최적화

### 로깅 시스템
```python
# 구조화된 로깅
logger.info(f"User {user_id} requested analysis for {stock_name}")
logger.error(f"Trading failed: {error_message}", extra={
    "user_id": user_id,
    "stock_code": stock_code,
    "action": trading_action
})
```

---

## 🔄 확장성 및 유지보수

### 새로운 에이전트 추가
1. `BaseAnalysisAgent` 상속 클래스 생성
2. 전용 도구(Tools) 개발
3. `multi_agent/__init__.py`에 에이전트 등록
4. 프롬프트 및 시스템 메시지 정의

### 새로운 도구 추가
```python
from langchain_core.tools import BaseTool

class NewAnalysisTool(BaseTool):
    name = "new_analysis_tool"
    description = "새로운 분석 도구"
    
    async def _arun(self, query: str) -> dict:
        # 도구 로직 구현
        return {"result": "분석 결과"}
```

### 성능 최적화
- **캐싱**: Redis를 활용한 분석 결과 캐싱
- **병렬 처리**: asyncio 기반 비동기 처리 최적화
- **데이터베이스 최적화**: 인덱싱 및 쿼리 최적화
- **모델 최적화**: 더 효율적인 AI 모델로 업그레이드

---

## 📈 향후 개발 계획

### Phase 1: 기본 기능 완성
- ✅ 다중 에이전트 시스템 구축
- ✅ 실시간 데이터 연동
- ✅ 기본 거래 기능

### Phase 2: 고도화
- 🔄 백테스팅 시스템 추가
- 🔄 더 정교한 리스크 관리
- 🔄 모바일 앱 개발

### Phase 3: 확장
- 📋 해외 주식 지원
- 📋 암호화폐 분석 추가
- 📋 소셜 트레이딩 기능

---

*본 문서는 Stockelper AI 챗봇의 기능명세서입니다. 시스템의 지속적인 개선에 따라 내용이 업데이트될 수 있습니다.*
