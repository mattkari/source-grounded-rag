"""Write `docs/workflows.md` from `workflows.py`.

    python scripts/workflow_diagrams.py            # rewrite the file
    python scripts/workflow_diagrams.py --check    # exit 1 if the file is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import workflows  # noqa: E402

TARGET = ROOT / "docs" / "workflows.md"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    wanted = workflows.document()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != wanted:
            print("docs/workflows.md is out of date. Run: python scripts/workflow_diagrams.py")
            return 1
        return 0
    TARGET.write_text(wanted, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
