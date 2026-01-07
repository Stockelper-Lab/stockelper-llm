from multi_agent.supervisor_agent.agent import _parse_kis_mst_text


def test_parse_kis_mst_text_extracts_name_and_code():
    # part1: 단축코드(9) + 표준코드(12) + 한글명(가변)
    # part2: 고정폭(228)
    row = "005930   " + "KR7005930003" + "삼성전자" + (" " * 228)
    mapping = _parse_kis_mst_text(row + "\n")
    assert mapping["삼성전자"] == "005930"


