import importlib


def test_stock_listing_fallback_to_kind(monkeypatch):
    # 모듈을 import 후 캐시를 초기화
    mod = importlib.import_module("multi_agent.supervisor_agent.agent")

    # FinanceDataReader가 깨지는 상황을 시뮬레이션
    def _raise(*args, **kwargs):
        raise RuntimeError("FDR failed")

    monkeypatch.setattr(mod.fdr, "StockListing", _raise)
    monkeypatch.setattr(mod, "_STOCK_LISTING_CACHE", None)

    # KIND 폴백이 정상적으로 맵을 리턴한다고 가정
    monkeypatch.setattr(
        mod,
        "_load_stock_listing_from_kind",
        lambda: {"삼성전자": "005930", "카카오": "035720"},
    )

    listing = mod._get_stock_listing_map()
    assert listing["삼성전자"] == "005930"
    assert listing["카카오"] == "035720"


