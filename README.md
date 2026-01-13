# Stockelper LLM Service

> LangGraph 기반 다중 에이전트 시스템을 활용한 AI 주식 투자 분석 서비스

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-1.0+-green.svg)](https://www.langchain.com/)

## 목차

- [개요](#개요)
- [주요 기능](#-주요-기능)
- [기술 스택](#-기술-스택)
- [에이전트 시스템](#-에이전트-시스템)
- [코드 구조](#-코드-구조)
- [빠른 시작](#-빠른-시작)
- [API 엔드포인트](#-api-엔드포인트)
- [환경 변수](#-환경-변수)
- [Docker 배포](#-docker-배포)
- [프로젝트 구조](#프로젝트-구조)
- [데이터베이스](#-데이터베이스)
- [개발 가이드](#개발-가이드)
- [문제 해결](#문제-해결)
- [라이선스](#-라이선스)

## 개요

**Stockelper LLM Service**는 LangGraph 기반 다중 에이전트 시스템을 활용하여 한국 주식 시장 분석 및 투자 전략 추천을 제공하는 AI 서비스입니다. SupervisorAgent가 4개의 전문 에이전트(시장 분석, 기본적 분석, 기술적 분석, 투자 전략)를 조율하여 실시간 스트리밍 방식으로 종합적인 투자 인사이트를 제공합니다.

## ✨ 주요 기능

- **다중 에이전트 시스템**: SupervisorAgent가 4개의 전문 에이전트를 조율
- **실시간 스트리밍**: Server-Sent Events (SSE)로 토큰 단위 응답 제공
- **한국 주식 시장 특화**: KIS API, DART, KRX 데이터 통합
- **자동 거래 제안**: 투자 전략에 기반한 매매 액션 생성
- **지식 그래프 통합**: Neo4j 기반 기업 관계 분석
- **백테스팅 연동**: 전략 검증 및 LLM 기반 결과 해석
- **포트폴리오 추천**: 투자자 성향 기반 맞춤형 포트폴리오

## 📋 기술 스택

### AI/ML
- **LangGraph**: 다중 에이전트 오케스트레이션
- **LangChain 1.0+**: 에이전트 및 도구 체인 구성
- **OpenAI GPT-4/GPT-5.1**: 대화 및 분석 모델
- **Prophet & ARIMA**: 주가 예측 앙상블 모델
- **LangFuse**: 옵저버빌리티 및 추적 (선택사항)

### 웹 프레임워크
- **FastAPI 0.111**: 비동기 웹 프레임워크
- **Uvicorn**: ASGI 서버
- **SSE (Server-Sent Events)**: 실시간 스트리밍

### 데이터베이스
- **PostgreSQL**: 사용자 데이터, 체크포인트, 산업 분류
- **Neo4j**: 기업 관계 지식 그래프
- **MongoDB**: 문서 저장소 (선택사항)
- **Redis**: 캐싱 및 세션 관리

### 데이터 분석
- **Pandas**: 데이터 처리
- **NumPy**: 수치 연산
- **Statsmodels**: 통계 모델링
- **Plotly**: 차트 시각화

### 외부 API
- **KIS (한국투자증권)**: 실시간 주가, 계좌 관리, 주문
- **DART (금융감독원)**: 재무제표, 기업 공시
- **OpenRouter/Perplexity**: 뉴스 검색 및 분석
- **YouTube Data API**: 투자 콘텐츠 분석

## 🤖 에이전트 시스템

### 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    SupervisorAgent                      │
│  - 사용자 질의 라우팅                                      │
│  - 종목 식별 (한국거래소 종목명 매칭)                        │
│  - 거래 액션 생성 및 승인 요청                              │
└────────────┬────────────────────────────────────────────┘
             │
     ┌───────┴───────┬───────────────┬───────────────┐
     │               │               │               │
┌────▼────┐   ┌─────▼─────┐   ┌────▼────┐   ┌─────▼─────┐
│ Market  │   │Fundamental│   │Technical│   │Investment │
│Analysis │   │ Analysis  │   │ Analysis│   │ Strategy  │
│ Agent   │   │  Agent    │   │  Agent  │   │   Agent   │
└─────────┘   └───────────┘   └─────────┘   └───────────┘
```

### SupervisorAgent (관리자)

**역할:**
- 사용자 질의를 분석하여 적절한 전문 에이전트로 라우팅
- 한국거래소 종목명 매칭을 통한 종목 코드 식별
- 최종 거래 액션 생성 및 사용자 승인 요청
- 각 에이전트의 분석 결과 통합

**주요 기능:**
- 종목명 → 종목코드 변환 (KIS 종목마스터 데이터 활용)
- 다중 에이전트 워크플로우 조율
- 거래 액션 JSON 생성 (매수/매도 제안)
- Neo4j 서브그래프 데이터 추출

### MarketAnalysisAgent (시장 분석)

**역할:** 뉴스, 리포트, 소셜 미디어 등을 분석하여 시장 심리 및 트렌드 파악

**도구:**

| 도구명 | 설명 | 데이터 소스 |
|-------|------|------------|
| `SearchNewsTool` | Perplexity API를 통한 최신 뉴스 검색 | OpenRouter/Perplexity |
| `SearchReportTool` | 증권사 리포트 및 투자 분석 자료 검색 | 웹 검색 |
| `YouTubeSearchTool` | YouTube 투자 콘텐츠 검색 및 자막 분석 | YouTube Data API |
| `ReportSentimentAnalysisTool` | 리포트 감정 분석 (긍정/중립/부정) | LLM 기반 분석 |
| `GraphQATool` | Neo4j 관계 그래프 기반 기업 분석 | Neo4j |

**분석 결과:**
- 시장 심리 (긍정적/부정적/중립적)
- 주요 뉴스 헤드라인
- 경쟁사 동향
- 산업 트렌드

### FundamentalAnalysisAgent (기본적 분석)

**역할:** DART 재무제표를 분석하여 기업의 재무 건전성 평가

**도구:**

| 도구명 | 설명 | 분석 지표 |
|-------|------|-----------|
| `AnalysisFinancialStatementTool` | DART API로 5개년 재무제표 수집 및 분석 | - 유동비율<br>- 부채비율<br>- 유보율<br>- ROE (자기자본이익률)<br>- 이자보상배율<br>- 매출액 증가율<br>- 영업이익률 |

**분석 결과:**
- 재무 건전성 평가 (안전/보통/위험)
- 수익성 지표
- 성장성 지표
- 유동성 분석
- 재무 리스크 평가

### TechnicalAnalysisAgent (기술적 분석)

**역할:** 주가 차트 및 기술적 지표를 분석하여 매매 타이밍 제안

**도구:**

| 도구명 | 설명 | 기능 |
|-------|------|------|
| `AnalysisStockTool` | KIS API를 통한 실시간 주가 및 시장 정보 조회 | - 현재가, 시가, 고가, 저가<br>- 거래량, 거래대금<br>- 52주 최고/최저<br>- PER, PBR, EPS |
| `PredictStockTool` | Prophet + ARIMA 앙상블 예측 모델 | - 단기 주가 예측 (1-30일)<br>- 신뢰 구간 제공<br>- 트렌드 분석 |
| `StockChartAnalysisTool` | 차트 이미지 분석 (GPT-4 Vision) | - 패턴 인식<br>- 지지/저항선 식별<br>- 매매 시그널 |

**분석 결과:**
- 기술적 매매 시그널 (매수/매도/관망)
- 주가 예측 및 신뢰 구간
- 차트 패턴 분석
- 거래량 분석

### InvestmentStrategyAgent (투자 전략)

**역할:** 계좌 정보와 투자 전략을 분석하여 포트폴리오 제안 및 주문 생성

**도구:**

| 도구명 | 설명 | 기능 |
|-------|------|------|
| `GetAccountInfoTool` | KIS API로 계좌 잔고 조회 | - 보유 종목 및 수량<br>- 평가금액 및 손익<br>- 예수금 (가용 현금)<br>- 총자산 |
| `InvestmentStrategySearchTool` | 투자 전략 웹 검색 | - 가치투자<br>- 성장투자<br>- 배당투자<br>- 모멘텀 전략 |

**분석 결과:**
- 투자 전략 제안
- 포트폴리오 비중 조정
- 매수/매도 수량 계산
- 리스크 관리 방안

## 📁 코드 구조

### 신규 구현 (src/)

현재 프로덕션 코드로, LangChain v1 `create_agent` 기반 전문 에이전트와 미들웨어(progress/tool 스트리밍)를 사용합니다.

- API I/O는 `/stock/chat` SSE 스트리밍을 유지
- LangGraph 체크포인트를 통한 대화 상태 관리
- 비동기 PostgreSQL 연동

### 레거시 보관 (legacy/)

이전 구현을 그대로 보관하여 참고 및 롤백 가능하도록 유지합니다.

## 🚀 빠른 시작

### 1. 사전 요구사항

- **Python**: 3.12 이상 (필수)
- **Docker & Docker Compose**: 컨테이너 환경 (권장)
- **uv**: Python 패키지 관리자 ([설치 가이드](https://github.com/astral-sh/uv))

### 2. 저장소 클론

```bash
git clone https://github.com/YOUR_ORG/stockelper-llm.git
cd stockelper-llm
```

### 3. 환경 변수 설정

```bash
cp env.example .env
# .env 파일을 열어 필요한 값 입력
```

### 4. Docker Compose 실행

```bash
# 기본 서비스 시작 (LLM Server + PostgreSQL)
docker-compose up -d

# LangFuse 포함 실행 (옵저버빌리티)
docker-compose --profile langfuse up -d

# Neo4j 포함 실행
docker-compose --profile neo4j up -d

# 로그 확인
docker-compose logs -f llm-server
```

### 5. 로컬 개발 환경

```bash
# 의존성 설치
uv sync

# 개발 서버 실행
uv run python src/main.py

# 또는 uvicorn 직접 실행
uv run uvicorn src.main:app --host 0.0.0.0 --port 21009 --reload
```

### 6. API 테스트

```bash
# 헬스 체크
curl http://localhost:21009/health

# 채팅 요청 (SSE 스트리밍)
curl -N -X POST http://localhost:21009/stock/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "thread_id": "test-thread-123",
    "message": "삼성전자 투자 전략 추천해줘"
  }'
```

## 🔌 API 엔드포인트

### POST /stock/chat

SSE 스트리밍 채팅 인터페이스 - 사용자 질의에 대한 AI 응답을 실시간으로 제공합니다.

**Request:**
```json
{
  "user_id": 1,
  "thread_id": "conversation_uuid",
  "message": "삼성전자 투자 전략 추천해줘",
  "human_feedback": null
}
```

**Parameters:**
- `user_id` (int, required): 사용자 ID (PostgreSQL `users` 테이블 참조)
- `thread_id` (string, required): 대화 스레드 UUID (LangGraph 체크포인트 식별자)
- `message` (string, required): 사용자 메시지
- `human_feedback` (object, optional): 거래 액션 승인/거부 피드백

**Response (SSE Stream):**

스트리밍 응답은 여러 이벤트 타입으로 구성됩니다:

1. **Progress 이벤트** - 에이전트 진행 상태
```json
{
  "type": "progress",
  "step": "MarketAnalysisAgent",
  "status": "start"
}
```

2. **Delta 이벤트** - 토큰 단위 응답
```json
{
  "type": "delta",
  "token": "삼성전자는"
}
```

3. **Final 이벤트** - 완전한 응답
```json
{
  "type": "final",
  "message": "삼성전자 투자 분석 결과...",
  "trading_action": {
    "action": "buy",
    "stock_code": "005930",
    "quantity": 10,
    "price": 70000
  },
  "subgraph": {
    "nodes": [...],
    "edges": [...]
  }
}
```

4. **Done 마커** - 스트림 종료
```
[DONE]
```

**에러 응답:**
```json
{
  "type": "error",
  "error": "에러 메시지"
}
```

### GET /health

서비스 헬스 체크 엔드포인트

**Response:**
```json
{
  "status": "healthy",
  "service": "stockelper-llm",
  "version": "0.1.0"
}
```

### POST /internal/backtesting/interpret (내부 API)

백테스트 완료 결과를 LLM으로 해석하고 `stockelper_web.public.backtesting` 테이블의 `analysis_*` 컬럼에 저장합니다.

**Request:**
```json
{
  "user_id": 1,
  "job_id": "backtesting-uuid-123",
  "force": false
}
```

**Parameters:**
- `user_id` (int, required): 사용자 ID
- `job_id` (string, required): 백테스트 작업 UUID
- `force` (bool, optional): 이미 해석된 결과 재해석 여부

**Response:**
```json
{
  "status": "success",
  "job_id": "backtesting-uuid-123",
  "analysis_md": "# 백테스트 분석 결과\n...",
  "analysis_json": {
    "summary": "...",
    "key_metrics": {...}
  }
}
```

**필수 환경 변수:**
- `STOCKELPER_BACKTESTING_URL`: 백테스팅 서비스 URL
- `OPENAI_API_KEY`: LLM 호출용 API 키

## ⚙️ 환경 변수

`env.example`를 `.env`로 복사한 뒤 값을 채워서 사용하세요. (`.env`는 커밋 금지)

### AI 서비스

```bash
# OpenAI API (GPT-4, GPT-5.1)
OPENAI_API_KEY=sk-proj-...

# (선택) 통일된 LLM 모델 지정
STOCKELPER_LLM_MODEL=gpt-5.1

# OpenRouter/Perplexity (뉴스 검색)
OPENROUTER_API_KEY=sk-or-...

# 금융감독원 DART API
OPEN_DART_API_KEY=your_dart_api_key

# YouTube Data API
YOUTUBE_API_KEY=your_youtube_api_key
```

### 한국투자증권 (KIS)

```bash
# 사용자별 kis_app_key/kis_app_secret/account_no/kis_access_token은
# stockelper_web.users 테이블에서 user_id로 조회/갱신합니다.

# KIS API Base URL (모의투자 기본값)
KIS_BASE_URL=https://openapivts.koreainvestment.com:29443

# 실전투자 URL (운영 환경)
# KIS_BASE_URL=https://openapi.koreainvestment.com:9443

# 거래 ID (모의/실전 전환 시 변경)
KIS_TR_ID_BALANCE=VTTC8434R      # 잔고 조회
KIS_TR_ID_ORDER_BUY=VTTC0802U    # 매수 주문
KIS_TR_ID_ORDER_SELL=VTTC0011U   # 매도 주문

# 종목 마스터 데이터
KIS_STOCK_MASTER_TIMEOUT=30
```

### 데이터베이스

```bash
# PostgreSQL - stockelper_web DB (사용자 데이터)
DATABASE_URL=postgresql://user:pass@host:5432/stockelper_web

# (선택) AsyncPG URL - 미지정 시 DATABASE_URL에서 자동 변환
ASYNC_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/stockelper_web

# LangGraph 체크포인트 DB (선택 - 미지정 시 stockelper_web 사용)
CHECKPOINT_DATABASE_URI=postgresql://user:pass@host:5432/checkpoint

# KSIC 산업 분류 DB (선택)
DATABASE_URL_KSIC=postgresql://user:pass@host:5432/ksic
ASYNC_DATABASE_URL_KSIC=postgresql+asyncpg://user:pass@host:5432/ksic

# 스키마/테이블 설정
STOCKELPER_WEB_SCHEMA=public
STOCKELPER_BACKTESTING_TABLE=backtesting
```

### Neo4j (선택)

```bash
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

### Redis

```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_AUTH=password
```

### LangFuse (선택사항 - 옵저버빌리티)

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:21003
```

### 서비스 설정

```bash
# 서버 설정
HOST=0.0.0.0
PORT=21009
DEBUG=false

# 서비스 모드 ("chat" 또는 "all")
STOCKELPER_SERVICE=chat

# 요청 타임아웃 (초)
REQUESTS_TIMEOUT=300

# 디버그 에러 출력
DEBUG_ERRORS=false

# 백테스팅 서비스 URL (필수)
STOCKELPER_BACKTESTING_URL=http://backtesting-server:21007

# 포트폴리오 추천 서비스 URL (선택)
STOCKELPER_PORTFOLIO_URL=http://portfolio-server:21008
PORTFOLIO_REQUESTS_TIMEOUT=300

# 백테스트 해석 설정
STOCKELPER_BACKTESTING_ANALYSIS_MODEL=gpt-4
BACKTEST_ANALYSIS_HTTP_TIMEOUT=60
```

## 🐳 Docker 배포

### Docker Compose를 이용한 배포 (권장)

```bash
# 모든 서비스 시작 (LLM Server만)
docker-compose up -d

# 데이터베이스 포함 시작
docker-compose --profile db up -d

# LangFuse 포함 시작
docker-compose --profile langfuse up -d

# Neo4j 포함 시작
docker-compose --profile neo4j up -d

# 모든 프로필 포함
docker-compose --profile db --profile langfuse --profile neo4j up -d

# 로그 확인
docker-compose logs -f llm-server

# 서비스 중지
docker-compose down

# 볼륨 포함 완전 삭제
docker-compose down -v
```

### 서비스 포트

| 서비스 | 포트 | 설명 |
|--------|------|------|
| LLM Server | 21009 | FastAPI 서버 |
| PostgreSQL | 5432 | 데이터베이스 |
| Redis | 6379 | 캐시 서버 |
| Neo4j Browser | 7474 | 웹 인터페이스 |
| Neo4j Bolt | 7687 | 드라이버 연결 |
| LangFuse | 21003 | 옵저버빌리티 대시보드 |

### 커스텀 Docker 이미지 빌드

```bash
# 이미지 빌드
docker build -t stockelper-llm-server:latest .

# 컨테이너 실행
docker run -d \
  --name stockelper-llm \
  --env-file .env \
  -p 21009:21009 \
  stockelper-llm-server:latest

# 로그 확인
docker logs -f stockelper-llm
```

### 프로덕션 배포 체크리스트

- [ ] `.env` 파일에 모든 필수 환경 변수 설정
- [ ] KIS API 실전투자 URL 및 TR ID 확인
- [ ] PostgreSQL 데이터베이스 백업 설정
- [ ] Redis 인증 비밀번호 설정
- [ ] Neo4j 비밀번호 변경
- [ ] LangFuse 추적 설정 (선택)
- [ ] Docker 네트워크 설정 (`stockelper` 네트워크)
- [ ] 로그 로테이션 설정
- [ ] 헬스 체크 및 모니터링 알람 설정

## 프로젝트 구조

```
stockelper-llm/
├── src/                              # 신규 구현 (프로덕션)
│   ├── main.py                       # 애플리케이션 진입점
│   └── stockelper_llm/
│       ├── __init__.py
│       ├── webapp.py                 # FastAPI 앱 설정
│       ├── multi_agent.py            # 다중 에이전트 그래프
│       ├── agents/                   # 에이전트 구현
│       │   ├── supervisor.py         # SupervisorAgent
│       │   ├── specialists.py        # 전문 에이전트들
│       │   ├── backtesting_request_agent.py  # 백테스팅 에이전트
│       │   ├── progress_middleware.py        # 진행 상태 미들웨어
│       │   └── tool_error_middleware.py      # 도구 에러 핸들링
│       ├── routers/                  # API 라우터
│       │   ├── stock.py              # /stock/chat 엔드포인트
│       │   ├── backtesting.py        # /internal/backtesting 엔드포인트
│       │   ├── models.py             # Pydantic 모델
│       │   └── base.py               # 기본 라우터
│       ├── integrations/             # 외부 통합
│       │   ├── neo4j_subgraph.py     # Neo4j 그래프 추출
│       │   ├── kis_client.py         # KIS API 클라이언트
│       │   ├── dart_client.py        # DART API 클라이언트
│       │   └── stock_master.py       # 종목 마스터 관리
│       └── core/                     # 핵심 유틸리티
│           ├── db_urls.py            # DB URL 파싱
│           ├── json_safety.py        # JSON 안전 처리
│           └── langchain_compat.py   # LangChain 호환성
├── legacy/                           # 레거시 보관
│   └── (이전 구현 전체)
├── tests/                            # 테스트 코드
├── docs/                             # 문서
├── assets/                           # 에셋 파일
├── scripts/                          # 배포 스크립트
├── docker-compose.yml                # Docker Compose 설정
├── cloud.docker-compose.yml          # 클라우드 배포용
├── Dockerfile                        # Docker 이미지 빌드
├── pyproject.toml                    # 프로젝트 메타데이터
├── uv.lock                           # 의존성 잠금 파일
├── env.example                       # 환경 변수 예시
├── requirements.txt                  # Python 의존성
├── init-multiple-db.sh               # PostgreSQL 다중 DB 초기화
├── .pre-commit-config.yaml           # Pre-commit 훅
└── README.md
```

## 🗄️ 데이터베이스

### PostgreSQL (3개 데이터베이스)

#### 1. stockelper_web

사용자 및 서비스 데이터를 저장하는 메인 데이터베이스

**주요 테이블:**

```sql
-- 사용자 정보 (KIS 자격증명 포함)
CREATE TABLE public.users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  nickname VARCHAR(255) UNIQUE NOT NULL,
  password VARCHAR(255) NOT NULL,
  investor_type VARCHAR(50) DEFAULT '안정형',

  -- KIS API 자격증명
  kis_app_key VARCHAR(255) NOT NULL,
  kis_app_secret VARCHAR(255) NOT NULL,
  kis_access_token TEXT,
  account_no VARCHAR(50) NOT NULL,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 대화 이력
CREATE TABLE public.conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id INTEGER REFERENCES users(id),
  title VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  last_active TIMESTAMP DEFAULT NOW()
);

-- 채팅 메시지
CREATE TABLE public.chats (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  message_id VARCHAR(255) NOT NULL,
  role VARCHAR(50) NOT NULL,
  content TEXT NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  subgraph_data JSONB,
  trading_action_data JSONB,
  error_message TEXT,
  human_feedback_response BOOLEAN,
  job_id VARCHAR(255),
  created_at TIMESTAMP DEFAULT NOW()
);

-- 백테스팅 결과
CREATE TABLE public.backtesting (
  id VARCHAR(255) PRIMARY KEY,
  job_id VARCHAR(255) UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  request_source VARCHAR(50) DEFAULT 'llm',
  status VARCHAR(50) NOT NULL,
  input_json JSONB DEFAULT '{}',
  output_json JSONB DEFAULT '{}',
  result_file_path TEXT,
  report_file_path TEXT,
  error_message TEXT,

  -- LLM 해석 결과
  analysis_status VARCHAR(50) DEFAULT 'pending',
  analysis_md TEXT,
  analysis_json JSONB DEFAULT '{}',
  analysis_model VARCHAR(100),
  analysis_prompt_version VARCHAR(50),
  analysis_error_message TEXT,
  analysis_started_at TIMESTAMPTZ,
  analysis_completed_at TIMESTAMPTZ,
  analysis_elapsed_seconds FLOAT,

  elapsed_seconds FLOAT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_backtesting_analysis_status ON public.backtesting(analysis_status, created_at DESC);
CREATE INDEX idx_backtesting_status ON public.backtesting(status, created_at DESC);
CREATE INDEX idx_backtesting_user ON public.backtesting(user_id, created_at DESC);
```

#### 2. checkpoint

LangGraph 상태 체크포인트를 저장하는 데이터베이스

**주요 테이블:**
- `checkpoints`: 에이전트 실행 상태 스냅샷
- `checkpoint_writes`: 체크포인트 쓰기 로그

#### 3. ksic

한국 표준 산업 분류 코드를 저장하는 데이터베이스

**주요 테이블:**
- `ksic_codes`: 산업 분류 코드 및 설명

### Neo4j (선택)

기업 관계 지식 그래프

**주요 노드:**
- `Company`: 상장 기업
- `StockPrice`: 주가 스냅샷
- `Event`: 기업 이벤트
- `Industry`: 산업 분류

**주요 관계:**
- `COMPETES_WITH`: 경쟁사 관계
- `BELONGS_TO`: 산업 소속
- `HAS_SNAPSHOT`: 주가 데이터
- `AFFECTED_BY`: 이벤트 영향

### MongoDB (선택)

문서 저장소 (현재 미사용)

### Redis

캐싱 및 세션 관리
- KIS 토큰 캐싱
- API 응답 캐싱
- 레이트 리밋 카운터

## 개발 가이드

### 로컬 개발 환경 설정

```bash
# 1. 저장소 클론
git clone https://github.com/YOUR_ORG/stockelper-llm.git
cd stockelper-llm

# 2. 의존성 설치
uv sync --dev

# 3. 환경 변수 설정
cp env.example .env
# .env 파일 편집

# 4. 데이터베이스 준비 (Docker 사용)
docker-compose --profile db up -d

# 5. 개발 서버 실행
uv run python src/main.py
```

### 새로운 도구(Tool) 추가

1. `src/stockelper_llm/integrations/`에 도구 클래스 생성
2. `@tool` 데코레이터로 LangChain 도구 정의
3. 에이전트에 도구 등록 (`specialists.py` 또는 `supervisor.py`)

```python
from langchain.tools import tool
from typing import Dict, Any

@tool
def my_new_tool(query: str) -> Dict[str, Any]:
    """새로운 도구 설명 (LLM에게 제공됨)

    Args:
        query: 검색 쿼리

    Returns:
        분석 결과 딕셔너리
    """
    # 도구 로직 구현
    result = perform_analysis(query)
    return {"status": "success", "data": result}
```

### 새로운 에이전트 추가

1. `src/stockelper_llm/agents/specialists.py`에 에이전트 함수 추가
2. 도구 리스트 및 시스템 프롬프트 정의
3. `multi_agent.py`의 그래프에 노드 추가

```python
def create_my_agent(llm):
    """새로운 에이전트 생성"""
    tools = [my_new_tool, other_tool]

    system_prompt = """당신은 {역할} 전문가입니다.

    주요 책임:
    - 책임 1
    - 책임 2
    """

    return create_agent(llm, tools, system_prompt)
```

### 테스트 실행

```bash
# 전체 테스트
uv run pytest

# 커버리지 포함
uv run pytest --cov=src/stockelper_llm --cov-report=html

# 특정 테스트 파일
uv run pytest tests/test_agents.py -v

# 통합 테스트 (DB 필요)
uv run pytest tests/integration/ -v
```

### 코드 품질 관리

```bash
# Black 포맷팅
uv run black src/ tests/

# isort import 정렬
uv run isort src/ tests/

# flake8 린트
uv run flake8 src/ tests/

# mypy 타입 체크
uv run mypy src/

# pre-commit 훅 설치
pre-commit install

# 모든 파일에 pre-commit 실행
pre-commit run --all-files
```

## 문제 해결

### 1. KIS API 토큰 만료

**증상**: `401 Unauthorized` 또는 토큰 만료 에러

**해결책**:
```bash
# users 테이블의 kis_access_token이 자동으로 갱신됩니다.
# 수동으로 갱신하려면:
# 1. KIS API 포털에서 새 토큰 발급
# 2. PostgreSQL users 테이블 업데이트
UPDATE users SET kis_access_token = 'new_token' WHERE id = 1;
```

### 2. PostgreSQL 연결 실패

**증상**: `psycopg.OperationalError: connection failed`

**해결책**:
```bash
# 데이터베이스 상태 확인
docker-compose ps

# PostgreSQL 로그 확인
docker-compose logs db

# 연결 문자열 확인
echo $DATABASE_URL

# 데이터베이스 재시작
docker-compose restart db
```

### 3. Neo4j 연결 실패

**증상**: `ServiceUnavailable: Unable to connect to neo4j://...`

**해결책**:
```bash
# Neo4j 서비스 시작
docker-compose --profile neo4j up -d

# Neo4j 로그 확인
docker-compose logs neo4j

# 브라우저에서 확인
open http://localhost:7474
```

### 4. LangChain 버전 호환성

**증상**: `AttributeError` 또는 import 에러

**해결책**:
```bash
# 의존성 재설치
uv sync --force

# 특정 버전 확인
uv pip list | grep langchain

# 캐시 클리어
uv cache clean
```

### 5. SSE 스트리밍 끊김

**증상**: 응답이 중간에 끊기거나 타임아웃

**해결책**:
```bash
# 타임아웃 증가 (.env 파일)
REQUESTS_TIMEOUT=600

# Nginx/프록시 사용 시 버퍼링 비활성화
# nginx.conf
proxy_buffering off;
proxy_cache off;
```

### 6. 메모리 부족

**증상**: `MemoryError` 또는 OOM killer

**해결책**:
```bash
# Docker 메모리 할당 증가
# docker-compose.yml
services:
  llm-server:
    deploy:
      resources:
        limits:
          memory: 4G

# Prophet 모델 캐싱 비활성화
# src/stockelper_llm/integrations/stock_predictor.py
# 예측 모델의 캐시 크기 조정
```

### 7. DART API 속도 제한

**증상**: `429 Too Many Requests`

**해결책**:
- DART API는 일일 10,000건 제한
- 요청 간격을 두고 호출
- 캐싱 활용 (Redis)

## 보안

### API 키 관리

- 모든 API 키는 환경 변수로 관리
- `.env` 파일은 절대 Git에 커밋하지 않음
- 프로덕션에서는 Secrets Manager 사용 권장

### KIS 토큰 보안

- 토큰은 PostgreSQL에 암호화 저장 (권장)
- 자동 갱신 메커니즘 구현
- 만료 시간 추적

### 데이터베이스 보안

```bash
# PostgreSQL 비밀번호 변경
docker exec -it stockelper-postgres-llm psql -U postgres
\password postgres

# Neo4j 비밀번호 변경
docker exec -it stockelper-neo4j cypher-shell
:server change-password
```

## 성능 최적화

### 1. 응답 속도 개선

- Redis 캐싱 활용
- 병렬 도구 호출 (LangGraph 자동 처리)
- 불필요한 도구 호출 최소화

### 2. 메모리 최적화

- LangGraph 체크포인트 정리 (오래된 대화)
- Prophet 모델 캐시 크기 제한
- 배치 처리 크기 조정

### 3. 데이터베이스 최적화

```sql
-- 인덱스 추가
CREATE INDEX idx_chats_conversation ON chats(conversation_id, timestamp);
CREATE INDEX idx_users_email ON users(email);

-- 쿼리 성능 분석
EXPLAIN ANALYZE SELECT * FROM chats WHERE conversation_id = 'uuid';
```

## 모니터링

### LangFuse 대시보드

```bash
# LangFuse 시작
docker-compose --profile langfuse up -d

# 브라우저에서 접속
open http://localhost:21003
```

**주요 메트릭:**
- 에이전트별 응답 시간
- 도구 호출 빈도
- LLM 토큰 사용량
- 에러 발생률

### 로그 모니터링

```bash
# 실시간 로그
docker-compose logs -f llm-server

# 에러 로그만 필터링
docker-compose logs llm-server | grep ERROR

# 특정 기간 로그
docker-compose logs --since 1h llm-server
```

## 로드맵

- [ ] 다국어 지원 (영어, 일본어)
- [ ] 음성 인터페이스 통합
- [ ] 백테스팅 전략 자동 생성
- [ ] 포트폴리오 리밸런싱 자동화
- [ ] 리스크 관리 에이전트 추가
- [ ] 해외 주식 시장 지원
- [ ] 모바일 앱 연동
- [ ] Slack/Discord 봇 통합

## 📄 라이선스

이 프로젝트는 MIT 라이선스에 따라 제공됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 👨‍💻 기여

Issues 및 Pull Requests를 환영합니다!

**기여 가이드:**
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📞 문의

- **Issues**: [GitHub Issues](https://github.com/YOUR_ORG/stockelper-llm/issues)
- **Discussions**: [GitHub Discussions](https://github.com/YOUR_ORG/stockelper-llm/discussions)
- **팀 연락처**: [내부 연락처 정보]

---

❤️ Stockelper-Lab 팀이 만들었습니다
