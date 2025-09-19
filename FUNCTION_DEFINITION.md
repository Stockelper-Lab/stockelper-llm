# Stockelper AI 챗봇 기능정의서

## 📊 기능 계층 구조 (Function Hierarchy)

### L1: 시스템 레벨 기능 (System Level Functions)

| 기능 ID | 기능명 | 설명 | 우선순위 | 상태 |
|---------|--------|------|----------|------|
| F1.0 | 다중 에이전트 시스템 | LangGraph 기반 6개 전문 에이전트 협업 시스템 | 높음 | 구현완료 |
| F2.0 | 실시간 스트리밍 | SSE 기반 실시간 진행상황 및 결과 전송 | 높음 | 구현완료 |
| F3.0 | 데이터 통합 시스템 | 4개 데이터베이스 연동 및 외부 API 통합 | 높음 | 구현완료 |
| F4.0 | 거래 실행 시스템 | KIS API 연동 실제 주식 거래 시스템 | 높음 | 구현완료 |
| F5.0 | 보안 및 인증 | 사용자 인증, API 키 관리, 거래 승인 | 높음 | 구현완료 |

---

### L2: 에이전트 레벨 기능 (Agent Level Functions)

#### F1.1 SupervisorAgent (관리자 에이전트)

| 기능 ID | 기능명 | 입력 | 출력 | 처리시간 | 의존성 |
|---------|--------|------|------|----------|--------|
| F1.1.1 | 질문 분석 및 라우팅 | 사용자 질문 텍스트 | 에이전트 선택 결과 | 1-2초 | OpenAI GPT-4o-mini |
| F1.1.2 | 주식 정보 추출 | 자연어 질문 | 주식명, 주식코드 | 2-3초 | FinanceDataReader, Neo4j |
| F1.1.3 | 에이전트 조율 | 에이전트 메시지 리스트 | 병렬 실행 결과 | 5-30초 | 하위 에이전트들 |
| F1.1.4 | 거래 결정 | 투자 전략 결과 | 거래 액션 제안 | 2-3초 | InvestmentStrategyAgent |
| F1.1.5 | 결과 통합 | 다중 에이전트 결과 | 최종 응답 | 1-2초 | 모든 에이전트 |

#### F1.2 MarketAnalysisAgent (시장 분석 에이전트)

| 기능 ID | 기능명 | 입력 | 출력 | 처리시간 | 의존성 |
|---------|--------|------|------|----------|--------|
| F1.2.1 | 뉴스 검색 및 분석 | 주식명/키워드 | 관련 뉴스 요약 | 3-5초 | Perplexity API |
| F1.2.2 | 투자 리포트 검색 | 주식코드 | 전문가 리포트 | 2-3초 | MongoDB |
| F1.2.3 | 감정 분석 | 뉴스/리포트 텍스트 | 감정 점수 (-1~1) | 2-3초 | OpenAI GPT |
| F1.2.4 | YouTube 트렌드 분석 | 주식명 | 관련 영상 분석 | 4-6초 | YouTube API |
| F1.2.5 | 관계 분석 | 주식명 | 경쟁사/섹터 관계 | 1-2초 | Neo4j |

#### F1.3 FundamentalAnalysisAgent (기업 분석 에이전트)

| 기능 ID | 기능명 | 입력 | 출력 | 처리시간 | 의존성 |
|---------|--------|------|------|----------|--------|
| F1.3.1 | 재무제표 분석 | 주식코드, 기간 | 재무 지표 분석 | 5-10초 | DART API |
| F1.3.2 | 밸류에이션 계산 | 재무 데이터 | PER, PBR, DCF 등 | 3-5초 | 내부 계산 |
| F1.3.3 | 경쟁사 비교 | 주식코드 리스트 | 비교 분석 결과 | 5-8초 | DART API, Neo4j |
| F1.3.4 | 성장성 분석 | 과거 재무 데이터 | 성장률 트렌드 | 3-4초 | 내부 계산 |

#### F1.4 TechnicalAnalysisAgent (기술 분석 에이전트)

| 기능 ID | 기능명 | 입력 | 출력 | 처리시간 | 의존성 |
|---------|--------|------|------|----------|--------|
| F1.4.1 | 주식 정보 조회 | 주식코드 | 현재가, 거래량 등 | 2-3초 | KIS API |
| F1.4.2 | 차트 분석 | 주식코드, 기간 | 차트 패턴 분석 | 8-12초 | 차트 생성 + GPT-4V |
| F1.4.3 | 기술적 지표 계산 | 주가 데이터 | RSI, MACD 등 | 2-3초 | 내부 계산 |
| F1.4.4 | 주가 예측 | 과거 주가 데이터 | 단기 예측 결과 | 10-15초 | Prophet, ARIMA |

#### F1.5 PortfolioAnalysisAgent (포트폴리오 분석 에이전트)

| 기능 ID | 기능명 | 입력 | 출력 | 처리시간 | 의존성 |
|---------|--------|------|------|----------|--------|
| F1.5.1 | 포트폴리오 최적화 | 보유 종목, 목표 수익률 | 최적 자산 배분 | 5-8초 | 내부 최적화 알고리즘 |
| F1.5.2 | 리스크 분석 | 포트폴리오 구성 | VaR, 샤프 비율 | 3-5초 | 내부 계산 |
| F1.5.3 | 성과 평가 | 포트폴리오 수익률 | 벤치마크 대비 성과 | 2-3초 | 시장 데이터 |
| F1.5.4 | 리밸런싱 제안 | 현재 vs 목표 배분 | 조정 방안 | 2-3초 | 내부 계산 |

#### F1.6 InvestmentStrategyAgent (투자 전략 에이전트)

| 기능 ID | 기능명 | 입력 | 출력 | 처리시간 | 의존성 |
|---------|--------|------|------|----------|--------|
| F1.6.1 | 계정 정보 조회 | 사용자 ID | 계좌 잔고, 보유 종목 | 2-3초 | KIS API, PostgreSQL |
| F1.6.2 | 투자 전략 검색 | 시장 상황, 목표 | 맞춤 전략 추천 | 4-6초 | Perplexity API |
| F1.6.3 | 리스크 프로파일링 | 사용자 정보 | 위험 성향 분석 | 2-3초 | 내부 알고리즘 |
| F1.6.4 | 거래 전략 수립 | 분석 결과 종합 | 구체적 매매 계획 | 3-5초 | 모든 분석 결과 |

---

### L3: 도구 레벨 기능 (Tool Level Functions)

#### F2.1 MarketAnalysisAgent Tools

| 도구 ID | 도구명 | 기능 설명 | 입력 파라미터 | 출력 형식 | API 의존성 |
|---------|--------|-----------|---------------|-----------|------------|
| T2.1.1 | SearchNewsTool | 실시간 뉴스 검색 | `query: str, count: int` | `{title, content, url, date}[]` | Perplexity |
| T2.1.2 | SearchReportTool | 투자 리포트 검색 | `stock_code: str, limit: int` | `{title, content, analyst, date}[]` | MongoDB |
| T2.1.3 | ReportSentimentAnalysisTool | 리포트 감정 분석 | `report_text: str` | `{sentiment: float, confidence: float}` | OpenAI |
| T2.1.4 | YouTubeSearchTool | YouTube 콘텐츠 검색 | `query: str, max_results: int` | `{title, description, url, views}[]` | YouTube API |
| T2.1.5 | GraphQATool | 지식그래프 질의 | `query: str, stock_name: str` | `{nodes: [], relationships: []}` | Neo4j |

#### F2.2 FundamentalAnalysisAgent Tools

| 도구 ID | 도구명 | 기능 설명 | 입력 파라미터 | 출력 형식 | API 의존성 |
|---------|--------|-----------|---------------|-----------|------------|
| T2.2.1 | AnalysisFinancialStatementTool | 재무제표 종합 분석 | `stock_code: str, years: int` | `{revenue, profit, ratios, growth}` | DART API |

#### F2.3 TechnicalAnalysisAgent Tools

| 도구 ID | 도구명 | 기능 설명 | 입력 파라미터 | 출력 형식 | API 의존성 |
|---------|--------|-----------|---------------|-----------|------------|
| T2.3.1 | AnalysisStockTool | 종합 주식 정보 분석 | `stock_code: str` | `{price, volume, indicators}` | KIS API |
| T2.3.2 | StockChartAnalysisTool | 차트 이미지 분석 | `stock_code: str, period: str` | `{chart_url, analysis, patterns}` | KIS API + GPT-4V |
| T2.3.3 | PredictStockTool | AI 주가 예측 | `stock_code: str, days: int` | `{predictions: [], confidence: float}` | Prophet/ARIMA |

#### F2.4 PortfolioAnalysisAgent Tools

| 도구 ID | 도구명 | 기능 설명 | 입력 파라미터 | 출력 형식 | API 의존성 |
|---------|--------|-----------|---------------|-----------|------------|
| T2.4.1 | PortfolioAnalysisTool | 포트폴리오 종합 분석 | `holdings: dict, target_return: float` | `{optimization, risk_metrics}` | 내부 알고리즘 |

#### F2.5 InvestmentStrategyAgent Tools

| 도구 ID | 도구명 | 기능 설명 | 입력 파라미터 | 출력 형식 | API 의존성 |
|---------|--------|-----------|---------------|-----------|------------|
| T2.5.1 | GetAccountInfoTool | 계정 정보 조회 | `user_id: int` | `{balance, holdings, history}` | KIS API |
| T2.5.2 | InvestmentStrategySearchTool | 투자 전략 검색 | `market_condition: str, goal: str` | `{strategies: [], recommendations: []}` | Perplexity |

---

## 📋 API 엔드포인트 명세

### F3.1 REST API Endpoints

| 엔드포인트 | 메서드 | 기능 | 입력 | 출력 | 응답시간 |
|------------|--------|------|------|------|----------|
| `/stock/chat` | POST | 챗봇 대화 | `ChatRequest` | SSE Stream | 5-60초 |
| `/health` | GET | 시스템 상태 확인 | - | `{status, timestamp}` | <1초 |
| `/` | GET | 기본 정보 | - | `{message, version}` | <1초 |

### F3.2 데이터 모델

#### ChatRequest Model
```json
{
  "user_id": "integer (required)",
  "thread_id": "string (required)", 
  "message": "string (required)",
  "human_feedback": "boolean (optional)"
}
```

#### SSE Response Models
```json
// Progress Response
{
  "type": "progress",
  "step": "string",
  "status": "start|end"
}

// Final Response  
{
  "type": "final",
  "message": "string",
  "subgraph": "object",
  "trading_action": "object|null"
}
```

---

## 🔧 시스템 구성 요소

### F4.1 데이터베이스 기능

| DB 유형 | 용도 | 주요 테이블/컬렉션 | 성능 요구사항 | 백업 주기 |
|---------|------|-------------------|---------------|-----------|
| PostgreSQL | 사용자 정보, 체크포인트 | `users`, `checkpoints` | 100 TPS | 일 1회 |
| Neo4j | 지식그래프 | `Company`, `Sector` | 50 QPS | 주 1회 |
| MongoDB | 문서 저장 | `reports`, `news` | 200 QPS | 일 1회 |
| Milvus | 벡터 검색 | `embeddings` | 1000 QPS | 주 1회 |

### F4.2 외부 API 연동

| API 서비스 | 용도 | 요청 한도 | 응답시간 | 에러 처리 |
|------------|------|-----------|----------|-----------|
| OpenAI GPT | LLM 추론 | 10,000 RPM | 2-5초 | 재시도 3회 |
| Perplexity | 웹 검색 | 1,000 RPD | 3-8초 | 대체 검색 |
| KIS API | 주식 데이터/거래 | 1,000 RPM | 1-3초 | 큐잉 처리 |
| DART API | 공시 정보 | 10,000 RPD | 2-5초 | 캐싱 활용 |
| YouTube API | 동영상 검색 | 10,000 RPD | 2-4초 | 선택적 실행 |

---

## 🚀 성능 및 확장성

### F5.1 성능 지표

| 지표 | 목표값 | 현재값 | 측정 방법 |
|------|--------|--------|----------|
| 응답 시간 (평균) | <30초 | 15-45초 | APM 모니터링 |
| 동시 사용자 | 100명 | 50명 | 부하 테스트 |
| 시스템 가용성 | 99.5% | 99.2% | 업타임 모니터링 |
| 에러율 | <1% | 0.5% | 로그 분석 |

### F5.2 확장성 계획

| 구성요소 | 현재 용량 | 확장 방안 | 예상 비용 |
|----------|-----------|-----------|----------|
| 웹 서버 | 1 인스턴스 | 로드밸런서 + 3 인스턴스 | +200% |
| 데이터베이스 | 단일 서버 | 읽기 복제본 추가 | +150% |
| AI 모델 | OpenAI API | 자체 모델 서버 | +300% |
| 캐싱 | 메모리 캐시 | Redis 클러스터 | +50% |

---

## 🔒 보안 및 컴플라이언스

### F6.1 보안 기능

| 보안 영역 | 구현 기능 | 보안 수준 | 검증 방법 |
|-----------|-----------|-----------|----------|
| 인증/인가 | JWT 토큰, 세션 관리 | 높음 | 침투 테스트 |
| 데이터 암호화 | AES-256, TLS 1.3 | 높음 | 보안 감사 |
| API 보안 | Rate Limiting, CORS | 중간 | 자동 스캔 |
| 거래 보안 | 2FA, 승인 워크플로우 | 높음 | 수동 검증 |

### F6.2 컴플라이언스

| 규정 | 적용 범위 | 준수 상태 | 검토 주기 |
|------|-----------|-----------|----------|
| 개인정보보호법 | 사용자 데이터 | 준수 | 분기별 |
| 자본시장법 | 투자 조언 | 부분 준수 | 월별 |
| 정보보안 관리체계 | 전체 시스템 | 준비 중 | 연간 |

---

## 📊 모니터링 및 운영

### F7.1 모니터링 지표

| 카테고리 | 지표명 | 임계값 | 알림 설정 |
|----------|--------|--------|----------|
| 시스템 | CPU 사용률 | >80% | Slack 알림 |
| 시스템 | 메모리 사용률 | >85% | 이메일 알림 |
| 애플리케이션 | 응답 시간 | >60초 | SMS 알림 |
| 비즈니스 | 일일 거래 건수 | <10건 | 대시보드 표시 |
| 비즈니스 | 에러율 | >2% | 즉시 알림 |

### F7.2 운영 절차

| 절차 | 주기 | 담당자 | 체크리스트 |
|------|------|--------|------------|
| 시스템 점검 | 일간 | DevOps | 로그 확인, 성능 지표 |
| 데이터 백업 | 일간 | DBA | 백업 완료 확인 |
| 보안 점검 | 주간 | 보안팀 | 취약점 스캔 |
| 성능 최적화 | 월간 | 개발팀 | 쿼리 최적화, 캐시 정리 |

---

*본 기능정의서는 Stockelper AI 챗봇의 상세 기능 명세를 계층적으로 정리한 문서입니다.*
