from __future__ import annotations

from typing import Any, Optional

from _config import get_logger
from _normalize import WebResult, Timer

log = get_logger("bs4_scrape")


def scrape_selector(
    html: str,
    selector: str,
    *,
    url: str = "",
    attribute: Optional[str] = None,
) -> WebResult:
    from bs4 import BeautifulSoup

    with Timer() as t:
        try:
            soup = BeautifulSoup(html, "lxml")
            elements = soup.select(selector)

            if attribute:
                extracted = [
                    el.get(attribute, "") for el in elements if el.get(attribute)
                ]
                text = "\n".join(extracted)
            else:
                extracted = [el.get_text(strip=True) for el in elements]
                text = "\n\n".join(extracted)

        except Exception as exc:
            log.error("BS4 selector extraction failed: %s", exc)
            return WebResult(
                url=url,
                status="failed",
                extract_mode="bs4",
                error=f"Selector extraction failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    if not elements:
        return WebResult(
            url=url,
            status="partial",
            extract_mode="bs4",
            text="",
            error=f"No elements matched selector: {selector}",
            timing_ms=t.elapsed_ms,
        )

    return WebResult(
        url=url,
        text=text,
        markdown=text,
        extract_mode="bs4",
        confidence=0.9 if elements else 0.0,
        timing_ms=t.elapsed_ms,
    )


def scrape_tables(html: str, *, url: str = "") -> WebResult:
    from bs4 import BeautifulSoup

    with Timer() as t:
        try:
            soup = BeautifulSoup(html, "lxml")
            table_elements = soup.find_all("table")
            tables: list[list[list[str]]] = []

            for table in table_elements:
                rows: list[list[str]] = []
                for tr in table.find_all("tr"):
                    cells = tr.find_all(["th", "td"])
                    rows.append([cell.get_text(strip=True) for cell in cells])
                if rows:
                    tables.append(rows)

        except Exception as exc:
            log.error("BS4 table extraction failed: %s", exc)
            return WebResult(
                url=url,
                status="failed",
                extract_mode="bs4",
                error=f"Table extraction failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    if not tables:
        return WebResult(
            url=url,
            status="partial",
            extract_mode="bs4",
            error="No tables found on page",
            timing_ms=t.elapsed_ms,
        )

    markdown_parts = []
    for table in tables:
        if len(table) < 1:
            continue
        header = table[0]
        md = "| " + " | ".join(header) + " |\n"
        md += "| " + " | ".join(["---"] * len(header)) + " |\n"
        for row in table[1:]:
            padded = row + [""] * (len(header) - len(row))
            md += "| " + " | ".join(padded[: len(header)]) + " |\n"
        markdown_parts.append(md)

    return WebResult(
        url=url,
        tables=tables,
        markdown="\n\n".join(markdown_parts),
        extract_mode="bs4",
        confidence=0.95,
        timing_ms=t.elapsed_ms,
    )


def scrape_lists(html: str, *, url: str = "") -> WebResult:
    from bs4 import BeautifulSoup

    with Timer() as t:
        try:
            soup = BeautifulSoup(html, "lxml")
            list_elements = soup.find_all(["ul", "ol"])
            all_lists: list[list[str]] = []

            for lst in list_elements:
                items = [
                    li.get_text(strip=True)
                    for li in lst.find_all("li", recursive=False)
                ]
                if items:
                    all_lists.append(items)

        except Exception as exc:
            log.error("BS4 list extraction failed: %s", exc)
            return WebResult(
                url=url,
                status="failed",
                extract_mode="bs4",
                error=f"List extraction failed: {exc}",
                timing_ms=t.elapsed_ms,
            )

    if not all_lists:
        return WebResult(
            url=url,
            status="partial",
            extract_mode="bs4",
            error="No lists found on page",
            timing_ms=t.elapsed_ms,
        )

    markdown_parts = []
    for items in all_lists:
        md = "\n".join(f"- {item}" for item in items)
        markdown_parts.append(md)

    return WebResult(
        url=url,
        text="\n\n".join(markdown_parts),
        markdown="\n\n".join(markdown_parts),
        extract_mode="bs4",
        confidence=0.9,
        timing_ms=t.elapsed_ms,
    )


def scrape_schema(html: str, schema: dict, *, url: str = "") -> WebResult:
    from bs4 import BeautifulSoup
    import json as _json

    with Timer() as t:
        try:
            soup = BeautifulSoup(html, "lxml")
            extracted: dict[str, Any] = {}

            for field, spec in schema.items():
                if isinstance(spec, str):
                    el = soup.select_one(spec)
                    extracted[field] = el.get_text(strip=True) if el else None
                elif isinstance(spec, dict):
                    selector = spec.get("selector", "")
                    attribute = spec.get("attribute")
                    multiple = spec.get("multiple", False)
                    elements = soup.select(selector) if multiple else [soup.select_one(selector)]
                    elements = [e for e in elements if e is not None]
                    results_for_field = []
                    for el in elements:
                        if attribute:
                            results_for_field.append(el.get(attribute, ""))
                        else:
                            results_for_field.append(el.get_text(strip=True))
                    extracted[field] = results_for_field if multiple else (results_for_field[0] if results_for_field else None)
        except Exception as exc:
            return WebResult(url=url, status="failed", extract_mode="bs4",
                             error=f"Schema extraction failed: {exc}", timing_ms=t.elapsed_ms)

    as_json = _json.dumps(extracted, ensure_ascii=False, indent=2)
    return WebResult(
        url=url,
        text=as_json,
        markdown=f"```json\n{as_json}\n```",
        extract_mode="bs4",
        confidence=0.9 if any(v is not None for v in extracted.values()) else 0.0,
        timing_ms=t.elapsed_ms,
    )
