from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional

import asyncpg
import httpx
from fastapi import APIRouter, HTTPException, status
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from stockelper_llm.core.db_urls import to_postgresql_conninfo

router = APIRouter(prefix="/internal/backtesting", tags=["backtesting"])


_SCHEMA_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

PROMPT_VERSION = "v1"


def _get_schema() -> str:
    schema = os.getenv("STOCKELPER_WEB_SCHEMA", "public")
    if not _SCHEMA_NAME_RE.match(schema):
        raise ValueError(f"Invalid STOCKELPER_WEB_SCHEMA: {schema!r}")
    return schema


def _get_table() -> str:
    table = os.getenv("STOCKELPER_BACKTESTING_TABLE", "backtesting")
    if not _TABLE_NAME_RE.match(table):
        raise ValueError(f"Invalid STOCKELPER_BACKTESTING_TABLE: {table!r}")
    return table


def _get_stockelper_web_dsn() -> str:
    # stockelper_web DB를 가리키는 DSN
    url = (
        os.getenv("STOCKELPER_WEB_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("ASYNC_DATABASE_URL")
    )
    dsn = to_postgresql_conninfo(url)
    if not dsn:
        raise RuntimeError("Missing STOCKELPER_WEB_DATABASE_URL or DATABASE_URL/ASYNC_DATABASE_URL")
    return dsn


def _get_backtesting_service_url() -> str:
    base = os.getenv("STOCKELPER_BACKTESTING_URL", "").strip()
    if not base:
        raise RuntimeError("Missing STOCKELPER_BACKTESTING_URL")
    return base.rstrip("/")


def _analysis_model_name() -> str:
    return (
        os.getenv("STOCKELPER_BACKTESTING_ANALYSIS_MODEL")
        or os.getenv("STOCKELPER_LLM_MODEL")
        or os.getenv("STOCKELPER_MODEL")
        or "gpt-5.1"
    ).strip()


class InterpretRequest(BaseModel):
    user_id: int = Field(description="stockelper_web.users.id")
    job_id: str = Field(description="public.backtesting.job_id")
    force: bool = Field(default=False, description="이미 completed인 분석을 강제로 재생성")


class BacktestInterpretationJson(BaseModel):
    """LLM 출력(고정 스키마).

    NOTE: 이 JSON을 그대로 analysis_json에 저장하고,
    사람이 읽을 수 있는 보고서는 서버에서 markdown으로 렌더링합니다.
    """

    summary: list[str] = Field(
        min_length=3,
        max_length=7,
        description="3~7줄 요약(각 항목은 한 문장)",
    )
    performance_interpretation: str = Field(
        description="수익률/변동성/MDD/샤프/승률 등을 근거로 한 해석"
    )
    trade_and_rebalance_characteristics: str = Field(
        description="진입/청산 규칙, 리밸런싱, 트레이드 성향(빈도/사유) 분석"
    )
    limitations_and_warnings: list[str] = Field(
        min_length=2, description="현재 구현/데이터 한계 및 주의사항"
    )
    next_experiments: list[str] = Field(
        min_length=3, description="다음 실험(파라미터/검증/개선) 제안"
    )


def _render_markdown(
    *,
    job_id: str,
    input_json: Dict[str, Any],
    output_json: Dict[str, Any],
    analysis: BacktestInterpretationJson,
) -> str:
    metrics_lines: list[str] = []
    for key, label in [
        ("total_return", "총 수익률(%)"),
        ("annualized_return", "연환산 수익률(%)"),
        ("mdd", "MDD(%)"),
        ("sharpe_ratio", "샤프"),
        ("win_rate", "승률(%)"),
        ("total_trades", "거래 횟수"),
    ]:
        if key in output_json:
            metrics_lines.append(f"- **{label}**: {output_json.get(key)}")

    target = None
    try:
        params = input_json.get("parameters") or {}
        if isinstance(params, dict):
            target = params.get("target_symbols") or params.get("target_corp_names")
    except Exception:
        pass

    md = []
    md.append(f"# 백테스트 해석 리포트\n")
    md.append(f"- **job_id**: `{job_id}`\n")
    if target:
        md.append(f"- **대상**: `{target}`\n")

    md.append("\n## 요약\n")
    for s in analysis.summary:
        md.append(f"- {s}\n")

    md.append("\n## 핵심 지표(요약)\n")
    if metrics_lines:
        md.extend([x + "\n" for x in metrics_lines])
    else:
        md.append("- (요약 지표가 없습니다)\n")

    md.append("\n## 성과 해석\n")
    md.append(analysis.performance_interpretation.strip() + "\n")

    md.append("\n## 트레이드/리밸런싱 특징\n")
    md.append(analysis.trade_and_rebalance_characteristics.strip() + "\n")

    md.append("\n## 한계 및 주의사항\n")
    for s in analysis.limitations_and_warnings:
        md.append(f"- {s}\n")

    md.append("\n## 다음 실험 제안\n")
    for s in analysis.next_experiments:
        md.append(f"- {s}\n")

    return "".join(md)


async def _update_analysis_in_progress(*, job_id: str, user_id: int, model: str) -> None:
    schema = _get_schema()
    table = _get_table()
    dsn = _get_stockelper_web_dsn()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            f"""
            UPDATE {schema}.{table}
            SET analysis_status = 'in_progress',
                analysis_model = $3,
                analysis_prompt_version = $4,
                analysis_error_message = NULL,
                analysis_started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $1 AND user_id = $2
            """,
            job_id,
            int(user_id),
            model,
            PROMPT_VERSION,
        )
    finally:
        await conn.close()


async def _update_analysis_completed(
    *,
    job_id: str,
    user_id: int,
    analysis_md: str,
    analysis_json: Dict[str, Any],
    elapsed_seconds: float,
) -> None:
    schema = _get_schema()
    table = _get_table()
    dsn = _get_stockelper_web_dsn()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            f"""
            UPDATE {schema}.{table}
            SET analysis_status = 'completed',
                analysis_md = $3,
                analysis_json = $4,
                analysis_error_message = NULL,
                analysis_elapsed_seconds = $5,
                analysis_completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $1 AND user_id = $2
            """,
            job_id,
            int(user_id),
            analysis_md,
            json.dumps(analysis_json, ensure_ascii=False, default=str),  # asyncpg jsonb 호환
            float(elapsed_seconds),
        )
    finally:
        await conn.close()


async def _update_analysis_failed(*, job_id: str, user_id: int, error_message: str, elapsed_seconds: float) -> None:
    schema = _get_schema()
    table = _get_table()
    dsn = _get_stockelper_web_dsn()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            f"""
            UPDATE {schema}.{table}
            SET analysis_status = 'failed',
                analysis_error_message = $3,
                analysis_elapsed_seconds = $4,
                analysis_completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $1 AND user_id = $2
            """,
            job_id,
            int(user_id),
            str(error_message),
            float(elapsed_seconds),
        )
    finally:
        await conn.close()


@router.post("/interpret", status_code=status.HTTP_200_OK)
async def interpret_backtest(req: InterpretRequest):
    """백테스트 완료 결과를 LLM으로 해석하고 public.backtesting에 저장합니다.

    고정 입력(권장 조합):
    - input_json(요청 파라미터)
    - output_json(핵심 지표 요약)
    - report_markdown(백테스트 리포트)
    - trades_tail/event_performance(결과 JSON에서 일부만 샘플링)

    고정 출력:
    - BacktestInterpretationJson (analysis_json 저장)
    - markdown 렌더링 결과 (analysis_md 저장)
    """

    t0 = time.time()
    model = _analysis_model_name()

    try:
        await _update_analysis_in_progress(job_id=req.job_id, user_id=req.user_id, model=model)

        base = _get_backtesting_service_url()
        timeout_s = float(os.getenv("BACKTEST_ANALYSIS_HTTP_TIMEOUT", "60") or 60)
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            # 1) status/result 조회 (input_json/output_json 포함)
            r = await client.get(
                f"{base}/api/backtesting/{req.job_id}/result",
                params={"user_id": req.user_id},
            )
            r.raise_for_status()
            job = r.json()
            if (job.get("status") or "").lower() != "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"backtest is not completed (status={job.get('status')})",
                )

            input_json = job.get("input_json") or {}
            output_json = job.get("output_json") or {}

            # 2) report markdown
            r_md = await client.get(
                f"{base}/api/backtesting/{req.job_id}/artifact",
                params={"user_id": req.user_id, "kind": "md"},
            )
            r_md.raise_for_status()
            report_md = r_md.text

            # 3) result json -> trades tail/sample
            trades_tail: list[dict] = []
            event_perf: dict = {}
            try:
                r_js = await client.get(
                    f"{base}/api/backtesting/{req.job_id}/artifact",
                    params={"user_id": req.user_id, "kind": "json"},
                )
                r_js.raise_for_status()
                result_payload = r_js.json()
                if isinstance(result_payload, dict):
                    trades = result_payload.get("trades") or []
                    if isinstance(trades, list):
                        trades_tail = trades[-50:]
                    ep = result_payload.get("event_performance") or {}
                    if isinstance(ep, dict):
                        event_perf = ep
            except Exception:
                # JSON artifact는 옵션(없어도 report_md로 충분)
                pass

        # 구현/데이터 한계(고정 컨텍스트) - LLM이 반드시 언급하도록 제공
        implementation_notes = {
            "data_sources": [
                "가격: daily_stock_price(open/high/low/close/volume) - adj_close는 사용하지 않음",
                "공시/지표: score_table_dart_idc",
            ],
            "known_limitations": [
                "유니버스 스크리닝 후 selected_symbols가 기간 내 고정(동적 재선정 없음)",
                "market_cap 스코어는 발행주식수 1,000만주 고정 추정(정확도 낮을 수 있음)",
                "event_type는 최근 30일이 아니라 최근 30건(tail 30) 합산",
                "리밸런싱은 전량청산 후 BUY 신호 종목만 재진입(신호 부족 시 현금 보유)",
            ],
        }

        llm_input = {
            "job_id": req.job_id,
            "user_id": req.user_id,
            "backtest_input_json": input_json,
            "backtest_output_json": output_json,
            "backtest_report_markdown": report_md,
            "trades_tail": trades_tail,
            "event_performance": event_perf,
            "implementation_notes": implementation_notes,
        }

        system = (
            "당신은 한국 주식 백테스트 결과를 해석하는 분석가입니다.\n"
            "반드시 한국어로 답변하고, 과장/확신을 피하며 근거를 제시하세요.\n"
            "출력은 지정된 JSON 스키마로만 응답합니다(추가 텍스트 금지)."
        )
        user = (
            "아래 입력(권장 조합 고정)을 바탕으로 백테스트 결과를 해석하세요.\n"
            "요구되는 섹션(요약/성과해석/트레이드특징/한계/다음실험)을 모두 채우세요.\n\n"
            f"{json.dumps(llm_input, ensure_ascii=False, indent=2)}"
        )

        llm = ChatOpenAI(model=model, temperature=0.2)
        llm_structured = llm.with_structured_output(BacktestInterpretationJson)
        analysis: BacktestInterpretationJson = await llm_structured.ainvoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )

        analysis_md = _render_markdown(
            job_id=req.job_id,
            input_json=input_json if isinstance(input_json, dict) else {},
            output_json=output_json if isinstance(output_json, dict) else {},
            analysis=analysis,
        )

        elapsed = time.time() - t0
        await _update_analysis_completed(
            job_id=req.job_id,
            user_id=req.user_id,
            analysis_md=analysis_md,
            analysis_json=analysis.model_dump(),
            elapsed_seconds=elapsed,
        )

        return {"ok": True, "job_id": req.job_id, "analysis_status": "completed"}

    except HTTPException as e:
        elapsed = time.time() - t0
        try:
            await _update_analysis_failed(
                job_id=req.job_id, user_id=req.user_id, error_message=str(e.detail), elapsed_seconds=elapsed
            )
        except Exception:
            pass
        raise
    except Exception as e:
        elapsed = time.time() - t0
        try:
            await _update_analysis_failed(
                job_id=req.job_id, user_id=req.user_id, error_message=str(e), elapsed_seconds=elapsed
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"backtest interpretation failed: {e}",
        ) from e

