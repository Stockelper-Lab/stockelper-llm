from __future__ import annotations

import os
import re
from typing import Any, Iterable

from neo4j import GraphDatabase

from stockelper_llm.core.json_safety import to_jsonable


_STOCK_CODE_PAT = re.compile(r"^\d{6}$")


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

