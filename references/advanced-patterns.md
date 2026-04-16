# Advanced Patterns

Multi-step workflows combining commands for complex research tasks.

## Research Pipeline: Topic Deep-Dive

```bash
# 1. Search for the topic
python3 scripts/web.py search "distributed consensus algorithms" --max-results 5 --pretty

# 2. Fetch each result (use jq to extract URLs, then loop)
for url in $(python3 scripts/web.py search "distributed consensus algorithms" | jq -r '.results[].url'); do
  python3 scripts/web.py fetch "$url" --include-links | jq '{url: .url, title: .title, content: .markdown[:500]}'
done
```

## Structured Data Collection

```bash
# Extract all tables from a Wikipedia page
python3 scripts/web.py scrape --table "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)" --pretty

# Extract specific data with CSS selectors
python3 scripts/web.py scrape --selector ".infobox td" "https://en.wikipedia.org/wiki/Python_(programming_language)"
```

## JS-Heavy Site Workflow

```bash
# Wait for dynamic content to load, then extract
python3 scripts/web.py crawl "https://spa-app.example.com" \
  --wait-for ".content-loaded" \
  --timeout 45 \
  --pretty

# Execute JS before extraction (e.g., dismiss cookie banner)
python3 scripts/web.py crawl "https://example.com" \
  --execute-js "document.querySelector('.cookie-accept')?.click()" \
  --pretty
```

## Site Mapping + Batch Fetch

```bash
# Discover all pages
python3 scripts/web.py discover "https://docs.example.com" --mode both --max-urls 50 > sitemap.json

# Batch fetch discovered pages
for url in $(jq -r '.urls[]' sitemap.json); do
  python3 scripts/web.py fetch "$url" | jq '{url: .url, title: .title, status: .status}'
  sleep 1
done
```

## Fallback Chain: Explicit Control

```bash
# Try fast path only (no Crawl4AI fallback)
python3 scripts/web.py fetch "https://example.com" --no-fallback-crawl

# Force Crawl4AI for a page you know needs JS
python3 scripts/web.py crawl "https://example.com"

# Use Docker-based Crawl4AI (if running)
python3 scripts/web.py crawl "https://example.com" --docker
```

## Precision vs Recall Tuning

```bash
# High precision: fewer false positives, cleaner output
python3 scripts/web.py fetch "https://example.com" --favor-precision

# High recall: more content, may include some boilerplate
python3 scripts/web.py fetch "https://example.com" --favor-recall --include-tables --include-links
```

## Processing Local HTML

```bash
# From a file
python3 scripts/web.py extract --html-file saved_page.html --url "https://original-url.com"

# From stdin (piped from another tool)
curl -s "https://example.com" | python3 scripts/web.py extract --stdin --include-tables

# From Crawl4AI raw output
python3 scripts/web.py crawl "https://example.com" | jq -r '.text' | python3 scripts/web.py extract --stdin
```

## Combining with jq for Analysis

```bash
# Compare word counts across sources
for url in url1 url2 url3; do
  python3 scripts/web.py fetch "$url" | jq '{url: .url, words: (.text | split(" ") | length)}'
done

# Filter search results by score
python3 scripts/web.py search "topic" | jq '.results | map(select(.score > 1.0))'

# Extract and deduplicate links
python3 scripts/web.py fetch "https://example.com" --include-links | jq '[.links[].url] | unique'
```
