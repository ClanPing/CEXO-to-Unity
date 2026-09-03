from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    app_path = repo_root / "app" / "app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    return subprocess.call(command, cwd=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
