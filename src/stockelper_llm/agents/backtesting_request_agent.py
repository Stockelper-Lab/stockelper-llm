from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Literal, Optional

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


class BacktestParametersDraft(BaseModel):
    """백테스트 요청 파라미터(BacktestInput의 부분집합).

    - 확실한 값만 채우고, 모르는 값은 None으로 둡니다.
    - 이 모델을 structured output으로 강제하여, LLM이 '입력 쿼리(JSON)'를 안정적으로 생성하도록 합니다.
    """

    # 기간
    start_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")

    # 자본/리밸런싱/정렬
    initial_cash: Optional[int] = Field(default=None, description="원 단위 정수")
    rebalancing_period: Optional[Literal["daily", "weekly", "monthly", "quarterly"]] = None
    sort_by: Optional[Literal["momentum", "market_cap", "event_type", "disclosure"]] = None

    # 대상
    target_symbols: Optional[list[str]] = None  # 6자리 종목코드 리스트
    target_corp_names: Optional[list[str]] = None  # 회사명 리스트

    # 포트폴리오 크기
    max_positions: Optional[int] = Field(default=None, ge=1, le=50)
    max_portfolio_size: Optional[int] = Field(default=None, ge=1, le=200)

    # 기본 동작
    use_dart_disclosure: bool = Field(default=True)

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
    def _normalize_symbols(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if not v:
            return None
        out: list[str] = []
        for x in v:
            s = str(x).strip()
            if len(s) == 6 and s.isdigit():
                out.append(s)
        out = sorted(set(out))
        return out or None

    @field_validator("target_corp_names")
    @classmethod
    def _normalize_names(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if not v:
            return None
        out: list[str] = []
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

    params: dict = {"use_dart_disclosure": True}

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

    return params


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
        "반드시 JSON 스키마에 맞춰서만 출력하고, 추측/환각을 최소화한다.\n"
        "- 종목코드(6자리)가 명시되지 않았으면 target_symbols는 비워두고, 회사명은 target_corp_names에 넣는다.\n"
        "- 날짜는 YYYY-MM-DD 형식. 모르면 null.\n"
        "- 리밸런싱 주기는 daily/weekly/monthly/quarterly.\n"
        "- sort_by는 momentum/market_cap/event_type/disclosure 중 하나.\n"
        "- 사용자가 말하지 않은 값은 null로 둔다."
    )
    user = f"사용자 입력:\n{text}"

    try:
        parsed: BacktestParametersDraft = await llm_structured.ainvoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        llm_params = parsed.model_dump(exclude_none=True)
    except Exception:
        return fallback

    # 보수적 병합: LLM 결과가 비어있으면 fallback
    if not llm_params:
        return fallback

    # 필수에 가까운 값(대상/기간)이 빠진 경우 fallback로 보완
    merged = dict(llm_params)
    for k in ("target_symbols", "target_corp_names", "start_date", "end_date"):
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

