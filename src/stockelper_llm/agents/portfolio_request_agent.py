from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


_PORTFOLIO_COUNT_PAT = re.compile(r"(\d{1,3})\s*(?:개|종목)")

# 웹검색 포함/제외 힌트(룰 기반 fallback)
_WEBSEARCH_TRUE_PAT = re.compile(
    r"(웹\s*검색|웹검색|web\s*search|뉴스|기사|이슈|최신|perplexity)",
    re.IGNORECASE,
)
_WEBSEARCH_FALSE_PAT = re.compile(
    r"(웹\s*검색\s*(?:제외|빼|빼고|안|없이)|웹검색\s*(?:제외|빼|빼고|안|없이)|"
    r"뉴스\s*(?:제외|필요\s*없)|검색\s*(?:제외|안|없이)|no\s*web\s*search)",
    re.IGNORECASE,
)

# 무위험 이자율 힌트(룰 기반 fallback)
_RF_HINT_PAT = re.compile(
    r"(무위험|risk\s*[- ]?free(?:\s*rate)?|\brf\b|riskfree)",
    re.IGNORECASE,
)
_RF_PERCENT_PAT = re.compile(
    r"(?:무위험(?:이자율|수익률)?|risk\s*[- ]?free(?:\s*rate)?|\brf\b|riskfree)"
    r"\s*(?:[:=]|\s)*\s*(\d+(?:\.\d+)?)\s*(?:%|퍼|프로)",
    re.IGNORECASE,
)
_RF_DECIMAL_PAT = re.compile(
    r"(?:무위험(?:이자율|수익률)?|risk\s*[- ]?free(?:\s*rate)?|\brf\b|riskfree)"
    r"\s*(?:[:=]|\s)*\s*(0\.\d+)",
    re.IGNORECASE,
)
_RF_NUMBER_PAT = re.compile(
    r"(?:무위험(?:이자율|수익률)?|risk\s*[- ]?free(?:\s*rate)?|\brf\b|riskfree)"
    r"\s*(?:[:=]|\s)*\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _model_name(default: str = "gpt-5.1") -> str:
    return (
        os.getenv("STOCKELPER_PORTFOLIO_REQUEST_MODEL")
        or os.getenv("STOCKELPER_LLM_MODEL")
        or os.getenv("STOCKELPER_MODEL")
        or default
    ).strip()


def _get_portfolio_service_url() -> str:
    base = os.getenv("STOCKELPER_PORTFOLIO_URL", "").strip()
    if not base:
        raise RuntimeError("Missing STOCKELPER_PORTFOLIO_URL")
    return base.rstrip("/")


def _has_websearch_hint(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_WEBSEARCH_TRUE_PAT.search(t) or _WEBSEARCH_FALSE_PAT.search(t))


def _has_risk_free_rate_hint(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_RF_HINT_PAT.search(t))


def _extract_portfolio_size_rule_based(text: str) -> Optional[int]:
    t = (text or "").strip()
    if not t:
        return None
    m = _PORTFOLIO_COUNT_PAT.search(t)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _extract_include_web_search_rule_based(text: str) -> Optional[bool]:
    t = (text or "").strip()
    if not t:
        return None

    # "제외/빼고/안함" 같은 표현이 있으면 False를 우선합니다.
    if _WEBSEARCH_FALSE_PAT.search(t):
        return False
    if _WEBSEARCH_TRUE_PAT.search(t):
        return True
    return None


def _normalize_risk_free_rate_value(v: float) -> Optional[float]:
    try:
        x = float(v)
    except Exception:
        return None
    # 3 같은 값(=3%)을 방지하기 위해, 1~100은 %로 간주하여 변환합니다.
    if 1.0 < x <= 100.0:
        x = x / 100.0
    # 비정상 값은 무시하고 서버 기본값(0.03)에 맡깁니다.
    if x < 0.0 or x > 0.2:
        return None
    return x


def _extract_risk_free_rate_rule_based(text: str) -> Optional[float]:
    t = (text or "").strip()
    if not t:
        return None

    if not _has_risk_free_rate_hint(t):
        return None

    m_pct = _RF_PERCENT_PAT.search(t)
    if m_pct:
        try:
            v = float(m_pct.group(1)) / 100.0
        except Exception:
            return None
        return _normalize_risk_free_rate_value(v)

    m_dec = _RF_DECIMAL_PAT.search(t)
    if m_dec:
        try:
            v = float(m_dec.group(1))
        except Exception:
            return None
        return _normalize_risk_free_rate_value(v)

    m_num = _RF_NUMBER_PAT.search(t)
    if m_num:
        try:
            v = float(m_num.group(1))
        except Exception:
            return None
        return _normalize_risk_free_rate_value(v)

    return None


def _build_params_rule_based(text: str) -> Dict[str, Any]:
    """포트폴리오 추천 파라미터를 룰 기반으로 추정(LLM 실패/미설정 시 fallback)."""

    t = (text or "").strip()
    if not t:
        return {}

    params: Dict[str, Any] = {}

    size = _extract_portfolio_size_rule_based(t)
    if size is not None:
        params["portfolio_size"] = size

    include_ws = _extract_include_web_search_rule_based(t)
    if include_ws is not None:
        params["include_web_search"] = include_ws

    rf = _extract_risk_free_rate_rule_based(t)
    if rf is not None:
        params["risk_free_rate"] = rf

    return params


class PortfolioParametersDraft(BaseModel):
    """유저 자연어 → 포트폴리오 추천 요청 파라미터(부분집합).

    - 사용자가 명시하지 않은 값은 반드시 None(null)로 둡니다(추측 금지).
    - 이 모델을 structured output으로 강제해 파싱 안정성을 높입니다.
    """

    portfolio_size: Optional[int] = Field(
        default=None,
        description="추천 종목 개수. 사용자가 'N개/ N종목'으로 명시했을 때만 설정, 아니면 null.",
    )
    include_web_search: Optional[bool] = Field(
        default=None,
        description="웹검색 기반 신호 포함 여부. 사용자가 포함/제외를 명시하지 않으면 null.",
    )
    risk_free_rate: Optional[float] = Field(
        default=None,
        description="무위험 이자율(연율 소수). 예: 3% -> 0.03. 사용자가 명시하지 않으면 null.",
    )

    @field_validator("portfolio_size")
    @classmethod
    def _normalize_portfolio_size(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        try:
            n = int(v)
        except Exception:
            return None
        # 과도한 값은 무시 (서버는 1~20만 지원하지만, 여기서는 '요청' 자체는 보존)
        if n <= 0 or n > 200:
            return None
        return n

    @field_validator("risk_free_rate")
    @classmethod
    def _normalize_risk_free_rate(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return _normalize_risk_free_rate_value(v)


async def build_portfolio_parameters_from_user_text(user_text: str) -> Dict[str, Any]:
    """유저 자연어 → 포트폴리오 추천 파라미터 dict (LLM + fallback).

    반환 dict는 portfolio 서버의 `/portfolio/recommendations` JSON payload에 포함됩니다.
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
    llm_structured = llm.with_structured_output(PortfolioParametersDraft)

    system = (
        "너는 사용자의 자연어를 '포트폴리오 추천 API' 파라미터로 변환하는 변환기다.\n"
        "반드시 JSON 스키마에 맞는 값만 출력하고, 사용자가 말하지 않은 값은 null로 둔다(추측 금지).\n\n"
        "## 필드 규칙\n"
        "- portfolio_size: 사용자가 'N개', 'N종목' 등으로 명시했을 때만 설정. 아니면 null.\n"
        "- include_web_search: 사용자가 웹검색/뉴스/최신/이슈 반영을 원하면 true,\n"
        "  웹검색 제외/빼고/안해도 되면 false. 언급이 없으면 null.\n"
        "- risk_free_rate: 사용자가 무위험 이자율(risk free rate/rf)을 말했을 때만 설정.\n"
        "  값은 연율 소수(예: 3% -> 0.03). 퍼센트로 말하면 변환한다.\n\n"
        "예시:\n"
        "- '10개 종목 추천해줘' -> portfolio_size=10\n"
        "- '웹검색 포함해서 추천' -> include_web_search=true\n"
        "- '무위험이자율 2.5%로' -> risk_free_rate=0.025\n"
    )
    user = f"사용자 입력:\n{text}"

    try:
        parsed: PortfolioParametersDraft = await llm_structured.ainvoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        llm_params = parsed.model_dump(exclude_none=True)
    except Exception:
        return fallback

    if not llm_params:
        return fallback

    # 보수적 병합: LLM 결과에 없는 값만 fallback으로 채움
    merged = dict(llm_params)
    for k, v in fallback.items():
        if k not in merged:
            merged[k] = v

    # ============================================================
    # 환각 방지 가드레일: '언급 없음'인 경우 LLM 값 제거
    # ============================================================
    if "portfolio_size" in merged and _PORTFOLIO_COUNT_PAT.search(text) is None:
        merged.pop("portfolio_size", None)
    if "include_web_search" in merged and not _has_websearch_hint(text):
        merged.pop("include_web_search", None)
    if "risk_free_rate" in merged and not _has_risk_free_rate_hint(text):
        merged.pop("risk_free_rate", None)

    return merged


async def request_portfolio_recommendations(
    *, user_id: int, user_text: str
) -> Dict[str, Any]:
    """포트폴리오 서버에 추천 생성 요청을 보냅니다.

    - 내부에서 LLM(structured output) + 룰 기반 fallback으로 파라미터를 생성하고,
    - `/portfolio/recommendations`로 전달합니다.
    """

    base = _get_portfolio_service_url()
    params = await build_portfolio_parameters_from_user_text(user_text)

    payload: Dict[str, Any] = {"user_id": int(user_id)}
    if params:
        payload.update(params)

    timeout_s = float(
        os.getenv("PORTFOLIO_REQUESTS_TIMEOUT", "")
        or os.getenv("REQUESTS_TIMEOUT", "300")
        or 300
    )
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(f"{base}/portfolio/recommendations", json=payload)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise RuntimeError(f"portfolio API error ({resp.status_code}): {detail}")

        try:
            data = resp.json()
        except Exception:
            data = {"status_code": resp.status_code, "text": resp.text}

    logger.info(
        "Triggered portfolio recommendations: user_id=%s payload=%s", user_id, payload
    )
    return data
