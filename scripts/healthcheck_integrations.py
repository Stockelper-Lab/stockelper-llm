from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional


# 프로젝트 루트의 `.env`를 자동 로드합니다.
# (값은 출력하지 않고, 테스트는 os.environ 기반으로 수행)
try:
    import dotenv  # type: ignore

    dotenv.load_dotenv(override=True)
except Exception:
    pass


@dataclass
class Result:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""


def _is_set(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _bool_env(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").lower().strip() in {"1", "true", "yes", "y"}


def _print_env_presence(names: Iterable[str]) -> None:
    print("== 환경변수 설정 여부(값은 출력하지 않음) ==")
    for n in names:
        print(f"- {n}: {'SET' if _is_set(n) else 'unset'}")
    print()


async def _test_openai() -> Result:
    if not _is_set("OPENAI_API_KEY"):
        return Result("OpenAI(ChatOpenAI)", "SKIP", "OPENAI_API_KEY 미설정")

    try:
        from langchain_openai import ChatOpenAI
        from langchain.messages import HumanMessage

        model_name = (os.getenv("STOCKELPER_LLM_MODEL") or os.getenv("STOCKELPER_MODEL") or "gpt-5.1").strip()
        llm = ChatOpenAI(model=model_name, temperature=0, max_tokens=16)
        t0 = time.time()
        resp = llm.invoke([HumanMessage("ping. 한국어로 1문장만 답해줘.")])
        dt = time.time() - t0
        text = getattr(resp, "content", "")
        ok = bool(str(text).strip())
        return Result("OpenAI(ChatOpenAI)", "PASS" if ok else "FAIL", f"model={model_name}, {dt:.2f}s")
    except Exception as e:
        return Result("OpenAI(ChatOpenAI)", "FAIL", f"{type(e).__name__}: {e}")


async def _test_postgres_user_db() -> Result:
    raw = (os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        return Result("PostgreSQL(stockelper_web)", "SKIP", "ASYNC_DATABASE_URL/DATABASE_URL 미설정")

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from stockelper_llm.core.db_urls import to_async_sqlalchemy_url

        async_db_url = to_async_sqlalchemy_url(raw)
        if not async_db_url:
            return Result("PostgreSQL(stockelper_web)", "FAIL", "DB URL 정규화 실패")

        engine = create_async_engine(async_db_url, echo=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return Result("PostgreSQL(stockelper_web)", "PASS", "SELECT 1 OK")
        finally:
            await engine.dispose()
    except Exception as e:
        return Result("PostgreSQL(stockelper_web)", "FAIL", f"{type(e).__name__}: {e}")


def _test_postgres_checkpoint_db_sync() -> Result:
    raw = (
        os.getenv("CHECKPOINT_DATABASE_URI")
        or os.getenv("DATABASE_URL")
        or os.getenv("ASYNC_DATABASE_URL")
        or ""
    ).strip()
    if not raw:
        return Result("PostgreSQL(checkpoint)", "SKIP", "CHECKPOINT_DATABASE_URI/DATABASE_URL 미설정")

    try:
        import psycopg

        from stockelper_llm.core.db_urls import to_postgresql_conninfo

        conninfo = to_postgresql_conninfo(raw)
        if not conninfo:
            return Result("PostgreSQL(checkpoint)", "FAIL", "conninfo 정규화 실패")

        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                _ = cur.fetchone()
        return Result("PostgreSQL(checkpoint)", "PASS", "SELECT 1 OK")
    except Exception as e:
        return Result("PostgreSQL(checkpoint)", "FAIL", f"{type(e).__name__}: {e}")


def _test_kis_master_listing() -> Result:
    try:
        from stockelper_llm.integrations.stock_listing import get_stock_listing_map

        t0 = time.time()
        mapping = get_stock_listing_map()
        dt = time.time() - t0
        if not mapping:
            return Result("KIS 종목마스터(.mst.zip) 다운로드", "FAIL", f"empty mapping ({dt:.2f}s)")
        return Result("KIS 종목마스터(.mst.zip) 다운로드", "PASS", f"rows={len(mapping)} ({dt:.2f}s)")
    except Exception as e:
        return Result("KIS 종목마스터(.mst.zip) 다운로드", "FAIL", f"{type(e).__name__}: {e}")


async def _test_kis_balance() -> Result:
    raw = (os.getenv("ASYNC_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        return Result("KIS 잔고조회(inquire-balance)", "SKIP", "DB 미설정(사용자 자격증명 조회 불가)")

    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        from stockelper_llm.core.db_urls import to_async_sqlalchemy_url
        from stockelper_llm.integrations.kis import check_account_balance, get_user_kis_context

        user_id = int(os.getenv("STOCKELPER_TEST_USER_ID", "2"))
        async_db_url = to_async_sqlalchemy_url(raw)
        if not async_db_url:
            return Result("KIS 잔고조회(inquire-balance)", "FAIL", "DB URL 정규화 실패")

        engine = create_async_engine(async_db_url, echo=False)
        try:
            user_info = await get_user_kis_context(engine, user_id, require=False)
            if not user_info:
                return Result("KIS 잔고조회(inquire-balance)", "SKIP", f"user_id={user_id} 사용자 없음/정보 없음")

            # get_user_kis_context 내부에서 토큰 발급까지 수행됨(필요 시)
            data = await check_account_balance(
                user_info["kis_app_key"],
                user_info["kis_app_secret"],
                user_info["kis_access_token"],
                user_info["account_no"],
            )
            if isinstance(data, dict):
                return Result("KIS 잔고조회(inquire-balance)", "PASS", "cash/total_eval OK")
            return Result("KIS 잔고조회(inquire-balance)", "FAIL", f"response={data!r}")
        finally:
            await engine.dispose()
    except Exception as e:
        return Result("KIS 잔고조회(inquire-balance)", "FAIL", f"{type(e).__name__}: {e}")


def _test_neo4j() -> Result:
    if not (_is_set("NEO4J_URI") and _is_set("NEO4J_USER") and _is_set("NEO4J_PASSWORD")):
        return Result("Neo4j", "SKIP", "NEO4J_URI/USER/PASSWORD 미설정")

    try:
        from neo4j import GraphDatabase

        uri = os.getenv("NEO4J_URI") or ""
        user = os.getenv("NEO4J_USER") or ""
        pw = os.getenv("NEO4J_PASSWORD") or ""
        driver = GraphDatabase.driver(uri, auth=(user, pw))
        try:
            with driver.session() as session:
                rec = session.run("RETURN 1 as ok").single()
                ok = rec and rec.get("ok") == 1
            return Result("Neo4j", "PASS" if ok else "FAIL", "RETURN 1 OK" if ok else "query failed")
        finally:
            driver.close()
    except Exception as e:
        return Result("Neo4j", "FAIL", f"{type(e).__name__}: {e}")


async def _test_opendart() -> Result:
    if not _is_set("OPEN_DART_API_KEY"):
        return Result("DART(OpenDART)", "SKIP", "OPEN_DART_API_KEY 미설정")
    try:
        import httpx

        key = os.getenv("OPEN_DART_API_KEY") or ""
        url = "https://opendart.fss.or.kr/api/list.json"
        params = {"crtfc_key": key, "page_no": 1, "page_count": 1}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
        status = data.get("status")
        if resp.status_code == 200 and status in {"000", "013"}:
            # 013 = 조회 데이터 없음(성공 응답)
            return Result("DART(OpenDART)", "PASS", f"http={resp.status_code}, status={status}")
        return Result("DART(OpenDART)", "FAIL", f"http={resp.status_code}, status={status}, msg={data.get('message')}")
    except Exception as e:
        return Result("DART(OpenDART)", "FAIL", f"{type(e).__name__}: {e}")


async def _test_openrouter() -> Result:
    if not _is_set("OPENROUTER_API_KEY"):
        return Result("OpenRouter(Perplexity 등)", "SKIP", "OPENROUTER_API_KEY 미설정")
    try:
        import httpx

        key = os.getenv("OPENROUTER_API_KEY") or ""
        url = "https://openrouter.ai/api/v1/models"
        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return Result("OpenRouter(Perplexity 등)", "PASS", "models endpoint OK")
        return Result("OpenRouter(Perplexity 등)", "FAIL", f"http={resp.status_code}")
    except Exception as e:
        return Result("OpenRouter(Perplexity 등)", "FAIL", f"{type(e).__name__}: {e}")


async def _test_youtube() -> Result:
    if not _is_set("YOUTUBE_API_KEY"):
        return Result("YouTube Data API", "SKIP", "YOUTUBE_API_KEY 미설정")
    try:
        import httpx

        key = os.getenv("YOUTUBE_API_KEY") or ""
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part": "snippet", "q": "삼성전자", "maxResults": 1, "type": "video", "key": key}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
        if resp.status_code == 200 and isinstance(data.get("items"), list):
            return Result("YouTube Data API", "PASS", f"items={len(data.get('items') or [])}")
        return Result("YouTube Data API", "FAIL", f"http={resp.status_code}, error={data.get('error')}")
    except Exception as e:
        return Result("YouTube Data API", "FAIL", f"{type(e).__name__}: {e}")


async def _test_optional_service(name: str, base_url_env: str) -> Result:
    base = (os.getenv(base_url_env) or "").strip().rstrip("/")
    if not base:
        return Result(name, "SKIP", f"{base_url_env} 미설정")

    # side-effect 방지: 추천/실행 엔드포인트를 호출하지 않고 /health만 시도
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/health")
        if resp.status_code < 400:
            return Result(name, "PASS", f"GET {base}/health -> {resp.status_code}")
        return Result(name, "FAIL", f"GET {base}/health -> {resp.status_code}")
    except Exception as e:
        return Result(name, "FAIL", f"{type(e).__name__}: {e}")


async def main() -> int:
    _print_env_presence(
        [
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "OPEN_DART_API_KEY",
            "YOUTUBE_API_KEY",
            "DATABASE_URL",
            "ASYNC_DATABASE_URL",
            "CHECKPOINT_DATABASE_URI",
            "NEO4J_URI",
            "NEO4J_USER",
            "NEO4J_PASSWORD",
            "LANGFUSE_ENABLED",
            "LANGFUSE_HOST",
            "STOCKELPER_PORTFOLIO_URL",
            "STOCKELPER_BACKTESTING_URL",
            "STOCKELPER_TEST_USER_ID",
        ]
    )

    results: list[Result] = []

    # 순서: 내부 인프라 → 외부 API
    results.append(await _test_postgres_user_db())
    results.append(_test_postgres_checkpoint_db_sync())
    results.append(_test_neo4j())
    results.append(_test_kis_master_listing())
    results.append(await _test_kis_balance())

    results.append(await _test_openai())
    results.append(await _test_opendart())
    results.append(await _test_openrouter())
    results.append(await _test_youtube())

    results.append(await _test_optional_service("Portfolio Service", "STOCKELPER_PORTFOLIO_URL"))
    results.append(await _test_optional_service("Backtesting Service", "STOCKELPER_BACKTESTING_URL"))

    print("== 테스트 결과 ==")
    for r in results:
        print(f"[{r.status}] {r.name}: {r.detail}")

    failed = [r for r in results if r.status == "FAIL"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

