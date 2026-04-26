# Advanced Patterns

Multi-step workflows combining commands for complex research tasks.

## Sourced Search (default — fully cited output)

```bash
# Default search — always returns published_at, authors, domain, citations[]
$SKILL_DIR/bin/web-intel search "neural scaling laws" --pretty

# Full content + citations in one shot (fetch-top backfills metadata for free)
$SKILL_DIR/bin/web-intel search "query" --fetch-top 3 --pretty

# Speed mode — skip enrichment and citations (for high-volume pipelines)
$SKILL_DIR/bin/web-intel search "query" --no-enrich --no-cite --pretty

# Compose a cited research answer
$SKILL_DIR/bin/web-intel search "transformer attention mechanisms" \
  | jq -r '
    "## Research Summary\n",
    (.results[] | "### [\(.citation_index)] \(.title) (\(.published_at // "date unknown"))\n\(.snippet)\n"),
    "\n## References",
    (.citations[])
  '

# Use citations[] as a ready-made reference list for follow-up fetches
$SKILL_DIR/bin/web-intel search "RLHF alignment" \
  | jq -r '.results[] | select(.published_at != "") | .url' \
  | $SKILL_DIR/bin/web-intel fetch-batch --concurrency 3 --max-tokens 2000
```

## Research Pipeline: Topic Deep-Dive

```bash
# 1. Search and read the top 3 results in one shot (fully sourced)
$SKILL_DIR/bin/web-intel search "distributed consensus algorithms" --fetch-top 3 --pretty

# 2. Fetch individual URLs with citation
$SKILL_DIR/bin/web-intel fetch "https://example.com/article" --pretty
# Response includes: citation.citation_text, markdown ends with ---\n**Source:** ...
```

## Structured Data Collection

```bash
# Extract all tables from a Wikipedia page
$SKILL_DIR/bin/web-intel scrape --table "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)" --pretty

# Extract specific data with CSS selectors
$SKILL_DIR/bin/web-intel scrape --selector ".infobox td" "https://en.wikipedia.org/wiki/Python_(programming_language)"
```

## JS-Heavy Site Workflow

```bash
# Wait for dynamic content to load, then extract
$SKILL_DIR/bin/web-intel crawl "https://spa-app.example.com" \
  --wait-for ".content-loaded" \
  --timeout 45 \
  --pretty

# Execute JS before extraction (e.g., dismiss cookie banner)
$SKILL_DIR/bin/web-intel crawl "https://example.com" \
  --execute-js "document.querySelector('.cookie-accept')?.click()" \
  --pretty
```

## Site Mapping + Batch Fetch

```bash
# Discover all pages
$SKILL_DIR/bin/web-intel discover "https://docs.example.com" --mode both --max-urls 50 > sitemap.json

# Batch fetch with citations per result
jq -r '.urls[]' sitemap.json | $SKILL_DIR/bin/web-intel fetch-batch --concurrency 3
# Each NDJSON line includes citation.citation_text
```

## Fallback Chain: Explicit Control

```bash
# Try fast path only (no Crawl4AI fallback)
$SKILL_DIR/bin/web-intel fetch "https://example.com" --no-fallback-crawl

# Force Crawl4AI for a page you know needs JS
$SKILL_DIR/bin/web-intel crawl "https://example.com"

# Use Docker-based Crawl4AI (if running)
$SKILL_DIR/bin/web-intel crawl "https://example.com" --docker
```

## Precision vs Recall Tuning

```bash
# High precision: fewer false positives, cleaner output
$SKILL_DIR/bin/web-intel fetch "https://example.com" --favor-precision

# High recall: more content, may include some boilerplate
$SKILL_DIR/bin/web-intel fetch "https://example.com" --favor-recall --include-tables --include-links
```

## Processing Local HTML

```bash
# From a file
$SKILL_DIR/bin/web-intel extract --html-file saved_page.html --url "https://original-url.com"

# From stdin (piped from another tool)
curl -s "https://example.com" | $SKILL_DIR/bin/web-intel extract --stdin --include-tables

# From Crawl4AI raw output
$SKILL_DIR/bin/web-intel crawl "https://example.com" | jq -r '.text' | $SKILL_DIR/bin/web-intel extract --stdin
```

## Combining with jq for Analysis

```bash
# Compare word counts across sources
for url in url1 url2 url3; do
  $SKILL_DIR/bin/web-intel fetch "$url" | jq '{url: .url, words: (.text | split(" ") | length)}'
done

# Filter search results by score
$SKILL_DIR/bin/web-intel search "topic" | jq '.results | map(select(.score > 1.0))'

# Extract and deduplicate links
$SKILL_DIR/bin/web-intel fetch "https://example.com" --include-links | jq '[.links[].url] | unique'

# Get only results where enrichment found a date
$SKILL_DIR/bin/web-intel search "machine learning" | jq '.results[] | select(.published_at != "")'
```
