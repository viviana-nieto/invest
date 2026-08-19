"""Make the repo root and the orchestration/ dir importable in tests.

`orchestration/run.py` uses local imports (`from providers import ...`), so the
orchestration directory must be on sys.path — mirroring how the runner is invoked
in production (`python -m orchestration.run` from inside that directory).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestration"))
