# Output Schema Reference

All commands return JSON to stdout. Logs go to stderr.

## Single-Page Result (fetch, crawl, scrape, extract)

```json
{
  "status": "ok | partial | failed",
  "command": "fetch | crawl | scrape | extract",
  "url": "https://example.com/page",
  "canonical_url": "https://example.com/page",
  "title": "Page Title",
  "site_name": "example.com",
  "published_at": "2025-01-15",
  "authors": ["Author Name"],
  "language": "en",
  "content_type": "article | documentation | forum | product | unknown",
  "summary": "First 200 chars...",
  "markdown": "# Full content in markdown\n\nParagraph text...",
  "text": "Plain text version of content...",
  "links": [{"url": "https://...", "text": "Link text"}],
  "images": [{"url": "https://...", "alt": "Alt text"}],
  "tables": [[["Header1", "Header2"], ["Row1Col1", "Row1Col2"]]],
  "source_engine": "httpx | crawl4ai",
  "fetch_mode": "httpx | crawl4ai | local",
  "extract_mode": "trafilatura | bs4 | crawl4ai_markdown",
  "confidence": 0.95,
  "timing_ms": 1234,
  "error": null
}
```

### Field Details

| Field | Type | Present When | Description |
|---|---|---|---|
| `status` | string | always | `ok` = success, `partial` = some content but issues, `failed` = error |
| `command` | string | always | Which command produced this result |
| `url` | string | always | Requested URL |
| `canonical_url` | string | if available | Page's canonical URL (from metadata) |
| `title` | string | if extracted | Page title |
| `markdown` | string | if extracted | Primary content in markdown format |
| `text` | string | if extracted | Plain text fallback |
| `tables` | array | scrape --table | 3D array: tables → rows → cells |
| `confidence` | float | always | 0.0-1.0, how confident in extraction quality |
| `timing_ms` | int | always | Total operation time in milliseconds |
| `error` | string | on failure | Error description with diagnostic hints |

### Empty fields are omitted from JSON output to reduce noise.

## Search Result (search command)

```json
{
  "status": "ok",
  "command": "search",
  "query": "python web scraping",
  "results": [
    {
      "url": "https://...",
      "title": "Result Title",
      "snippet": "Text excerpt from page...",
      "engine": "google",
      "score": 1.5
    }
  ],
  "total_results": 10,
  "timing_ms": 567
}
```

## Discover Result (discover command)

```json
{
  "status": "ok",
  "command": "discover",
  "base_url": "https://example.com",
  "mode": "sitemap | crawl | both",
  "urls": [
    "https://example.com/page1",
    "https://example.com/page2"
  ],
  "total_urls": 42,
  "timing_ms": 890
}
```

## Status Codes

| Status | Meaning | Action |
|---|---|---|
| `ok` | Full success | Use `markdown` field |
| `partial` | Some content extracted but with issues | Check `error` for details, content may be usable |
| `failed` | Complete failure | Check `error` for diagnostic, try different command |

## Piping and Processing

```bash
# Extract markdown only
python3 scripts/web.py fetch "https://example.com" | jq -r '.markdown'

# Get all URLs from search
python3 scripts/web.py search "topic" | jq -r '.results[].url'

# Get tables as CSV-like
python3 scripts/web.py scrape --table "https://..." | jq -r '.tables[0][] | @csv'
```
