from __future__ import annotations

import sys
from pathlib import Path


# 테스트 실행 시에도 `python src/main.py`와 동일하게 `src/`를 import 루트로 사용합니다.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
sys.path.insert(0, str(_SRC))



