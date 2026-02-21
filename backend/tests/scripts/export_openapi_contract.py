#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

os.environ.setdefault("ALLOW_MISSING_FIREBASE", "1")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main() -> int:
    out_dir = ROOT / "tests" / "catalog"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "openapi_snapshot.json"

    schema = app.openapi()
    with out_file.open("w", encoding="utf-8") as handle:
        json.dump(schema, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"OpenAPI contract exported to {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
