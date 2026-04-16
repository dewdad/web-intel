# Performance Table

Measured characteristics for each component. Use these to choose the right tool for latency-sensitive workflows.

## Component Benchmarks

| Component | Operation | Typical Latency | Max Concurrency | Memory Overhead |
|---|---|---|---|---|
| SearXNG | Search query | 200-800ms | 1 per query (rate-limited) | ~0 (server-side) |
| httpx | HTTP GET | 100-500ms | 10+ parallel | ~5MB per client |
| httpx + HTTP/2 | HTTP GET (multiplexed) | 80-400ms | 100 streams per connection | ~5MB per client |
| Trafilatura | Content extraction | 20-100ms | CPU-bound (parallel OK) | ~10MB per call |
| Trafilatura | Sitemap parsing | 500ms-5s | 1 per site | ~20MB |
| Trafilatura | Focused crawl | 5-60s | 1 per site | ~50MB |
| BS4 + lxml | HTML parsing | 10-50ms | CPU-bound (parallel OK) | ~5MB per document |
| Crawl4AI | Browser startup | ~2-3s | 1 (reused after) | ~270MB per browser |
| Crawl4AI | Page crawl | 2-10s | 1-3 parallel | ~50MB per page |
| Crawl4AI | JS execution | +1-5s | Per page | Included above |

## End-to-End Pipeline Latency

| Pipeline | Components | Expected Latency |
|---|---|---|
| `search` | SearXNG | 200-800ms |
| `fetch` (static page) | httpx → Trafilatura | 200-600ms |
| `fetch` (with fallback) | httpx → Trafilatura → Crawl4AI | 3-12s |
| `crawl` (JS page) | Crawl4AI | 3-12s |
| `scrape --table` (static) | httpx → BS4 | 150-550ms |
| `scrape --table --use-crawl4ai` | Crawl4AI → BS4 | 3-12s |
| `extract` (local HTML) | Trafilatura | 20-100ms |
| `discover --mode sitemap` | Trafilatura | 500ms-5s |
| `discover --mode crawl` | Trafilatura | 5-60s |
| `discover --mode both` | Trafilatura (sitemap + crawl) | 5-65s |

## Tuning Tips

| Goal | Recommendation |
|---|---|
| Minimize latency | Use `fetch` for static pages, avoid Crawl4AI unless needed |
| Maximize throughput | Batch URLs and process sequentially with `sleep 1` between domains |
| Reduce memory | Avoid `crawl` command (browser overhead). Use `fetch` with `--no-fallback-crawl` |
| Best extraction quality | Use `--favor-precision` for articles, `--favor-recall` for documentation |
| Handle rate limits | SearXNG has built-in limiting. For httpx, respect `MAX_CONCURRENT_FETCHES` |

## Resource Limits

| Resource | Default | Override Via |
|---|---|---|
| HTTP timeout | 30s | `--timeout` flag or `HTTP_TIMEOUT` env var |
| Max concurrent fetches | 5 | `MAX_CONCURRENT_FETCHES` env var |
| Browser timeout | 60s | `--timeout` flag on `crawl` command |
| SearXNG rate limit | Server-configured | SearXNG settings.yml `limiter` section |
| Crawl4AI page timeout | 60s | `--timeout` flag (converted to ms internally) |
