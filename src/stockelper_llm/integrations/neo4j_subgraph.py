from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable

from neo4j import GraphDatabase

from stockelper_llm.core.json_safety import to_jsonable

logger = logging.getLogger(__name__)

_STOCK_CODE_PAT = re.compile(r"^\d{6}$")


# ============================================================================
# 그래프 스키마 정의 (LLM Cypher 생성용)
# ============================================================================

GRAPH_SCHEMA = """
Node types:
- Company
    - corp_name: 회사의 이름 (예: SK하이닉스)
    - stock_code: 회사의 종목코드 6자리 (예: 000660)
    - corp_code: 회사의 고유 코드 (예: 00164779)
    - stock_nm_eng: 회사의 영문명 (예: SK Hynix Inc.)
    - listing_dt: 회사의 상장일 (예: 2021-03-01)
    - capital_stock: 회사의 자본금
    - outstanding_shares: 발행주식수
    - market_nm: 회사의 시장 (예: 코스피)
- Sector
    - sector_name: 업종명 (예: 반도체)
- Event
    - event_id: 이벤트 고유 ID
    - disclosure_name: 공시명 (예: "주주총회소집공고")
    - disclosure_category: 공시 카테고리
    - report_type: 보고서 유형
    - disclosure_type_code: 공시유형코드
    - source: 출처
    - updated_at: 업데이트 일시 (ISO string)
- Document
    - rcept_no: 접수번호
    - report_nm: 보고서명
    - rcept_dt: 접수일
    - url: 공시 문서 URL
- StockPrice
    - stock_code: 종목코드
    - traded_at: 거래일 (예: 2024-01-15)
    - stck_prpr: 종가
    - stck_oprc: 시가
    - stck_hgpr: 고가
    - stck_lwpr: 저가
    - volume: 거래량
- Date
    - date: 날짜 (예: 2024-01-15)
- EventDate
    - date: 이벤트 발생 날짜
- PriceDate
    - date: 가격 기록 날짜
- FinancialStatements
    - revenue: 매출액
    - operating_income: 영업이익
    - net_income: 순이익
    - total_assets: 총자산
    - total_liabilities: 총부채
    - total_capital: 총자본
    - capital_stock: 자본금
- Indicator
    - eps: 주당순이익
    - bps: 주당자본
    - per: 주가수익비율
    - pbr: 주가자산비율
- News
    - id: 뉴스의 고유 ID
    - date: 뉴스의 날짜
    - title: 뉴스의 제목
    - body: 뉴스의 본문
    - stock_nm: 관련 종목명

Relationships:
- (Company)-[:INVOLVED_IN]->(Event): 회사가 관련된 공시/이벤트
- (Event)-[:REPORTED_BY]->(Document): 이벤트에 대한 공시 문서
- (Event)-[:OCCURRED_ON]->(EventDate): 이벤트 발생 날짜
- (EventDate)-[:IS_DATE]->(Date): 날짜 노드 연결
- (Company)-[:HAS_STOCK_PRICE]->(StockPrice): 회사의 주가 정보
- (StockPrice)-[:RECORDED_ON]->(PriceDate): 주가 기록 날짜
- (PriceDate)-[:IS_DATE]->(Date): 날짜 노드 연결
- (Company)-[:HAS_FINANCIAL_STATEMENTS]->(FinancialStatements): 재무제표
- (Company)-[:HAS_INDICATOR]->(Indicator): 투자지표
- (Company)-[:BELONGS_TO]->(Sector): 업종 분류
- (Company)-[:HAS_COMPETITOR]->(Company): 경쟁사 관계
- (News)-[:PUBLISHED_ON]->(Date): 뉴스 발행일
- (News)-[:MENTIONS_STOCKS]->(Company): 뉴스에서 언급된 종목

Query Guidelines:
- 종목코드는 6자리 문자열입니다 (예: '000660')
- 날짜 비교는 문자열 비교를 사용합니다 (예: sp.traded_at >= '2024-01-01')
- 최신 데이터를 먼저 보려면 ORDER BY ... DESC를 사용합니다
- LIMIT을 적절히 사용하여 결과 수를 제한합니다 (기본 10~20)
"""


# ============================================================================
# 의도(Intent) 분류를 위한 예시 의도 카테고리
# ============================================================================

INTENT_CATEGORIES = {
    "company_info": "회사 기본 정보 조회 (회사명, 종목코드, 상장일, 시장 등)",
    "stock_price": "주가/시세 정보 조회 (현재가, 종가, 시가, 고가, 저가, 거래량 등)",
    "event_disclosure": "공시/이벤트 정보 조회 (공시명, 공시 카테고리, 보고서 등)",
    "financial_statement": "재무제표 정보 조회 (매출액, 영업이익, 순이익, 자산, 부채 등)",
    "indicator": "투자지표 조회 (EPS, BPS, PER, PBR 등)",
    "sector": "업종/섹터 정보 조회",
    "competitor": "경쟁사 관계 조회",
    "news": "뉴스/기사 조회",
    "timeline": "시계열/타임라인 분석 (특정 기간 데이터)",
    "relationship": "엔티티 간 관계/연결 분석",
    "comparison": "종목 간 비교 분석",
    "general": "일반적인 질문/기타",
}


def _neo4j_env() -> tuple[str, str, str] | None:
    uri = (os.getenv("NEO4J_URI") or "").strip()
    user = (os.getenv("NEO4J_USER") or "").strip()
    password = (os.getenv("NEO4J_PASSWORD") or "").strip()
    if not (uri and user and password):
        return None
    return uri, user, password


def _first_label(labels: Iterable[str] | None) -> str:
    try:
        return next(iter(labels or ())) or "Node"
    except Exception:
        return "Node"


def _as_props(obj: Any) -> dict[str, Any]:
    try:
        return dict(obj)  # neo4j.Node는 dict로 변환 가능
    except Exception:
        return {}


def _node_name(label: str, props: dict[str, Any]) -> str:
    """FE에서 node_name으로 id를 만들기 때문에, 충돌을 피하도록 유니크 이름을 만든다."""
    if label == "Company":
        return str(props.get("corp_name") or props.get("stock_code") or props.get("corp_code") or "Company")

    if label == "Event":
        base = str(props.get("disclosure_name") or props.get("event_id") or "Event")
        eid = props.get("event_id")
        if eid and str(eid) not in base:
            return f"{base} ({eid})"
        return base

    if label == "Document":
        title = str(props.get("report_nm") or props.get("title") or props.get("rcept_no") or "Document")
        rcept_no = props.get("rcept_no")
        if rcept_no and str(rcept_no) not in title:
            return f"{title} ({rcept_no})"
        return title

    if label in {"StockPrice"}:
        stock_code = props.get("stock_code")
        traded_at = props.get("traded_at") or props.get("date")
        if stock_code and traded_at:
            return f"StockPrice:{stock_code}@{traded_at}"
        if traded_at:
            return f"StockPrice:{traded_at}"
        return "StockPrice"

    if label.endswith("Date") or label == "Date":
        date = props.get("date") or props.get("traded_at") or props.get("rcept_dt")
        if date:
            return f"{label}:{date}"
        return label

    # 기타 라벨은 대표키처럼 쓸만한 필드를 붙여 충돌을 줄인다.
    for key in ("name", "metric", "metric_id", "id", "isin", "stock_code", "corp_code"):
        if props.get(key):
            return f"{label}:{props.get(key)}"
    return label


def _add_node(nodes: dict[str, dict], label: str, props: dict[str, Any]) -> tuple[str, str]:
    name = _node_name(label, props)
    key = f"{label}::{name}"
    if key not in nodes:
        nodes[key] = {"node_type": label, "node_name": name, "properties": to_jsonable(props)}
    return label, name


def _add_relation(relations: dict[tuple[str, str, str, str, str], dict], *, start: tuple[str, str], rel_type: str, end: tuple[str, str]) -> None:
    (s_type, s_name) = start
    (e_type, e_name) = end
    key = (s_type, s_name, rel_type, e_type, e_name)
    if key in relations:
        return
    relations[key] = {
        "start": {"name": s_name, "type": s_type},
        "relationship": rel_type,
        "end": {"name": e_name, "type": e_type},
    }


def _resolve_company_match(
    *,
    stock_code: str | None,
    company_name: str | None,
) -> tuple[str, str] | None:
    sc = (stock_code or "").strip()
    if sc and _STOCK_CODE_PAT.match(sc):
        return "stock_code", sc

    name = (company_name or "").strip()
    if name:
        # KG의 Company 핵심 키는 corp_name / stock_code / corp_code
        return "corp_name", name

    return None


def get_subgraph_by_stock_code(
    stock_code: str,
    *,
    max_events: int = 10,
    max_prices: int = 20,
) -> dict:
    """현재 온톨로지(Company/Event/Document/StockPrice/Date 축)에 맞춘 서브그래프 조회."""
    return get_subgraph(stock_code=stock_code, company_name=None, max_events=max_events, max_prices=max_prices)


def get_subgraph_by_company_name(
    company_name: str,
    *,
    max_events: int = 10,
    max_prices: int = 20,
) -> dict:
    return get_subgraph(stock_code=None, company_name=company_name, max_events=max_events, max_prices=max_prices)


def get_subgraph(
    *,
    stock_code: str | None,
    company_name: str | None,
    max_events: int = 10,
    max_prices: int = 20,
) -> dict:
    """종목(코드/이름) 기준으로 서브그래프를 조회합니다.

    반환 포맷은 FE(`stockelper-fe`)가 기대하는 형태를 유지합니다:
    {"node": [...], "relation": [...]}
    """
    env = _neo4j_env()
    match = _resolve_company_match(stock_code=stock_code, company_name=company_name)
    if not env or not match:
        return {}

    uri, user, password = env
    match_key, match_val = match

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        nodes: dict[str, dict] = {}
        relations: dict[tuple[str, str, str, str, str], dict] = {}

        with driver.session() as session:
            # 1) Company 기준점
            rec = session.run(
                f"MATCH (c:Company {{{match_key}: $v}}) RETURN c LIMIT 1",
                v=match_val,
            ).single()
            if not rec:
                return {}

            c = rec["c"]
            c_label = _first_label(getattr(c, "labels", None))
            c_props = _as_props(c)
            c_node = _add_node(nodes, c_label, c_props)

            resolved_stock_code = str(c_props.get("stock_code") or "").strip()
            if not (resolved_stock_code and _STOCK_CODE_PAT.match(resolved_stock_code)):
                # 그래프가 stock_code를 들고 있지 않은 경우라도, 이벤트/시세는 (c)-[]-> 로 따라갈 수 있으므로 계속 진행
                resolved_stock_code = ""

            # 2) 이벤트/문서/이벤트 날짜(최근 이벤트 일부만)
            event_rows = session.run(
                """
                MATCH (c:Company {stock_code: $stock_code})-[:INVOLVED_IN]->(e:Event)
                OPTIONAL MATCH (e)-[:REPORTED_BY]->(d:Document)
                OPTIONAL MATCH (e)-[:OCCURRED_ON]->(ed:EventDate)-[:IS_DATE]->(dt:Date)
                RETURN e, d, ed, dt
                ORDER BY coalesce(e.updated_at, datetime('1970-01-01')) DESC
                LIMIT $limit
                """,
                stock_code=resolved_stock_code or c_props.get("stock_code") or "",
                limit=max(0, int(max_events)),
            )
            for row in event_rows:
                e = row.get("e")
                if e is not None:
                    e_label = _first_label(getattr(e, "labels", None))
                    e_node = _add_node(nodes, e_label, _as_props(e))
                    _add_relation(relations, start=c_node, rel_type="INVOLVED_IN", end=e_node)

                    d = row.get("d")
                    if d is not None:
                        d_label = _first_label(getattr(d, "labels", None))
                        d_node = _add_node(nodes, d_label, _as_props(d))
                        _add_relation(relations, start=e_node, rel_type="REPORTED_BY", end=d_node)

                    ed = row.get("ed")
                    if ed is not None:
                        ed_label = _first_label(getattr(ed, "labels", None))
                        ed_node = _add_node(nodes, ed_label, _as_props(ed))
                        _add_relation(relations, start=e_node, rel_type="OCCURRED_ON", end=ed_node)

                        dt = row.get("dt")
                        if dt is not None:
                            dt_label = _first_label(getattr(dt, "labels", None))
                            dt_node = _add_node(nodes, dt_label, _as_props(dt))
                            _add_relation(relations, start=ed_node, rel_type="IS_DATE", end=dt_node)

            # 3) 시세(최근 일부만)
            price_rows = session.run(
                """
                MATCH (c:Company {stock_code: $stock_code})-[:HAS_STOCK_PRICE]->(sp:StockPrice)
                OPTIONAL MATCH (sp)-[:RECORDED_ON]->(pd:PriceDate)-[:IS_DATE]->(dt:Date)
                RETURN sp, pd, dt
                ORDER BY sp.traded_at DESC
                LIMIT $limit
                """,
                stock_code=resolved_stock_code or c_props.get("stock_code") or "",
                limit=max(0, int(max_prices)),
            )
            for row in price_rows:
                sp = row.get("sp")
                if sp is None:
                    continue
                sp_label = _first_label(getattr(sp, "labels", None))
                sp_node = _add_node(nodes, sp_label, _as_props(sp))
                _add_relation(relations, start=c_node, rel_type="HAS_STOCK_PRICE", end=sp_node)

                pd = row.get("pd")
                if pd is not None:
                    pd_label = _first_label(getattr(pd, "labels", None))
                    pd_node = _add_node(nodes, pd_label, _as_props(pd))
                    _add_relation(relations, start=sp_node, rel_type="RECORDED_ON", end=pd_node)

                    dt = row.get("dt")
                    if dt is not None:
                        dt_label = _first_label(getattr(dt, "labels", None))
                        dt_node = _add_node(nodes, dt_label, _as_props(dt))
                        _add_relation(relations, start=pd_node, rel_type="IS_DATE", end=dt_node)

        return {"node": list(nodes.values()), "relation": list(relations.values())}
    except Exception:
        # 서브그래프는 부가 데이터이므로 실패 시 조용히 빈 dict 반환
        return {}
    finally:
        try:
            driver.close()
        except Exception:
            pass


def get_subgraph_by_stock_name(stock_name: str) -> dict:
    """레거시 호환: stock_name을 corp_name으로 간주하여 조회합니다."""
    return get_subgraph_by_company_name(stock_name or "")


# ============================================================================
# 동적 Cypher 쿼리 실행 (GraphRAG용)
# ============================================================================


def get_graph_schema() -> str:
    """그래프 스키마를 반환합니다. LLM Cypher 쿼리 생성 시 참조용."""
    return GRAPH_SCHEMA


def get_intent_categories() -> dict[str, str]:
    """의도(Intent) 카테고리를 반환합니다."""
    return INTENT_CATEGORIES


def execute_cypher_query(
    cypher: str,
    *,
    parameters: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict:
    """동적으로 Cypher 쿼리를 실행하고 결과를 서브그래프 포맷으로 변환합니다.

    Args:
        cypher: 실행할 Cypher 쿼리
        parameters: 쿼리 파라미터 (선택)
        limit: 최대 결과 행 수

    Returns:
        {"node": [...], "relation": [...], "raw_results": [...], "cypher": str, "error": str | None}
    """
    env = _neo4j_env()
    if not env:
        return {
            "node": [],
            "relation": [],
            "raw_results": [],
            "cypher": cypher,
            "error": "Neo4j 설정(NEO4J_URI/USER/PASSWORD)이 없습니다.",
        }

    uri, user, password = env
    params = parameters or {}

    # 보안: 위험한 쿼리 패턴 차단
    cypher_upper = cypher.upper()
    dangerous_keywords = ["DELETE", "REMOVE", "DROP", "CREATE", "MERGE", "SET", "DETACH"]
    for kw in dangerous_keywords:
        if kw in cypher_upper:
            return {
                "node": [],
                "relation": [],
                "raw_results": [],
                "cypher": cypher,
                "error": f"보안 정책: {kw} 키워드를 포함한 쿼리는 실행할 수 없습니다.",
            }

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        nodes: dict[str, dict] = {}
        relations: dict[tuple[str, str, str, str, str], dict] = {}
        raw_results: list[dict] = []

        with driver.session() as session:
            result = session.run(cypher, params)
            records = list(result)[:limit]

            for record in records:
                row_data: dict[str, Any] = {}

                for key in record.keys():
                    value = record[key]

                    # Neo4j Node 처리
                    if hasattr(value, "labels"):
                        label = _first_label(getattr(value, "labels", None))
                        props = _as_props(value)
                        node_key = _add_node(nodes, label, props)
                        row_data[key] = {
                            "type": "node",
                            "label": label,
                            "properties": to_jsonable(props),
                        }

                    # Neo4j Relationship 처리
                    elif hasattr(value, "type") and hasattr(value, "start_node"):
                        rel_type = value.type
                        start_node = value.start_node
                        end_node = value.end_node

                        start_label = _first_label(getattr(start_node, "labels", None))
                        start_props = _as_props(start_node)
                        start_key = _add_node(nodes, start_label, start_props)

                        end_label = _first_label(getattr(end_node, "labels", None))
                        end_props = _as_props(end_node)
                        end_key = _add_node(nodes, end_label, end_props)

                        _add_relation(relations, start=start_key, rel_type=rel_type, end=end_key)

                        row_data[key] = {
                            "type": "relationship",
                            "rel_type": rel_type,
                            "start": {"label": start_label, "properties": to_jsonable(start_props)},
                            "end": {"label": end_label, "properties": to_jsonable(end_props)},
                        }

                    # Path 처리
                    elif hasattr(value, "nodes") and hasattr(value, "relationships"):
                        path_nodes = []
                        for n in value.nodes:
                            label = _first_label(getattr(n, "labels", None))
                            props = _as_props(n)
                            _add_node(nodes, label, props)
                            path_nodes.append({"label": label, "properties": to_jsonable(props)})

                        for rel in value.relationships:
                            rel_type = rel.type
                            start_node = rel.start_node
                            end_node = rel.end_node

                            start_label = _first_label(getattr(start_node, "labels", None))
                            start_props = _as_props(start_node)
                            start_key = _add_node(nodes, start_label, start_props)

                            end_label = _first_label(getattr(end_node, "labels", None))
                            end_props = _as_props(end_node)
                            end_key = _add_node(nodes, end_label, end_props)

                            _add_relation(relations, start=start_key, rel_type=rel_type, end=end_key)

                        row_data[key] = {"type": "path", "nodes": path_nodes}

                    # 일반 값 처리
                    else:
                        row_data[key] = to_jsonable(value)

                raw_results.append(row_data)

        return {
            "node": list(nodes.values()),
            "relation": list(relations.values()),
            "raw_results": raw_results,
            "cypher": cypher,
            "error": None,
        }

    except Exception as e:
        logger.exception("Cypher query execution failed: %s", cypher)
        return {
            "node": [],
            "relation": [],
            "raw_results": [],
            "cypher": cypher,
            "error": f"쿼리 실행 오류: {type(e).__name__}: {e}",
        }
    finally:
        try:
            driver.close()
        except Exception:
            pass


def validate_cypher_query(cypher: str) -> dict[str, Any]:
    """Cypher 쿼리의 유효성을 검사합니다 (EXPLAIN 사용).

    Returns:
        {"valid": bool, "error": str | None}
    """
    env = _neo4j_env()
    if not env:
        return {"valid": False, "error": "Neo4j 설정이 없습니다."}

    uri, user, password = env

    # 보안 검사
    cypher_upper = cypher.upper()
    dangerous_keywords = ["DELETE", "REMOVE", "DROP", "CREATE", "MERGE", "SET", "DETACH"]
    for kw in dangerous_keywords:
        if kw in cypher_upper:
            return {"valid": False, "error": f"보안 정책: {kw} 키워드는 허용되지 않습니다."}

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            # EXPLAIN으로 쿼리 유효성만 검사 (실제 실행 X)
            session.run(f"EXPLAIN {cypher}")
        return {"valid": True, "error": None}
    except Exception as e:
        return {"valid": False, "error": str(e)}
    finally:
        try:
            driver.close()
        except Exception:
            pass


def format_subgraph_for_context(subgraph: dict, *, max_nodes: int = 30, max_relations: int = 50) -> str:
    """서브그래프를 LLM 컨텍스트용 텍스트로 변환합니다.

    Args:
        subgraph: {"node": [...], "relation": [...]} 포맷
        max_nodes: 포함할 최대 노드 수
        max_relations: 포함할 최대 관계 수

    Returns:
        LLM이 읽기 쉬운 텍스트 형식의 그래프 정보
    """
    lines: list[str] = []

    nodes = (subgraph.get("node") or [])[:max_nodes]
    relations = (subgraph.get("relation") or [])[:max_relations]
    raw_results = subgraph.get("raw_results") or []

    if not nodes and not raw_results:
        return "그래프에서 관련 데이터를 찾지 못했습니다."

    # 노드 정보 요약
    if nodes:
        lines.append("=== 그래프 노드 정보 ===")
        nodes_by_type: dict[str, list[dict]] = {}
        for n in nodes:
            nt = n.get("node_type", "Unknown")
            nodes_by_type.setdefault(nt, []).append(n)

        for node_type, type_nodes in nodes_by_type.items():
            lines.append(f"\n[{node_type}] ({len(type_nodes)}개)")
            for n in type_nodes[:10]:  # 타입당 최대 10개
                props = n.get("properties") or {}
                name = n.get("node_name", "")
                if props:
                    # 주요 속성만 표시
                    key_props = {k: v for k, v in props.items() if v is not None and k not in {"id", "element_id"}}
                    if key_props:
                        props_str = ", ".join(f"{k}={v}" for k, v in list(key_props.items())[:5])
                        lines.append(f"  - {name}: {props_str}")
                    else:
                        lines.append(f"  - {name}")
                else:
                    lines.append(f"  - {name}")

    # 관계 정보 요약
    if relations:
        lines.append("\n=== 그래프 관계 정보 ===")
        rel_summary: dict[str, int] = {}
        for r in relations:
            rel_type = r.get("relationship", "UNKNOWN")
            rel_summary[rel_type] = rel_summary.get(rel_type, 0) + 1

        for rel_type, count in rel_summary.items():
            lines.append(f"  - {rel_type}: {count}개")

        # 샘플 관계 표시
        lines.append("\n샘플 관계:")
        for r in relations[:10]:
            start = r.get("start", {})
            end = r.get("end", {})
            rel_type = r.get("relationship", "UNKNOWN")
            lines.append(f"  ({start.get('name', '?')}) -[{rel_type}]-> ({end.get('name', '?')})")

    # Raw 결과 요약 (테이블 형식 데이터)
    if raw_results:
        lines.append("\n=== 쿼리 결과 데이터 ===")
        for i, row in enumerate(raw_results[:20]):  # 최대 20행
            row_items = []
            for k, v in row.items():
                if isinstance(v, dict) and v.get("type") == "node":
                    row_items.append(f"{k}: [{v.get('label')}]")
                elif isinstance(v, dict) and v.get("type") == "relationship":
                    row_items.append(f"{k}: -{v.get('rel_type')}->")
                else:
                    row_items.append(f"{k}: {v}")
            lines.append(f"  {i+1}. {', '.join(row_items)}")

    return "\n".join(lines)

