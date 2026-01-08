import importlib


def test_stock_listing_uses_kis_master_loader(monkeypatch):
    # 모듈을 import 후 캐시를 초기화
    mod = importlib.import_module("multi_agent.supervisor_agent.agent")

    monkeypatch.setattr(mod, "_STOCK_LISTING_CACHE", None)

    # KIS 종목마스터 로더가 정상적으로 맵을 리턴한다고 가정
    monkeypatch.setattr(
        mod,
        "_load_stock_listing_from_kis_master",
        lambda: {"삼성전자": "005930", "카카오": "035720"},
    )

    listing = mod._get_stock_listing_map()
    assert listing["삼성전자"] == "005930"
    assert listing["카카오"] == "035720"


