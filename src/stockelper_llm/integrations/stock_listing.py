from __future__ import annotations

import difflib
import os
from typing import Optional

_STOCK_LISTING_CACHE: Optional[dict[str, str]] = None


def _debug_errors_enabled() -> bool:
    return os.getenv("DEBUG_ERRORS", "false").lower() not in {"0", "false", "no"}


def _parse_kis_mst_text(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not text:
        return mapping

    for raw in text.splitlines():
        row = (raw or "").rstrip("\r\n")
        if not row:
            continue
        if len(row) < (21 + 1 + 228):
            continue

        part1 = row[:-228]
        if len(part1) < 21:
            continue

        code_raw = part1[0:9].strip()
        name = part1[21:].strip()
        if not code_raw or not name:
            continue

        code_digits = "".join(ch for ch in code_raw if ch.isdigit())
        if not code_digits:
            continue
        code_digits = code_digits.zfill(6)
        if not (len(code_digits) == 6 and code_digits.isdigit()):
            continue

        mapping.setdefault(name, code_digits)

    return mapping


def _load_stock_listing_from_kis_master() -> dict[str, str]:
    import io
    import zipfile

    import requests

    default_urls = [
        "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
        "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
        "https://new.real.download.dws.co.kr/common/master/konex_code.mst.zip",
    ]
    raw_urls = (os.getenv("KIS_STOCK_MASTER_URLS") or "").strip()
    urls = (
        [u.strip() for u in raw_urls.split(",") if u.strip()]
        if raw_urls
        else default_urls
    )

    headers = {
        "User-Agent": os.getenv(
            "STOCK_LISTING_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        )
    }
    timeout_s = float(os.getenv("KIS_STOCK_MASTER_TIMEOUT", "30") or 30)

    mapping: dict[str, str] = {}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout_s)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                mst_name = next(
                    (n for n in zf.namelist() if n.lower().endswith(".mst")), None
                )
                if not mst_name:
                    raise ValueError("zip 내부에 .mst 파일이 없습니다.")
                mst_bytes = zf.read(mst_name)

            text = mst_bytes.decode("cp949", errors="replace")
            part = _parse_kis_mst_text(text)
            for k, v in part.items():
                mapping.setdefault(k, v)
        except Exception:
            if _debug_errors_enabled():
                raise
            # 운영에서는 조용히 실패(빈 맵) 허용
            continue

    return mapping


def get_stock_listing_map() -> dict[str, str]:
    global _STOCK_LISTING_CACHE
    if _STOCK_LISTING_CACHE is None:
        _STOCK_LISTING_CACHE = _load_stock_listing_from_kis_master()
    return _STOCK_LISTING_CACHE


def lookup_stock_code(stock_name: str) -> str | None:
    if not stock_name:
        return None
    listing = get_stock_listing_map()
    return listing.get(stock_name.strip())


def find_similar_companies(company_name: str, top_n: int = 10) -> dict[str, str]:
    listing = get_stock_listing_map()
    if not listing:
        return {}

    similarities: list[tuple[str, float]] = []
    for name in listing.keys():
        ratio = difflib.SequenceMatcher(None, company_name, name).ratio()
        similarities.append((name, ratio))

    similarities.sort(key=lambda x: x[1], reverse=True)
    top_companies = similarities[:top_n]

    return {name: listing[name] for name, _ in top_companies}
