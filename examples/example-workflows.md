# Example Workflows

Common patterns for using web-intel in AI agent workflows.

## 1. Quick Fact Check

```bash
# Search and read the top result
url=$(python3 scripts/web.py search "when was Python 3.12 released" --max-results 1 | jq -r '.results[0].url')
python3 scripts/web.py fetch "$url" --favor-precision --pretty
```

## 2. Documentation Lookup

```bash
# Search for specific API docs
python3 scripts/web.py search "httpx AsyncClient documentation" --engines google --max-results 3 --pretty

# Fetch the docs page
python3 scripts/web.py fetch "https://www.python-httpx.org/async/" --include-tables --pretty
```

## 3. News Research

```bash
# Search recent news
python3 scripts/web.py search "AI regulation 2025" --categories news --time-range week --max-results 10 --pretty

# Fetch each article
for url in $(python3 scripts/web.py search "AI regulation 2025" --categories news --time-range week | jq -r '.results[].url'); do
  echo "---"
  python3 scripts/web.py fetch "$url" --favor-precision | jq '{title: .title, published: .published_at, summary: (.markdown[:300])}'
  sleep 1
done
```

## 4. Competitive Analysis (Table Extraction)

```bash
# Extract pricing tables from competitor pages
python3 scripts/web.py scrape --table "https://competitor.com/pricing" --pretty

# If the pricing page is a SPA
python3 scripts/web.py scrape --table --use-crawl4ai "https://competitor.com/pricing" --pretty
```

## 5. Site Audit (Discovery + Batch)

```bash
# Find all pages on a site
python3 scripts/web.py discover "https://docs.example.com" --mode both --max-urls 20 --pretty

# Batch fetch and check which pages extract well
for url in $(python3 scripts/web.py discover "https://docs.example.com" --mode sitemap | jq -r '.urls[:10][]'); do
  python3 scripts/web.py fetch "$url" | jq '{url: .url, status: .status, confidence: .confidence, title: .title}'
  sleep 0.5
done
```

## 6. GitHub/Code Research

```bash
# Search for code-related topics
python3 scripts/web.py search "site:github.com httpx retry transport example" --max-results 5 --pretty

# Fetch a GitHub README
python3 scripts/web.py fetch "https://github.com/will-ockmore/httpx-retries" --pretty
```

## 7. Processing Saved HTML

```bash
# Extract content from a downloaded page
python3 scripts/web.py extract --html-file ~/Downloads/saved_page.html --url "https://original-url.com" --pretty

# Process HTML from clipboard (macOS)
pbpaste | python3 scripts/web.py extract --stdin --include-tables --pretty
```

## 8. Multi-Source Comparison

```bash
# Fetch the same topic from multiple sources
sources=(
  "https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)"
  "https://arxiv.org/abs/1706.03762"
  "https://jalammar.github.io/illustrated-transformer/"
)

for url in "${sources[@]}"; do
  python3 scripts/web.py fetch "$url" | jq '{url: .url, title: .title, words: (.text | split(" ") | length), confidence: .confidence}'
done
```
