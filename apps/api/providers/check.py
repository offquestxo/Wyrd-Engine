"""Test provider connections, or check configured model IDs against live model lists.

Usage:
  python -m apps.api.providers.check [provider ...]          # connection tests
  python -m apps.api.providers.check --models [provider ...] # configured IDs vs live list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from apps.api.providers.base import ConnectionTest, ProviderError
from apps.api.providers.router import get_router


async def _connections(names: list[str]) -> int:
    router = get_router()
    targets = names or [*router.providers, "youtube"]
    results = [await router.test_connection(n) for n in targets if n != "youtube"]
    if "youtube" in targets:
        from apps.api.sources import youtube

        ok, detail = await youtube.test_connection()
        results.append(ConnectionTest(provider="youtube", ok=ok, detail=detail))
    print(json.dumps([r.model_dump() for r in results], indent=2))
    return 0 if all(r.ok for r in results) else 1


async def _models(names: list[str]) -> int:
    router = get_router()
    report: list[dict[str, Any]] = []
    for name in names or list(router.providers):
        provider = router.providers[name]
        configured = {a: m.id for a, m in router.config.providers[name].models.items()}
        try:
            live = set(await provider.list_models())  # type: ignore[attr-defined]
        except ProviderError as e:
            report.append({"provider": name, "ok": False, "error": str(e)})
            continue
        missing = {alias: mid for alias, mid in configured.items() if mid not in live}
        report.append(
            {
                "provider": name,
                "ok": not missing,
                "configured": configured,
                "missing_from_live_list": missing,
                "live_count": len(live),
            }
        )
    print(json.dumps(report, indent=2))
    return 0 if all(r["ok"] for r in report) else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="check")
    parser.add_argument("--models", action="store_true", help="compare model IDs to live lists")
    parser.add_argument("providers", nargs="*")
    args = parser.parse_args()
    run = _models if args.models else _connections
    sys.exit(asyncio.run(run(args.providers)))


if __name__ == "__main__":
    main()
