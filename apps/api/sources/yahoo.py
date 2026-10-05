"""Yahoo Finance via yfinance (unofficial). Stock price context only.

yfinance scrapes Yahoo and breaks without warning; delisted tickers often return nothing.
Always secondary to EDGAR: every failure becomes a SourceError the caller can skip.

CLI:
  python -m apps.api.sources.yahoo history BBY --period 5y --interval 1mo
  python -m apps.api.sources.yahoo info BBY
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from apps.api.sources._http import SourceError, run_cli

SOURCE = "yahoo"
INFO_FIELDS = [
    "shortName",
    "longName",
    "exchange",
    "currency",
    "marketCap",
    "sector",
    "industry",
    "fullTimeEmployees",
    "website",
]


class PricePoint(BaseModel):
    date: str
    close: float
    volume: int | None


class PriceHistory(BaseModel):
    ticker: str
    period: str
    interval: str
    points: list[PricePoint]
    url: str


def _quote_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"


def _history_sync(ticker: str, period: str, interval: str) -> PriceHistory:
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    try:
        frame = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    except Exception as e:
        raise SourceError(SOURCE, f"yfinance failed: {type(e).__name__}: {str(e)[:150]}") from e
    if frame is None or frame.empty:
        raise SourceError(SOURCE, f"no price data for {ticker!r} (delisted or unknown ticker?)")
    points = [
        PricePoint(
            date=idx.date().isoformat(),
            close=round(float(row["Close"]), 4),
            volume=int(row["Volume"]) if row.get("Volume") == row.get("Volume") else None,
        )
        for idx, row in frame.iterrows()
    ]
    return PriceHistory(
        ticker=ticker, period=period, interval=interval, points=points, url=_quote_url(ticker)
    )


def _info_sync(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        raise SourceError(SOURCE, f"yfinance failed: {type(e).__name__}: {str(e)[:150]}") from e
    picked = {k: info.get(k) for k in INFO_FIELDS if info.get(k) is not None}
    if not picked:
        raise SourceError(SOURCE, f"no info for {ticker!r}")
    return {"ticker": ticker, "url": _quote_url(ticker), **picked}


async def history(ticker: str, period: str = "5y", interval: str = "1mo") -> PriceHistory:
    return await asyncio.to_thread(_history_sync, ticker.upper(), period, interval)


async def info(ticker: str) -> dict[str, Any]:
    return await asyncio.to_thread(_info_sync, ticker.upper())


def main() -> None:
    parser = argparse.ArgumentParser(prog="yahoo")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("history")
    p.add_argument("ticker")
    p.add_argument("--period", default="5y")
    p.add_argument("--interval", default="1mo")
    p = sub.add_parser("info")
    p.add_argument("ticker")
    run_cli(
        SOURCE,
        parser,
        {
            "history": lambda a: history(a.ticker, a.period, a.interval),
            "info": lambda a: info(a.ticker),
        },
    )


if __name__ == "__main__":
    main()
