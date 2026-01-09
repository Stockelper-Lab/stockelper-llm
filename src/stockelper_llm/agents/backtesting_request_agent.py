from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Literal, Optional

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator


_STOCK_CODE_PAT = re.compile(r"\b\d{6}\b")
_DATE_YMD_PAT = re.compile(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})")
_YEAR_RANGE_PAT = re.compile(r"(20\d{2})\s*(?:년)?\s*[~\\-–]\s*(20\d{2})\s*(?:년)?")
_YEAR_PAT = re.compile(r"(20\d{2})\s*년")
_MONEY_EOK_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*억(?:원)?")
_MONEY_MAN_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*만(?:원)?")
_MONEY_WON_PAT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")


def _model_name(default: str = "gpt-5.1") -> str:
    return (
        os.getenv("STOCKELPER_BACKTESTING_REQUEST_MODEL")
        or os.getenv("STOCKELPER_LLM_MODEL")
        or os.getenv("STOCKELPER_MODEL")
        or default
    ).strip()


def _get_backtesting_service_url() -> str:
    base = os.getenv("STOCKELPER_BACKTESTING_URL", "").strip()
    if not base:
        raise RuntimeError("Missing STOCKELPER_BACKTESTING_URL")
    return base.rstrip("/")


class IndicatorCondition(BaseModel):
    """이벤트별 지표 조건 설정 (score_table_dart_idc 기반)."""

    report_type: str = Field(
        description="공시 유형 (예: '유상증자 결정', '감자 결정', '회사합병 결정')"
    )
    idc_nm: str = Field(
        description="지표명 (예: '희석률', '감자비율', '합병비율')"
    )
    action: Literal["BUY", "SELL"] = Field(
        description="조건 만족 시 행동 (BUY: 매수, SELL: 매도)"
    )
    condition_min: Optional[float] = Field(
        default=None, description="최소값 (None이면 제한 없음)"
    )
    condition_max: Optional[float] = Field(
        default=None, description="최대값 (None이면 제한 없음)"
    )
    condition_operator: Literal["between", ">=", "<=", ">", "<", "=="] = Field(
        default="between", description="조건 연산자"
    )
    delay_days: int = Field(
        default=0, ge=0, le=30, description="공시일로부터 N일 후 매매"
    )


class BacktestParametersDraft(BaseModel):
    """백테스트 요청 파라미터(BacktestInput의 부분집합).

    - 확실한 값만 채우고, 모르는 값은 None으로 둡니다.
    - 이 모델을 structured output으로 강제하여, LLM이 '입력 쿼리(JSON)'를 안정적으로 생성하도록 합니다.
    """

    # 기간
    start_date: Optional[str] = Field(default=None, description="YYYY-MM-DD 형식의 시작일")
    end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD 형식의 종료일")

    # 자본/리밸런싱/정렬
    initial_cash: Optional[int] = Field(
        default=None,
        description="초기 투자금액 (원 단위 정수, 예: 1억=100000000)"
    )
    rebalancing_period: Optional[Literal["daily", "weekly", "monthly", "quarterly"]] = Field(
        default=None,
        description="리밸런싱 주기 (daily: 매일, weekly: 매주, monthly: 매월, quarterly: 분기)"
    )
    sort_by: Optional[Literal["momentum", "market_cap", "event_type", "disclosure"]] = Field(
        default=None,
        description="정렬 기준 (momentum: 모멘텀, market_cap: 시가총액, event_type: 이벤트, disclosure: 공시)"
    )

    # 대상
    target_symbols: Optional[List[str]] = Field(
        default=None, description="6자리 종목코드 리스트 (예: ['005930', '000660'])"
    )
    target_corp_names: Optional[List[str]] = Field(
        default=None, description="회사명 리스트 (예: ['삼성전자', 'SK하이닉스'])"
    )

    # 포트폴리오 크기
    max_positions: Optional[int] = Field(
        default=None, ge=1, le=50, description="최대 보유 종목 수 (1~50)"
    )
    max_portfolio_size: Optional[int] = Field(
        default=None, ge=1, le=200, description="포트폴리오 최대 종목 수 (1~200)"
    )

    # 필터링
    filter_type: Optional[Literal["top", "bottom", "value"]] = Field(
        default=None,
        description="필터 타입 (top: 상위, bottom: 하위, value: 값 기준)"
    )
    filter_percent: Optional[float] = Field(
        default=None, ge=0, le=100, description="상위/하위 % (예: 20 = 상위 20%)"
    )

    # DART 공시 설정
    use_dart_disclosure: bool = Field(
        default=True, description="DART 공시 데이터 사용 여부"
    )

    # 이벤트별 지표 조건
    event_indicator_conditions: Optional[List[IndicatorCondition]] = Field(
        default=None,
        description="이벤트별 지표 조건 설정 리스트 (공시 지표가 특정 조건을 만족할 때 매수/매도)"
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        # 매우 단순한 형식 검증(YYYY-MM-DD)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return None
        return s

    @field_validator("target_symbols")
    @classmethod
    def _normalize_symbols(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return None
        out: List[str] = []
        for x in v:
            s = str(x).strip()
            if len(s) == 6 and s.isdigit():
                out.append(s)
        out = sorted(set(out))
        return out or None

    @field_validator("target_corp_names")
    @classmethod
    def _normalize_names(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return None
        out: List[str] = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s)
        out = sorted(set(out))
        return out or None


def _build_params_rule_based(text: str) -> Dict[str, Any]:
    """백테스트 초기 입력값을 룰 기반으로 추정(LLM 실패/미설정 시 fallback)."""

    t = (text or "").strip()
    if not t:
        return {}

    params: Dict[str, Any] = {"use_dart_disclosure": True}

    # 1) 종목코드(6자리)
    codes = _STOCK_CODE_PAT.findall(t)
    codes = sorted(set(codes))
    if codes:
        params["target_symbols"] = codes
        params["max_portfolio_size"] = len(codes)
        params["max_positions"] = max(1, min(10, len(codes)))

    # 2) 기간
    ymd = _DATE_YMD_PAT.findall(t)
    if len(ymd) >= 2:
        y1, m1, d1 = ymd[0]
        y2, m2, d2 = ymd[1]
        params["start_date"] = f"{int(y1):04d}-{int(m1):02d}-{int(d1):02d}"
        params["end_date"] = f"{int(y2):04d}-{int(m2):02d}-{int(d2):02d}"
    else:
        yr = _YEAR_RANGE_PAT.search(t)
        if yr:
            y1, y2 = int(yr.group(1)), int(yr.group(2))
            start_y, end_y = (y1, y2) if y1 <= y2 else (y2, y1)
            params["start_date"] = f"{start_y:04d}-01-01"
            params["end_date"] = f"{end_y:04d}-12-31"
        else:
            y = _YEAR_PAT.search(t)
            if y:
                yy = int(y.group(1))
                params["start_date"] = f"{yy:04d}-01-01"
                params["end_date"] = f"{yy:04d}-12-31"

    # 3) 리밸런싱
    if any(k in t for k in ("매일", "일간", "daily")):
        params["rebalancing_period"] = "daily"
    elif any(k in t for k in ("매주", "주간", "weekly")):
        params["rebalancing_period"] = "weekly"
    elif any(k in t for k in ("매월", "월간", "monthly")):
        params["rebalancing_period"] = "monthly"
    elif any(k in t for k in ("분기", "quarter")):
        params["rebalancing_period"] = "quarterly"

    # 4) sort_by
    tl = t.lower()
    if any(k in tl for k in ("momentum", "모멘텀", "급등", "수익률")):
        params["sort_by"] = "momentum"
    elif any(k in tl for k in ("market_cap", "시총", "시가총액")):
        params["sort_by"] = "market_cap"
    elif any(k in tl for k in ("event_type", "이벤트")):
        params["sort_by"] = "event_type"
    elif any(k in tl for k in ("disclosure", "공시")):
        params["sort_by"] = "disclosure"

    # 5) 투자금
    m_eok = _MONEY_EOK_PAT.search(t)
    if m_eok:
        params["initial_cash"] = int(float(m_eok.group(1)) * 100_000_000)
    else:
        m_won = _MONEY_WON_PAT.search(t)
        if m_won:
            params["initial_cash"] = int(str(m_won.group(1)).replace(",", ""))
        else:
            m_man = _MONEY_MAN_PAT.search(t)
            if m_man:
                params["initial_cash"] = int(float(m_man.group(1)) * 10_000)

    # 6) 필터링 (상위/하위)
    if any(k in t for k in ("상위", "top")):
        params["filter_type"] = "top"
        # 상위 N% 패턴 추출
        pct_match = re.search(r"상위\s*(\d+)\s*%", t)
        if pct_match:
            params["filter_percent"] = float(pct_match.group(1))
    elif any(k in t for k in ("하위", "bottom")):
        params["filter_type"] = "bottom"
        pct_match = re.search(r"하위\s*(\d+)\s*%", t)
        if pct_match:
            params["filter_percent"] = float(pct_match.group(1))

    # 7) 이벤트/공시 기반 조건 추출 (룰 기반)
    event_conditions: List[Dict[str, Any]] = []

    # 희석률 조건
    if "희석률" in t:
        cond: Dict[str, Any] = {
            "report_type": "유상증자 결정",
            "idc_nm": "희석률",
            "action": "BUY",
            "delay_days": 0,
            "condition": {"operator": "between"},
        }
        # "희석률 30% 이하" 같은 패턴
        dilution_match = re.search(r"희석률\s*(\d+(?:\.\d+)?)\s*%?\s*이하", t)
        if dilution_match:
            cond["condition"]["max"] = float(dilution_match.group(1)) / 100
            cond["condition"]["min"] = 0.0
        event_conditions.append(cond)

    # 감자비율 조건
    if "감자" in t:
        cond = {
            "report_type": "감자 결정",
            "idc_nm": "감자비율",
            "action": "SELL",
            "delay_days": 0,
            "condition": {"operator": ">=", "min": 0.1},
        }
        event_conditions.append(cond)

    if event_conditions:
        params["event_indicator_conditions"] = event_conditions

    return params


def _convert_indicator_conditions(conditions: List[IndicatorCondition]) -> List[Dict[str, Any]]:
    """IndicatorCondition Pydantic 모델을 BacktestInput 형식의 dict로 변환."""
    result: List[Dict[str, Any]] = []
    for cond in conditions:
        item: Dict[str, Any] = {
            "report_type": cond.report_type,
            "idc_nm": cond.idc_nm,
            "action": cond.action,
            "delay_days": cond.delay_days,
            "condition": {
                "operator": cond.condition_operator,
            },
        }
        if cond.condition_min is not None:
            item["condition"]["min"] = cond.condition_min
        if cond.condition_max is not None:
            item["condition"]["max"] = cond.condition_max
        result.append(item)
    return result


async def build_backtest_parameters_from_user_text(user_text: str) -> Dict[str, Any]:
    """유저 자연어 → 백테스트 파라미터 dict (LLM + fallback).

    반환 dict는 backtesting 서버의 `parameters`로 그대로 전달됩니다.
    """

    text = (user_text or "").strip()
    if not text:
        return {}

    fallback = _build_params_rule_based(text)

    # LLM이 없으면 fallback
    if not os.getenv("OPENAI_API_KEY"):
        return fallback

    model = _model_name()
    llm = ChatOpenAI(model=model, temperature=0.0)
    llm_structured = llm.with_structured_output(BacktestParametersDraft)

    system = (
        "너는 사용자의 자연어를 한국 주식 백테스트 요청 파라미터로 변환하는 변환기다.\n"
        "반드시 JSON 스키마에 맞춰서만 출력하고, 추측/환각을 최소화한다.\n\n"
        "## 기본 규칙\n"
        "- 종목코드(6자리)가 명시되지 않았으면 target_symbols는 비워두고, 회사명은 target_corp_names에 넣는다.\n"
        "- 날짜는 YYYY-MM-DD 형식. 모르면 null.\n"
        "- 리밸런싱 주기는 daily/weekly/monthly/quarterly.\n"
        "- sort_by는 momentum/market_cap/event_type/disclosure 중 하나.\n"
        "- 사용자가 말하지 않은 값은 null로 둔다.\n\n"
        "## 이벤트별 지표 조건 (event_indicator_conditions)\n"
        "사용자가 공시 관련 조건을 언급하면 event_indicator_conditions를 채운다.\n"
        "지원되는 공시 유형(report_type):\n"
        "- 유상증자 결정, 무상증자 결정, 유무상증자 결정\n"
        "- 감자 결정\n"
        "- 자기주식 취득 결정, 자기주식 처분 결정\n"
        "- 회사합병 결정, 회사분할 결정\n"
        "- 전환사채권 발행결정, 신주인수권부사채권 발행결정\n"
        "지원되는 지표명(idc_nm):\n"
        "- 희석률, 감자비율, 합병비율, 분할비율, 증자비율\n\n"
        "예시:\n"
        "- '유상증자 희석률 30% 이하면 매수' → report_type='유상증자 결정', idc_nm='희석률', action='BUY', condition_max=0.3\n"
        "- '감자비율 10% 이상이면 매도' → report_type='감자 결정', idc_nm='감자비율', action='SELL', condition_min=0.1\n\n"
        "## 필터링\n"
        "- '상위 20%' → filter_type='top', filter_percent=20\n"
        "- '하위 10%' → filter_type='bottom', filter_percent=10"
    )
    user = f"사용자 입력:\n{text}"

    try:
        parsed: BacktestParametersDraft = await llm_structured.ainvoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        llm_params = parsed.model_dump(exclude_none=True)

        # event_indicator_conditions를 BacktestInput 형식으로 변환
        if parsed.event_indicator_conditions:
            llm_params["event_indicator_conditions"] = _convert_indicator_conditions(
                parsed.event_indicator_conditions
            )
    except Exception:
        return fallback

    # 보수적 병합: LLM 결과가 비어있으면 fallback
    if not llm_params:
        return fallback

    # 필수에 가까운 값(대상/기간)이 빠진 경우 fallback로 보완
    merged = dict(llm_params)
    for k in ("target_symbols", "target_corp_names", "start_date", "end_date", "event_indicator_conditions"):
        if merged.get(k) in (None, "", [], {}):
            if k in fallback and fallback.get(k) not in (None, "", [], {}):
                merged[k] = fallback[k]

    # 안전: 단일 종목이면 기본값 보정
    syms = merged.get("target_symbols")
    if isinstance(syms, list) and syms:
        merged.setdefault("max_portfolio_size", len(syms))
        merged.setdefault("max_positions", max(1, min(10, len(syms))))

    # 기본 DART 모드 유지
    merged.setdefault("use_dart_disclosure", True)
    return merged


async def request_backtesting_job(*, user_id: int, user_text: str) -> Dict[str, Any]:
    """백테스팅 서버에 job 생성 요청을 자동으로 보냅니다.

    포트폴리오 트리거와 동일하게, '요청'은 LLM 서버가 만들고,
    실행/결과 적재/해석은 (backtesting/worker + llm/internal/interpret) 체계로 처리합니다.
    """

    base = _get_backtesting_service_url()

    params = await build_backtest_parameters_from_user_text(user_text)
    target_symbols = params.get("target_symbols") if isinstance(params, dict) else None

    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "stock_symbol": (target_symbols[0] if isinstance(target_symbols, list) and target_symbols else None),
        "strategy_type": params.get("sort_by") if isinstance(params, dict) else None,
        "query": user_text,
    }
    if params:
        payload["parameters"] = params

    timeout_s = float(os.getenv("BACKTESTING_REQUESTS_TIMEOUT", "") or os.getenv("REQUESTS_TIMEOUT", "30") or 30)
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(f"{base}/api/backtesting/execute", json=payload)
        resp.raise_for_status()
        return resp.json()

