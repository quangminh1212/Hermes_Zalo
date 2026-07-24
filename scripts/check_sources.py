#!/usr/bin/env python3
"""Verify sources/catalog.yaml evidence paths."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    data = yaml.safe_load((ROOT / "sources" / "catalog.yaml").read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    for e in data.get("entries") or []:
        print(f"  [{e.get('status')}] {e.get('id')} {e.get('url')}")
        if e.get("status") != "integrated":
            continue
        for rel in e.get("evidence") or []:
            if not (ROOT / rel).exists():
                problems.append(f"{e.get('id')}: missing {rel}")
    # bridge feature surface required
    bridge = (ROOT / "bridge" / "bridge.js").read_text(encoding="utf-8", errors="replace")
    for needle in ("/health", "/messages", "/send", "/allowlist", "app.listen"):
        if needle not in bridge:
            problems.append(f"bridge missing {needle}")
    if problems:
        print("FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
