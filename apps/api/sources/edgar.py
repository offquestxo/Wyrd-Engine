"""SEC EDGAR: company lookup, filings, XBRL company facts, full-text search.

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
Fair access: max 10 req/s and a User-Agent with contact email (SEC_USER_AGENT in .env).

CLI:
  python -m apps.api.sources.edgar search "Circuit City"
  python -m apps.api.sources.edgar filings 104599 --forms 10-K
  python -m apps.api.sources.edgar facts 764478
  python -m apps.api.sources.edgar fulltext "\"Circuit City\" liquidation" --forms 8-K
"""

from __future__ import annotations

import argparse
from typing import Any

from pydantic import BaseModel

from apps.api.settings import get_settings
from apps.api.sources._http import SourceError, get_json, run_cli, truncate
from apps.api.sources.models import SourceItem

SOURCE = "edgar"
EFTS = "https://efts.sec.gov/LATEST/search-index"
DATA = "https://data.sec.gov"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# A compact set of headline concepts for story research (full facts are huge).
KEY_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "NetIncomeLoss",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "LongTermDebt",
]


class Company(BaseModel):
    cik: str
    name: str


class Filing(BaseModel):
    form: str
    filing_date: str
    report_date: str | None
    accession: str
    description: str | None
    url: str


class Fact(BaseModel):
    concept: str
    label: str | None
    unit: str
    value: float
    period_end: str
    fiscal_year: int | None
    form: str | None
    filed: str | None
    accession: str | None


class CompanyFacts(BaseModel):
    cik: str
    name: str | None
    facts: list[Fact]
    note: str | None = None


def _headers() -> dict[str, str]:
    ua = get_settings().sec_user_agent.strip().strip('"')
    if "@" not in ua or "your@email.com" in ua:
        raise SourceError(SOURCE, "set SEC_USER_AGENT in .env to 'name contact@email' (SEC rule)")
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def pad_cik(cik: str | int) -> str:
    return str(int(str(cik).strip())).zfill(10)


async def search_companies(name: str, limit: int = 10) -> list[Company]:
    data = await get_json(SOURCE, EFTS, params={"keysTyped": name}, headers=_headers())
    hits = (data.get("hits") or {}).get("hits") or []
    return [
        Company(cik=pad_cik(h["_id"]), name=h["_source"].get("entity", "")) for h in hits[:limit]
    ]


async def resolve_cik(cik_or_name: str) -> str:
    if cik_or_name.strip().isdigit():
        return pad_cik(cik_or_name)
    matches = await search_companies(cik_or_name, limit=1)
    if not matches:
        raise SourceError(SOURCE, f"no EDGAR entity matches {cik_or_name!r}")
    return matches[0].cik


async def filings(
    cik_or_name: str, forms: list[str] | None = None, limit: int = 40
) -> list[Filing]:
    cik = await resolve_cik(cik_or_name)
    data = await get_json(SOURCE, f"{DATA}/submissions/CIK{cik}.json", headers=_headers())
    recent = (data.get("filings") or {}).get("recent") or {}
    wanted = {f.upper() for f in forms or []}
    out: list[Filing] = []
    for i, form in enumerate(recent.get("form", [])):
        if wanted and form.upper() not in wanted:
            continue
        accession = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]
        out.append(
            Filing(
                form=form,
                filing_date=recent["filingDate"][i],
                report_date=recent["reportDate"][i] or None,
                accession=accession,
                description=recent["primaryDocDescription"][i] or None,
                url=f"{ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{doc}",
            )
        )
        if len(out) >= limit:
            break
    return out


async def company_facts(
    cik_or_name: str, concepts: list[str] | None = None, annual_only: bool = True
) -> CompanyFacts:
    cik = await resolve_cik(cik_or_name)
    try:
        data = await get_json(
            SOURCE, f"{DATA}/api/xbrl/companyfacts/CIK{cik}.json", headers=_headers(), retries=0
        )
    except SourceError as e:
        if e.status == 404:
            return CompanyFacts(
                cik=cik,
                name=None,
                facts=[],
                note=(
                    "No XBRL facts. Companies began XBRL tagging in 2009–2011, so older filers "
                    "(e.g. Circuit City) have none — use `filings` and read the 10-Ks instead."
                ),
            )
        raise
    gaap: dict[str, Any] = (data.get("facts") or {}).get("us-gaap") or {}
    facts: list[Fact] = []
    for concept in concepts or KEY_CONCEPTS:
        entry = gaap.get(concept)
        if not entry:
            continue
        for unit, rows in (entry.get("units") or {}).items():
            for row in rows:
                if annual_only and row.get("form") not in ("10-K", "10-K/A", "20-F"):
                    continue
                if annual_only and row.get("fp") not in (None, "FY"):
                    continue
                facts.append(
                    Fact(
                        concept=concept,
                        label=entry.get("label"),
                        unit=unit,
                        value=row["val"],
                        period_end=row["end"],
                        fiscal_year=row.get("fy"),
                        form=row.get("form"),
                        filed=row.get("filed"),
                        accession=row.get("accn"),
                    )
                )
    # One row per concept/unit/period (latest filing wins), newest periods first.
    dedup: dict[tuple[str, str, str], Fact] = {}
    for fact in sorted(facts, key=lambda f: f.filed or ""):
        dedup[(fact.concept, fact.unit, fact.period_end)] = fact
    ordered = sorted(dedup.values(), key=lambda f: (f.concept, f.period_end), reverse=True)
    return CompanyFacts(cik=cik, name=data.get("entityName"), facts=ordered)


async def full_text_search(
    query: str,
    forms: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
) -> list[SourceItem]:
    params: dict[str, str] = {"q": query}
    if forms:
        params["forms"] = forms
    if start or end:
        params.update(
            {"dateRange": "custom", "startdt": start or "2001-01-01", "enddt": end or "2100-01-01"}
        )
    data = await get_json(SOURCE, EFTS, params=params, headers=_headers())
    items: list[SourceItem] = []
    for hit in ((data.get("hits") or {}).get("hits") or [])[:limit]:
        src = hit.get("_source") or {}
        adsh, _, filename = str(hit.get("_id", "")).partition(":")
        ciks = src.get("ciks") or ["0"]
        names = src.get("display_names") or [""]
        url = f"{ARCHIVES}/{int(ciks[0])}/{adsh.replace('-', '')}/{filename}"
        title = f"{names[0]} — {src.get('form', '')} {src.get('file_description') or ''}".strip()
        items.append(
            SourceItem(
                title=truncate(title, 200),
                url=url,
                source="SEC EDGAR",
                published_at=src.get("file_date"),
                snippet=f"{src.get('form', '')} · period ending "
                f"{src.get('period_ending') or 'n/a'}",
            )
        )
    return items


# ---------------------------------------------------------------------------- CLI
def main() -> None:
    parser = argparse.ArgumentParser(prog="edgar", description="SEC EDGAR source")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search", help="find companies (CIK) by name")
    p.add_argument("name")
    p = sub.add_parser("filings", help="recent filings for a CIK or company name")
    p.add_argument("company")
    p.add_argument("--forms", default="", help="comma-separated, e.g. 10-K,8-K")
    p.add_argument("--limit", type=int, default=40)
    p = sub.add_parser("facts", help="headline XBRL facts (annual)")
    p.add_argument("company")
    p.add_argument("--concepts", default="", help="comma-separated us-gaap concepts")
    p = sub.add_parser("fulltext", help="EDGAR full-text search (2001+)")
    p.add_argument("query")
    p.add_argument("--forms", default=None)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--limit", type=int, default=20)

    def split(value: str) -> list[str] | None:
        return [v.strip() for v in value.split(",") if v.strip()] or None

    run_cli(
        SOURCE,
        parser,
        {
            "search": lambda a: search_companies(a.name),
            "filings": lambda a: filings(a.company, split(a.forms), a.limit),
            "facts": lambda a: company_facts(a.company, split(a.concepts)),
            "fulltext": lambda a: full_text_search(a.query, a.forms, a.start, a.end, a.limit),
        },
    )


if __name__ == "__main__":
    main()
