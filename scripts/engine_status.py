#!/usr/bin/env python3
"""Unlimited Research — engine diagnostics CLI.

Prints the same health report the ``engine_status`` MCP tool returns, plus a
quick live round-trip check. Useful for verifying the stack from a terminal:

    python scripts/engine_status.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

from research import engine_status  # noqa: E402


async def main() -> int:
    status = await engine_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    ok = status["config"]["searxng_reachable"]
    print("\nRESULT:", "PASS" if ok else "FAIL (SearXNG unreachable)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
