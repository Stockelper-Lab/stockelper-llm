# Stockelper LLM 챗봇 LangGraph 구조도

## 🔄 전체 시스템 LangGraph 구조

```mermaid
graph TB
    %% User Input
    User["사용자 입력"] --> FastAPI["FastAPI /stock/chat"]
    FastAPI --> MultiAgent["Multi-Agent System"]
    
    %% SupervisorAgent LangGraph
    MultiAgent --> SupervisorGraph{"SupervisorAgent StateGraph"}
    
    %% SupervisorAgent Nodes
    SupervisorGraph --> Start["START"]
    Start --> Supervisor["supervisor<br/>질문 분석 라우팅"]
    
    %% Supervisor Decision Logic
    Supervisor --> SupervisorDecision{"라우팅 결정"}
    SupervisorDecision -->|"직접 응답"| DirectResponse["직접 응답"]
    SupervisorDecision -->|"에이전트 실행"| ExecuteAgent["execute_agent"]
    SupervisorDecision -->|"거래 제안"| ExecuteTrading["execute_trading"]
    
    %% Agent Execution Flow
    ExecuteAgent --> ParallelAgents{"병렬 에이전트 실행"}
    ParallelAgents --> MA["MarketAnalysisAgent"]
    ParallelAgents --> FA["FundamentalAnalysisAgent"] 
    ParallelAgents --> TA["TechnicalAnalysisAgent"]
    ParallelAgents --> IA["InvestmentStrategyAgent"]
    
    %% Agent Results Back to Supervisor
    MA --> AgentResults["에이전트 결과 수집"]
    FA --> AgentResults
    TA --> AgentResults
    IA --> AgentResults
    
    AgentResults --> Supervisor
    
    %% Trading Flow
    ExecuteTrading --> HumanApproval["인간 승인<br/>interrupt()"]
    HumanApproval -->|"승인"| KISTrading["KIS API 거래 실행"]
    HumanApproval -->|"거부"| TradingCancel["거래 취소"]
    
    %% End States
    DirectResponse --> End["END"]
    KISTrading --> End
    TradingCancel --> End
    
    %% State Management
    StateBox["State Management<br/>messages 대화 히스토리<br/>agent_results 에이전트 결과<br/>trading_action 거래 액션<br/>stock_name code 주식 정보<br/>subgraph Neo4j 데이터"]
    
    SupervisorGraph -.-> StateBox
```

## 🤖 BaseAnalysisAgent 공통 구조

```mermaid
graph TB
    %% BaseAnalysisAgent Structure
    AgentStart["START"] --> Agent["agent<br/>LLM 추론 도구 선택"]
    
    Agent --> AgentDecision{"도구 실행 여부"}
    AgentDecision -->|"도구 실행 필요"| ExecuteTool["execute_tool"]
    AgentDecision -->|"응답 완료"| AgentEnd["END"]
    AgentDecision -->|"실행 한도 초과"| LimitExceeded["실행 한도 초과"]
    
    %% Tool Execution
    ExecuteTool --> ParallelTools{"병렬 도구 실행"}
    ParallelTools --> Tool1["Tool 1"]
    ParallelTools --> Tool2["Tool 2"]
    ParallelTools --> Tool3["Tool N"]
    
    Tool1 --> ToolResults["도구 결과 수집"]
    Tool2 --> ToolResults
    Tool3 --> ToolResults
    
    ToolResults --> Agent
    
    LimitExceeded --> AgentEnd
    
    %% SubState Management
    SubStateBox["SubState<br/>messages 에이전트 대화<br/>execute_tool_count 도구 실행 횟수"]
    
    Agent -.-> SubStateBox
    ExecuteTool -.-> SubStateBox
```

## 📊 MarketAnalysisAgent 상세 구조

```mermaid
graph TB
    %% MarketAnalysisAgent Specific Flow
    MAStart["MarketAnalysisAgent 시작"] --> MAAgent["시장 분석 에이전트"]
    
    MAAgent --> MATools{"도구 선택 병렬 실행"}
    
    %% Market Analysis Tools
    MATools --> SearchNews["SearchNewsTool<br/>Perplexity 뉴스 검색"]
    MATools --> SearchReport["SearchReportTool<br/>MongoDB 리포트 검색"]
    MATools --> YouTubeSearch["YouTubeSearchTool<br/>YouTube 콘텐츠 검색"]
    MATools --> SentimentAnalysis["ReportSentimentAnalysisTool<br/>감정 분석"]
    MATools --> GraphQA["GraphQATool<br/>Neo4j 관계 분석"]
    
    %% External API Calls
    SearchNews --> PerplexityAPI["Perplexity API"]
    SearchReport --> MongoDB["MongoDB"]
    YouTubeSearch --> YouTubeAPI["YouTube API"]
    SentimentAnalysis --> OpenAIAPI["OpenAI API"]
    GraphQA --> Neo4jDB["Neo4j"]
    
    %% Results Collection
    PerplexityAPI --> MAResults["시장 분석 결과"]
    MongoDB --> MAResults
    YouTubeAPI --> MAResults
    OpenAIAPI --> MAResults
    Neo4jDB --> MAResults
    
    MAResults --> MAAgent
    MAAgent --> MAEnd["MarketAnalysisAgent 완료"]
```

## 📈 TechnicalAnalysisAgent 상세 구조

```mermaid
graph TB
    %% TechnicalAnalysisAgent Specific Flow
    TAStart["TechnicalAnalysisAgent 시작"] --> TAAgent["기술 분석 에이전트"]
    
    TAAgent --> TATools{"도구 선택 병렬 실행"}
    
    %% Technical Analysis Tools
    TATools --> AnalysisStock["AnalysisStockTool<br/>종합 주식 정보"]
    TATools --> ChartAnalysis["StockChartAnalysisTool<br/>차트 이미지 분석"]
    TATools --> PredictStock["PredictStockTool<br/>AI 주가 예측"]
    
    %% External API and Processing
    AnalysisStock --> KISAPI["KIS API<br/>실시간 주가 데이터"]
    ChartAnalysis --> ChartGeneration["차트 생성"]
    ChartGeneration --> GPT4V["GPT-4V<br/>멀티모달 분석"]
    PredictStock --> MLModels["Prophet ARIMA<br/>예측 모델"]
    
    %% Results Collection
    KISAPI --> TAResults["기술 분석 결과"]
    GPT4V --> TAResults
    MLModels --> TAResults
    
    TAResults --> TAAgent
    TAAgent --> TAEnd["TechnicalAnalysisAgent 완료"]
```

## 💰 거래 실행 워크플로우

```mermaid
graph TB
    %% Trading Execution Flow
    TradingStart["🚀 거래 실행 시작"] --> InvestmentResult["📋 InvestmentStrategyAgent 결과"]
    
    InvestmentResult --> TradingDecision["🎯 거래 결정 생성<br/>GPT + TradingAction 모델"]
    
    TradingDecision --> TradingProposal["💡 거래 제안<br/>주식코드, 수량, 가격, 매매구분"]
    
    TradingProposal --> HumanInterrupt["⏸️ interrupt()<br/>인간 승인 대기"]
    
    HumanInterrupt --> ApprovalDecision{사용자 승인}
    
    ApprovalDecision -->|승인| AccountCheck["👤 계정 정보 확인<br/>PostgreSQL"]
    ApprovalDecision -->|거부| TradingCancel["❌ 거래 취소"]
    
    AccountCheck --> TokenCheck{액세스 토큰 확인}
    TokenCheck -->|토큰 없음| GetToken["🔑 KIS 액세스 토큰 발급"]
    TokenCheck -->|토큰 있음| ExecuteOrder["💱 KIS API 주문 실행"]
    
    GetToken --> ExecuteOrder
    
    ExecuteOrder --> OrderResult{주문 결과}
    OrderResult -->|성공| TradingSuccess["✅ 거래 성공"]
    OrderResult -->|토큰 만료| RefreshToken["🔄 토큰 갱신 후 재시도"]
    OrderResult -->|실패| TradingError["❌ 거래 실패"]
    
    RefreshToken --> ExecuteOrder
    
    TradingSuccess --> TradingEnd["🏁 거래 완료"]
    TradingCancel --> TradingEnd
    TradingError --> TradingEnd
```

## 🔄 스트리밍 및 상태 관리

```mermaid
graph TB
    %% Streaming and State Management
    StreamStart["🚀 스트리밍 시작"] --> SSEConnection["📡 SSE 연결 설정"]
    
    SSEConnection --> StateInit["📝 State 초기화<br/>messages, agent_results 등"]
    
    StateInit --> CheckpointerSetup["💾 PostgreSQL Checkpointer<br/>대화 상태 저장"]
    
    CheckpointerSetup --> StreamLoop{스트리밍 루프}
    
    %% Streaming Events
    StreamLoop --> ProgressEvent["📊 Progress Event<br/>{step: agent, status: start}"]
    StreamLoop --> CustomEvent["🔧 Custom Event<br/>도구 실행 상태"]
    StreamLoop --> ValuesEvent["📋 Values Event<br/>최종 상태 업데이트"]
    
    %% Event Processing
    ProgressEvent --> ClientUpdate["📱 클라이언트 업데이트"]
    CustomEvent --> ClientUpdate
    ValuesEvent --> FinalResponse["🏁 최종 응답<br/>{type: final, message: ...}"]
    
    ClientUpdate --> StreamLoop
    FinalResponse --> StreamEnd["📡 스트리밍 종료<br/>data: [DONE]"]
    
    %% State Persistence
    StateUpdate["💾 상태 업데이트"] --> PostgreSQLCheckpoint["(🐘 PostgreSQL<br/>Checkpoints)"]
    StreamLoop -.-> StateUpdate
```

## 🎯 에이전트 조율 및 병렬 처리

```mermaid
graph TB
    %% Agent Coordination and Parallel Processing
    CoordStart["🚀 에이전트 조율 시작"] --> RouterAnalysis["🎭 라우터 분석<br/>GPT + RouterList 모델"]
    
    RouterAnalysis --> AgentSelection["🎯 에이전트 선택<br/>1개 이상 에이전트"]
    
    AgentSelection --> ParallelExecution{병렬 실행 준비}
    
    %% Parallel Agent Execution
    ParallelExecution --> AsyncTasks["⚡ asyncio.gather()<br/>비동기 태스크 생성"]
    
    AsyncTasks --> Agent1Task["📊 MarketAnalysis Task"]
    AsyncTasks --> Agent2Task["📈 Fundamental Task"]
    AsyncTasks --> Agent3Task["📉 Technical Task"]
    AsyncTasks --> Agent4Task["🎯 Investment Task"]
    
    %% Individual Agent Streams
    Agent1Task --> Agent1Stream["📡 Agent1 스트리밍"]
    Agent2Task --> Agent2Stream["📡 Agent2 스트리밍"]
    Agent3Task --> Agent3Stream["📡 Agent3 스트리밍"]
    Agent4Task --> Agent4Stream["📡 Agent4 스트리밍"]
    
    %% Results Aggregation
    Agent1Stream --> ResultsAggregation["📋 결과 집계<br/>agent_results 업데이트"]
    Agent2Stream --> ResultsAggregation
    Agent3Stream --> ResultsAggregation
    Agent4Stream --> ResultsAggregation
    
    ResultsAggregation --> SupervisorReturn["🎭 Supervisor로 복귀"]
    SupervisorReturn --> NextDecision["🔄 다음 결정<br/>계속 실행 or 응답 or 거래"]
```

---

*이 LangGraph 구조도는 Stockelper LLM 챗봇의 전체 워크플로우와 에이전트 간 상호작용을 시각적으로 표현합니다.*
