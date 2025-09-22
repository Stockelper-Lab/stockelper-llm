<div align="center">
  <img src="assets/bull.png" alt="Stockelper" width="100%"/>
</div>

# Stockelper - AI-Powered Stock Investment Platform

**Stockelper**는 AI 기반의 종합 주식 투자 플랫폼으로, 초보부터 전문가까지 모든 투자자를 위한 지능형 투자 어시스턴트입니다. LangGraph 기반의 다중 에이전트 시스템과 자동화된 데이터 파이프라인을 통해 실시간 시장 분석, 기업 분석, 투자 전략 수립을 지원합니다.

## 🚀 주요 특징

- **🤖 다중 AI 에이전트**: 시장분석, 기업분석, 기술분석, 리스크관리 전문 에이전트
- **📊 실시간 데이터**: Airflow 기반 자동화된 뉴스/리포트 크롤링 파이프라인
- **🔍 지능형 검색**: Neo4j 지식그래프와 벡터 데이터베이스 기반 정보 검색
- **📈 포트폴리오 관리**: 실시간 포트폴리오 추적 및 리스크 분석
- **🌐 오픈소스**: 완전한 오픈소스로 누구나 배포 및 커스터마이징 가능

## 🏗️ 시스템 아키텍처

Stockelper는 마이크로서비스 아키텍처를 기반으로 구성되어 있습니다:

![Stockelper Architecture](assets/architecture.png)

### 핵심 컴포넌트

1. **LLM Server** (`llm-server/`): LangGraph 기반 다중 에이전트 시스템
2. **Data Pipeline**: Airflow 기반 자동화된 데이터 수집 및 처리
3. **Vector Database**: 임베딩 기반 지능형 검색 시스템
4. **Knowledge Graph**: Neo4j 기반 관계형 데이터 분석

## 📋 태스크 흐름도

사용자 질문이 다양한 에이전트를 통해 처리되는 과정:

![Task Flow](assets/task_flow.png)

## 👤 사용자 흐름도

### 기본 사용자 흐름
![User Flow 1](assets/user_flow1.png)

### 상세 사용자 흐름
![User Flow 2](assets/user_flow2.png)

## 🤖 AI 에이전트 시스템

### 1. SupervisorAgent (관리자 에이전트)
- 사용자 질문 분석 및 작업 할당
- 에이전트 간 협업 조율
- 최종 응답 생성 및 품질 관리
- 실제 거래 실행 결정

### 2. MarketAnalysisAgent (시장 분석 에이전트)
- 실시간 시장 동향 분석
- 뉴스 감성 분석 및 요약
- 섹터별 시장 분석
- 유튜브/소셜미디어 트렌드 분석
- 지식그래프 기반 관계 분석

### 3. FundamentalAnalysisAgent (기업 분석 에이전트)
- 재무제표 심층 분석
- 기업 가치 평가 (DCF, PER, PBR 등)
- 경쟁사 비교 분석
- ESG 및 지배구조 분석
- DART 공시 정보 분석

### 4. TechnicalAnalysisAgent (기술 분석 에이전트)
- 차트 패턴 인식 및 분석
- 기술적 지표 계산 (RSI, MACD, 볼린저밴드 등)
- 지지/저항선 분석
- 거래량 분석
- 매매 타이밍 추천

### 5. PortfolioAnalysisAgent (포트폴리오 분석 에이전트)
- 포트폴리오 구성 최적화
- 리스크 분산 분석
- 수익률 시뮬레이션

### 6. InvestmentStrategyAgent (투자 전략 에이전트)
- 개인화된 투자 전략 수립
- 리스크 프로파일 기반 추천
- 장기/단기 투자 계획
- 세금 최적화 전략
- KIS API 연동 실제 거래 실행

## 🤖 AI 에이전트 도구
### MarketAnalysisAgent Tools
- SearchNewsTool: Perplexity를 사용하여 관련 뉴스를 검색합니다.
- SearchReportTool: MongoDB에서 종목 관련 투자 리포트를 검색합니다.
- ReportSentimentAnalysisTool: LLM을 통해 투자 리포트의 감정을 분석합니다.
- YouTubeSearchTool: YouTube의 주식 관련 콘텐츠를 검색합니다.
- GraphQATool: Neo4j에서 인물, 경쟁사등의 관계 데이터를 검색합니다.
### FundamentalAnalysisAgent Tools
- AnalysisFinancialStatementTool: Dart에서 회사 재무제표를 분석합니다.
### TechnicalAnalysisAgent Tools
- AnalysisStockTool: kis에서 종합적인 주식 정보 검색합니다.
- StockChartAnalysisTool: 차트이미지를 생성하고 multi-modal로 분석합니다
- PredictStockTool: Prophet과 ARIMA를 활용해 주가 변동을 예측합니다.
### PortfolioAnalysisAgent Tools
- PortfolioAnalysisTool: 포트폴리오 성능을 분석하고, 자산 배분을 최적화하며, 위험을 평가합니다.
### InvestmentStrategyAgent Tools
- GetAccountInfoTool: 사용자 계정 정보를 조회합니다.
- InvestmentStrategySearchTool: Perplexity를 사용하여 관련 투자 전략을 검색합니다.

## 🚀 빠른 시작

### Docker Compose 실행
```bash
docker network create stockelper
docker compose up --build -d
```

> 참고: Docker 이미지 내부에서 Python 의존성 설치는 pip가 아닌 Astral uv로 수행됩니다. 사용자는 별도 조치 없이 위 명령만 실행하면 됩니다.

### 모의투자 계정 업로드
```bash
docker compose exec llm-server uv run python src/upload_user.py
```

### 프론트엔드 실행 (테스트용)
```bash
streamlit run src/frontend/streamlit_app.py
```

## 📁 프로젝트 구조

```
Stockelper/
├── 📁 src/                      # 소스 코드
│   ├── __init__.py
│   ├── main.py                  # 메인 FastAPI 애플리케이션
│   ├── upload_user.py           # 사용자 모의 투자 계정 업로드
│   ├── 📁 multi_agent/          # 멀티 에이전트 시스템
│   │   ├── __init__.py          # 멀티 에이전트 객체 생성
│   │   ├── utils.py             # postgresql users table schema, kis 관련 함수, 유틸리티 함수
│   │   ├── 📁 base/             # Agent base class
│   │   │   ├── __init__.py
│   │   │   └── analysis_agent.py    # Anaysis agent base class
│   │   ├── 📁 supervisor_agent/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py             # SupervisorAgent Workflow
│   │   │   └── prompt.py            # prompt
│   │   ├── 📁 market_analysis_agent/  #  MarketAnalysisAgent
│   │   │   ├── __init__.py          # object instantiation
│   │   │   ├── agent.py             # workflow
│   │   │   ├── prompt.py            # prompt
│   │   │   └── 📁 tools/
│   │   │       ├── __init__.py
│   │   │       ├── graph_qa.py      # 지식 그래프 검색 도구
│   │   │       ├── news.py          # 뉴스 검색 도구
│   │   │       ├── report.py        # 투자 리포트 검색 도구
│   │   │       ├── sentiment.py     # 리포트 감정 분석 도구
│   │   │       └── youtube_tool.py  # YouTube 검색 도구
│   │   ├── 📁 fundamental_analysis_agent/   # FundamentalAnalysisAgent
│   │   │   ├── __init__.py          # object instantiation
│   │   │   ├── agent.py             # workflow
│   │   │   ├── prompt.py            # prompt
│   │   │   └── 📁 tools/
│   │   │       ├── __init__.py
│   │   │       └── dart.py          # 재무제표 분석 도구
│   │   ├── 📁 technical_analysis_agent/     # TechnicalAnalysisAgent
│   │   │   ├── __init__.py          # object instantiation
│   │   │   ├── agent.py             # workflow
│   │   │   ├── prompt.py            # prompt
│   │   │   └── 📁 tools/
│   │   │       ├── __init__.py
│   │   │       ├── chart_analysis_tool.py   # 주식 차트 이미지 분석 도구
│   │   │       └── stock.py         # 주식 정보 및 기술적 분석 도구
│   │   ├── 📁 portfolio_analysis_agent/     # PortfolioAnalysisAgent
│   │   │   ├── __init__.py          # object instantiation
│   │   │   ├── agent.py             # workflow
│   │   │   ├── prompt.py            # prompt
│   │   │   └── 📁 tools/
│   │   │       ├── __init__.py
│   │   │       └── portfolio.py     # 포트폴리오 분석 도구
│   │   └── 📁 investment_strategy_agent/    # InvestmentStrategyAgent
│   │       ├── __init__.py          # object instantiation
│   │       ├── agent.py             # workflow
│   │       ├── prompt.py            # prompt
│   │       └── 📁 tools/
│   │           ├── __init__.py
│   │           ├── account.py       # 계정 정보 조회 도구
│   │           └── search.py        # 투자 전략 검색 도구
│   ├── 📁 routers/                  # API 라우터
│   │   ├── __init__.py              # 라우터 내보내기
│   │   ├── base.py                  # 기본 엔드포인트
│   │   ├── models.py                # API 요청/응답 모델
│   │   └── stock.py                 # 주식 관련 엔드포인트
│   └── 📁 frontend/                 # 프론트엔드
│       ├── __init__.py
│       └── streamlit_app.py         # Streamlit 웹 인터페이스
├── .dockerignore
├── .env.example                     # api key
├── .gitignore
├── docker-compose.yml               # Docker Compose 설정
├── Dockerfile                       # Docker 이미지 설정
├── init-multiple-db.sh              # 데이터베이스 초기화 스크립트
├── LICENSE
├── README.md
├── requirements.txt                 # Python 의존성
└── 📁 assets                        # 문서 이미지 및 자료
```

## 🔧 기술 스택

### AI/ML
- **LangGraph**: 다중 에이전트 워크플로우
- **LangChain**: LLM 애플리케이션 프레임워크
- **OpenAI GPT**: 주요 언어 모델
- **Anthropic Claude**: 보조 언어 모델
- **HuggingFace**: 임베딩 모델

### 데이터베이스
- **PostgreSQL**: 사용자 데이터 및 체크포인트
- **Neo4j**: 지식 그래프
- **MongoDB**: 문서 저장소

### 인프라
- **Docker**: 컨테이너화
- **FastAPI**: API 서버
- **Apache Airflow**: 데이터 파이프라인
- **Langfuse**: AI 관찰성 및 모니터링

### 외부 API
- **KIS API**: 한국투자증권 거래 API
- **DART API**: 금융감독원 공시 시스템
- **FinanceDataReader**: 금융 데이터
- **Tavily**: 웹 검색
- **YouTube API**: 동영상 콘텐츠

## 🔑 필수 API 키 (.env)

### AI 서비스
- `OPENAI_API_KEY`: OpenAI GPT 모델
- `OPENROUTER_API_KEY`: perplexity

### 데이터 서비스
- `OPEN_DART_API_KEY`: 기업 재무제표
- `MONGO_URI`: 투자 리포트
- `YOUTUBE_API_KEY`: 유튜브 스크립트
- `NEO4J_URI`: Neo4j 데이터베이스
- `NEO4J_USER`: Neo4j 사용자명
- `NEO4J_PASSWORD`: Neo4j 비밀번호
- `KIS_APP_KEY`: 한국투자증권 앱 키
- `KIS_APP_SECRET`: 한국투자증권 앱 시크릿
- `KIS_ACCOUNT_NO`: 한국투자증권 가상 계좌번호

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 후원사

아래는 Stockelper 프로젝트를 지원해주시는 후원사 목록입니다.

<table>
  <tr>
    <td align="center" width="25%">
      <a href="#">
        <img src="assets/kis.png" alt="KIS" width="180"/>
      </a>
    </td>
    <td align="center" width="25%">
      <a href="#">
        <img src="assets/naver-cloud-platform.png.png" alt="Naver Cloud Platform" width="180"/>
      </a>
    </td>
    <td align="center" width="25%">
      <a href="#">
        <img src="assets/telepix.png" alt="Telepix" width="180"/>
      </a>
    </td>
    <td align="center" width="25%">
      <a href="#">
        <img src="assets/pseudolab.png" alt="PseudoLab" width="180"/>
      </a>
    </td>
  </tr>
</table>
