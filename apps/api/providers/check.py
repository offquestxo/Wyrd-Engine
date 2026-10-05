"""Test every provider connection from the terminal.

Usage: python -m apps.api.providers.check [provider ...]
"""

from __future__ import annotations

import asyncio
import json
import sys

from apps.api.providers.base import ConnectionTest
from apps.api.providers.router import get_router


async def _main(names: list[str]) -> int:
    router = get_router()
    targets = names or list(router.providers)
    results = [await router.test_connection(name) for name in targets if name != "youtube"]
    if not names or "youtube" in names:
        from apps.api.sources import youtube

        ok, detail = await youtube.test_connection()
        results.append(ConnectionTest(provider="youtube", ok=ok, detail=detail))
    print(json.dumps([r.model_dump() for r in results], indent=2))
    return 0 if all(r.ok for r in results) else 1


def main() -> None:
    sys.exit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
