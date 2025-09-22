# Stockelper에서의 KIS OpenAPI 연동 문서

본 문서는 프로젝트 전반에서 KIS(OpenAPI, 한국투자증권) 엔드포인트를 어디서, 어떤 목적으로 호출하고, 어떤 데이터를 받아 어떻게 활용하는지 상세히 정리합니다. 또한 인증/해더 규칙, 토큰 만료 처리, 주문 시 hashkey 처리 등 운영상 주의점을 포함합니다.

## 1. 개요
- 목적: 실시간 시세 조회, 재무/지표 조회, 계좌 잔고 확인, 모의/실전 주문 수행
- 호출 방식: REST(API) + JSON, 비동기(aiohttp)와 동기(requests) 혼용
- 주요 사용 위치(모듈):
  - `src/multi_agent/utils.py`: 인증, 잔고조회, 주문, hashkey 유틸
  - `src/multi_agent/technical_analysis_agent/tools/stock.py`: 시세/기술분석용 현재가 조회
  - `src/multi_agent/technical_analysis_agent/tools/chart_analysis_tool.py`: mojito SDK 경유 OHLCV 조회
  - `src/multi_agent/portfolio_analysis_agent/tools/portfolio.py`: 각종 재무/랭킹 지표 조회
  - `src/multi_agent/investment_strategy_agent/tools/account.py`: 계정 잔고 조회(토큰 자동 갱신)
  - `src/multi_agent/supervisor_agent/agent.py`: 거래 실행(주문) 및 토큰 갱신/저장

## 2. 인증/환경 변수
- 필요한 환경 변수(.env/.env.example 참조)
  - `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`
- 시스템에서의 관리
  - 사용자별 키/계좌는 PostgreSQL `users` 테이블에 저장/조회
  - 토큰은 필요 시 발급/갱신하여 `users.kis_access_token`에 업데이트

### 2.1 액세스 토큰 발급
- 모듈/함수: `utils.get_access_token(app_key, app_secret)`
- URL: `https://openapivts.koreainvestment.com:29443/oauth2/tokenP`
- 메서드: `POST`
- 헤더: `content-type: application/json`
- 바디: `{ "grant_type": "client_credentials", "appkey": ..., "appsecret": ... }`
- 응답: `{ access_token: "...", ... }` → 반환값으로 access_token만 사용
- 사용처: 최초 호출 또는 만료 시 재발급 (여러 모듈에서 호출)

## 3. 주문/HashKey/잔고 조회

### 3.1 HashKey 생성 (주문 필수)
- 모듈/함수: `utils.get_hashkey(app_key, app_secret, body, url_base)`
- URL: `{url_base}/uapi/hashkey` (예: `https://openapivts.koreainvestment.com:29443/uapi/hashkey`)
- 메서드: `POST`
- 헤더: `content-type: application/json`, `appkey`, `appsecret`
- 바디: 실제 주문에 사용할 body(JSON)
- 응답: `{ "HASH": "..." }`
- 사용처: `utils.place_order(...)`에서 주문 전에 호출하여 주문 헤더에 `hashkey` 추가

### 3.2 현금주문 (모의투자/실전)
- 모듈/함수: `utils.place_order(stock_code, order_side, order_type, order_price, order_quantity, account_no, kis_app_key, kis_app_secret, kis_access_token, ...)`
- URL: `https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/order-cash`
- 메서드: `POST`
- 헤더(통일):
  - `Content-Type: application/json`
  - `authorization: Bearer {kis_access_token}`
  - `appkey: {KIS_APP_KEY}`
  - `appsecret: {KIS_APP_SECRET}`
  - `tr_id: {VTTC0802U|VTTC0011U}` (매수/매도, 모의투자 기준)
  - `custtype: P`
  - `hashkey: {get_hashkey(...)로 생성}`
- 바디 예시:
  ```json
  {
    "CANO": "50123456",              // account_no의 앞자리
    "ACNT_PRDT_CD": "01",            // account_no의 뒤자리
    "PDNO": "005930",                 // 종목코드
    "ORD_DVSN": "00",                 // 00: 지정가, 01: 시장가
    "ORD_QTY": "10",
    "ORD_UNPR": "70000"               // 시장가일 때 "0"
  }
  ```
- 응답: 표준 메시지 `msg1` 및 주문 접수 결과
- 에러/토큰 만료 처리: 응답 메시지에 `"유효하지 않은 token"` 또는 `"기간이 만료된 token"` 포함 시 토큰 재발급 후 재시도
- 사용처:
  - `supervisor_agent/agent.py`의 거래 실행 단계에서 호출 (TradingAction 기반)

### 3.3 계좌 잔고 조회
- 모듈/함수: `utils.check_account_balance(app_key, app_secret, access_token, account_no)`
- URL: `https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/inquire-balance`
- 메서드: `GET`
- 헤더: `Content-Type`, `authorization: Bearer ...`, `appKey`, `appSecret`, `tr_id: VTTC8434R`, `custtype: P`
- 파라미터: `CANO`, `ACNT_PRDT_CD` 등
- 응답: `output2[0]`에서 `dnca_tot_amt`(예수금), `tot_evlu_amt`(총 평가금액) 추출
- 에러/토큰 만료 처리: 동일하게 두 문구 인식 → 재발급 후 재요청
- 사용처:
- `investment_strategy_agent/tools/account.py` (GetAccountInfoTool) → 사용자에게 현재 잔고/평가금액 제공, 필요시 토큰 갱신 및 DB 업데이트

## 4. 시세/정보/지표 조회

### 4.1 현재가 조회(시세)
- 모듈/함수: `technical_analysis_agent/tools/stock.py` → `AnalysisStockTool.get_current_price(stock_no, user_id)`
- URL: `https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price`
- 메서드: `GET`
- 헤더: `authorization: Bearer ...`, `appkey`, `appsecret`, `tr_id: FHKST01010100`
- 파라미터: `fid_cond_mrkt_div_code=J`, `fid_input_iscd={stock_no}`
- 응답 사용 필드(예): 시장/업종명, 현재가/전일가/상하한가/고저가/거래량/누적금액, PER/PBR/EPS/BPS/배당수익률/외국인보유율/경고코드 등 → 사용자 응답 메시지에 포함
- 토큰 만료 처리: 401/403/500 + 두 문구 인식 시 갱신
- 타임아웃: `ClientTimeout(total=30)` 적용

### 4.2 종목 기본 정보 조회
- 모듈/함수: `portfolio_analysis_agent/tools/portfolio.py` → `get_stock_basic_info(pdno, prdt_type_cd)`
- URL: `.../uapi/domestic-stock/v1/quotations/search-stock-info`
- 메서드: `GET`
- 헤더: `_make_headers("CTPF1002R", ...)`
- 파라미터: `PDNO`, `PRDT_TYPE_CD`
- 응답: 종목 기본 정보 → 포트폴리오 분석 맥락에 활용

### 4.3 재무/지표(안정성/수익성 등)
- 모듈/함수: `portfolio_analysis_agent/tools/portfolio.py`
  - `get_stability_ratio(symbol, div_cd="0")`
    - URL: `.../uapi/domestic-stock/v1/finance/stability-ratio`
    - 헤더: `_make_headers("FHKST66430600", ...)`
    - 응답: `output` 배열 → 유동성/부채/현금비율 등 정규화 가중합 산출, 포트폴리오 안정성 점수에 반영
  - `get_profit_ratio(symbol, div_cd="1")`
    - URL: `.../uapi/domestic-stock/v1/finance/profit-ratio`
    - 헤더: `_make_headers("FHKST66430400", ...)`
    - 응답: 수익성 관련 지표 배열 → 정규화/가중합으로 점수 산출
- 에러/토큰 만료 처리: 동일 기준(401/403/500 + 두 문구)으로 재발급/재요청

### 4.4 랭킹(시가총액 상위 등)
- 모듈/함수: `portfolio_analysis_agent/tools/portfolio.py` → `get_top_market_value(fid_rank_sort_cls_code, user_info)`
- URL: `.../uapi/domestic-stock/v1/ranking/market-value`
- 헤더: `_make_headers("FHPST01790000", ...)`
- 파라미터: 랭킹/정렬 기준 등
- 응답: 상위 종목 리스트 → 추천 종목 후보군 구성에 활용

### 4.5 OHLCV(일봉) 조회(모듈: mojito)
- 모듈/함수: `technical_analysis_agent/tools/chart_analysis_tool.py` → `StockChartAnalyzer.get_stock_data(...)`
- 사용 방식: `mojito.KoreaInvestment(api_key, api_secret, acc_no)` 인스턴스를 통해 `broker.fetch_ohlcv(stock_code, "D", start, end)` 호출
- 응답: 일자별 시가/고가/저가/종가/거래량 등 → MACD/볼린저/RSI/스토캐스틱 계산 및 차트 이미지 생성에 사용

## 5. 데이터 사용 흐름
- 사용자 요청 → `SupervisorAgent` 라우팅 → 각 에이전트에서 필요 시 KIS 호출
- 분석 결과는 `values` 스트림으로 집계되어 최종 메시지(`FinalResponse.message`)로 반환
- `InvestmentStrategyAgent`가 제안한 `trading_action`은 `SupervisorAgent`의 `execute_trading`에서 사용자 승인 후 `place_order` 호출로 실제 주문
- 주문/조회 중 토큰 만료 발생 시 공통 규칙(두 문구 인식)으로 토큰 갱신 → DB 반영 → 재시도

## 6. 공통 규칙/가이드
- 헤더 키 통일: `appkey`, `appsecret`, `authorization`, `tr_id`, `custtype`
- 주문은 반드시 `hashkey` 포함
- 타임아웃: aiohttp `ClientTimeout(total=30)` 기본 적용
- 토큰 만료 메시지 표준화: 응답에 `"유효하지 않은 token"` 또는 `"기간이 만료된 token"` 포함 시 만료로 처리
- 계좌번호 분해: `CANO`, `ACNT_PRDT_CD`는 `account_no`를 `-`로 분리해 사용

## 7. 코드 참조 요약
- 인증/주문/잔고/유틸: `src/multi_agent/utils.py`
  - `get_access_token`, `check_account_balance`, `get_hashkey`, `place_order`
- 거래 실행: `src/multi_agent/supervisor_agent/agent.py` → `execute_trading`
- 계정 정보 조회: `src/multi_agent/investment_strategy_agent/tools/account.py` → `GetAccountInfoTool`
- 현재가/시세: `src/multi_agent/technical_analysis_agent/tools/stock.py` → `AnalysisStockTool`
- OHLCV/차트: `src/multi_agent/technical_analysis_agent/tools/chart_analysis_tool.py` → `StockChartAnalyzer`
- 지표/랭킹/기본정보: `src/multi_agent/portfolio_analysis_agent/tools/portfolio.py`

## 8. 예시 (의사코드/요청)

### 8.1 토큰 발급
```bash
curl -X POST \
  -H 'content-type: application/json' \
  -d '{"grant_type":"client_credentials","appkey":"${KIS_APP_KEY}","appsecret":"${KIS_APP_SECRET}"}' \
  https://openapivts.koreainvestment.com:29443/oauth2/tokenP
```

### 8.2 주문(HashKey 포함)
1) HashKey 생성
```bash
curl -X POST \
  -H 'content-type: application/json' \
  -H "appkey: ${KIS_APP_KEY}" -H "appsecret: ${KIS_APP_SECRET}" \
  -d '{"CANO":"50123456","ACNT_PRDT_CD":"01","PDNO":"005930","ORD_DVSN":"00","ORD_QTY":"10","ORD_UNPR":"70000"}' \
  https://openapivts.koreainvestment.com:29443/uapi/hashkey
```
2) 주문 요청
```bash
curl -X POST \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${ACCESS_TOKEN}" \
  -H "appkey: ${KIS_APP_KEY}" -H "appsecret: ${KIS_APP_SECRET}" \
  -H "tr_id: VTTC0802U" -H "custtype: P" -H "hashkey: ${HASH}" \
  -d '{"CANO":"50123456","ACNT_PRDT_CD":"01","PDNO":"005930","ORD_DVSN":"00","ORD_QTY":"10","ORD_UNPR":"70000"}' \
  https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/order-cash
```

### 8.3 현재가 조회
```bash
curl -G \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${ACCESS_TOKEN}" \
  -H "appkey: ${KIS_APP_KEY}" -H "appsecret: ${KIS_APP_SECRET}" -H "tr_id: FHKST01010100" \
  --data-urlencode 'fid_cond_mrkt_div_code=J' \
  --data-urlencode 'fid_input_iscd=005930' \
  https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price
```

---

본 문서는 코드 기준으로 유지보수됩니다. API 스펙 변경이나 추가 연동이 있을 경우 본 문서에 반영하세요.

