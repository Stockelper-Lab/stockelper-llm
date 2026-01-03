# Stockelper LLM Service

LangGraph 기반 다중 에이전트 시스템을 활용한 AI 주식 분석 서비스입니다.

## 🚀 주요 기능

- **다중 에이전트 시스템**: SupervisorAgent가 4개의 전문 에이전트를 조율
- **실시간 스트리밍**: Server-Sent Events (SSE)로 토큰 단위 응답
- **한국 주식 시장 특화**: KIS API, DART, KRX 데이터 통합
- **자동 거래 제안**: 투자 전략에 기반한 매매 액션 생성
- **지식 그래프 통합**: Neo4j 기반 기업 관계 분석

## 📋 기술 스택

- **AI/ML**: LangGraph, LangChain 1.0+, OpenAI GPT-4.5.1
- **Web Framework**: FastAPI 0.111, Uvicorn
- **Database**: PostgreSQL (async), Neo4j, MongoDB
- **Data Analysis**: Prophet, ARIMA, Pandas, NumPy
- **Observability**: LangFuse (optional)
- **APIs**: KIS, DART, OpenRouter (Perplexity), YouTube

## 🤖 에이전트 시스템

### SupervisorAgent (관리자)
- 사용자 질의 라우팅
- 주식 종목 식별 (한국거래소 종목명 매칭)
- 거래 액션 생성 및 승인 요청

### MarketAnalysisAgent (시장 분석)
**도구:**
- SearchNewsTool - Perplexity 뉴스 검색
- SearchReportTool - 투자 리포트 검색
- YouTubeSearchTool - YouTube 콘텐츠 분석
- ReportSentimentAnalysisTool - 리포트 감정 분석
- GraphQATool - Neo4j 관계 그래프 검색

### FundamentalAnalysisAgent (기본적 분석)
**도구:**
- AnalysisFinancialStatementTool - DART 재무제표 분석 (5년 데이터)
  - 유동비율, 부채비율, 유보율, ROE, 이자보상배율 등

### TechnicalAnalysisAgent (기술적 분석)
**도구:**
- AnalysisStockTool - KIS API 실시간 주가/시장 정보
- PredictStockTool - Prophet + ARIMA 앙상블 예측
- StockChartAnalysisTool - 차트 이미지 분석

### InvestmentStrategyAgent (투자 전략)
**도구:**
- GetAccountInfoTool - KIS 계좌 잔고 조회
- InvestmentStrategySearchTool - 투자 전략 웹 검색

## 🔌 API 엔드포인트

### POST /stock/chat
SSE 스트리밍 채팅 인터페이스

**Request:**
```json
{
  "user_id": 1,
  "thread_id": "conversation_uuid",
  "message": "삼성전자 투자 전략 추천해줘",
  "human_feedback": null
}
```

**Response (SSE Stream):**
- Progress events: `{"type": "progress", "step": "agent_name", "status": "start|end"}`
- Delta events: `{"type": "delta", "token": "..."}`
- Final response: 완전한 메시지 + trading_action + subgraph
- Done marker: `[DONE]`

### GET /health
헬스 체크

## 🗄️ 데이터베이스

### PostgreSQL (3개 데이터베이스)
- **llm_users**: 사용자 데이터 (KIS 자격증명 포함)
- **checkpoint**: LangGraph 상태 체크포인트
- **ksic**: 한국 산업 분류

### Neo4j
- 기업 관계 그래프 (경쟁사, 섹터)

### MongoDB (Optional)
- 문서 저장소

## ⚙️ 환경 변수

```bash
# AI 서비스
OPENAI_API_KEY=                   # OpenAI GPT-4.5.1
OPENROUTER_API_KEY=               # Perplexity/OpenRouter
OPEN_DART_API_KEY=                # 한국 금융감독원
YOUTUBE_API_KEY=                  # YouTube 검색

# 한국투자증권 (KIS)
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=                   # 형식: "50132452-01"

# 데이터베이스
ASYNC_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/llm_users
CHECKPOINT_DATABASE_URI=postgresql://user:pass@host:5432/checkpoint
ASYNC_DATABASE_URL_KSIC=postgresql+asyncpg://user:pass@host:5432/ksic

# Neo4j
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_AUTH=password

# LangFuse (선택사항)
LANGFUSE_ENABLED=true/false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://localhost:21003

# 서비스 설정
STOCKELPER_SERVICE=chat           # "chat" 또는 "all"
STOCKELPER_BACKTESTING_URL=       # 백테스팅 서비스 URL (선택)
```

## 🐳 Docker 실행

```bash
# 모든 서비스 시작
docker-compose -f local.docker-compose.yml up -d

# LangFuse 포함
docker-compose -f local.docker-compose.yml --profile langfuse up -d

# 로그 확인
docker-compose logs -f llm-server
```

### 서비스 포트
- LLM Server: 21009
- PostgreSQL: 5432
- Redis: 6379
- LangFuse: 21003 (optional)

## 🔒 보안

- 모든 API 키를 환경 변수로 관리
- KIS 토큰 자동 갱신 (PostgreSQL 저장)
- `.env` 파일 절대 커밋 금지

## 📞 문의

- Issues: GitHub Issues 탭
- 기여: Pull Request 환영
