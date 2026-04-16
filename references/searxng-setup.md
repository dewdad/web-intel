# SearXNG Setup

## Quick Start (Docker)

```bash
docker compose -f docker/docker-compose.searxng.yml up -d
```

This starts SearXNG on port 8080 with Valkey (Redis-compatible) for caching.

Verify: `curl http://localhost:8080/search?q=test&format=json`

## Configuration

Settings are in `docker/searxng/settings.yml`. Key sections:

### Enable JSON API (required)

```yaml
search:
  formats:
    - html
    - json
```

Without `json` in formats, the API returns HTML instead of JSON.

### Rate Limiting

```yaml
server:
  limiter: true
```

SearXNG uses a built-in Limiter with Valkey backend. Default limits are generous for single-user use. Adjust via environment variables if needed.

### Engines

Enable/disable search engines in the `engines` section. Each engine has:
- `name`: Display name
- `engine`: Engine module name
- `shortcut`: Short code for URL queries

Pre-configured engines: Google, DuckDuckGo, Brave, Bing, Wikipedia, GitHub.

### Adding Engines

```yaml
engines:
  - name: arxiv
    engine: arxiv
    shortcut: ar
    categories: science

  - name: stackoverflow
    engine: stackoverflow
    shortcut: so
    categories: it
```

See full list: https://docs.searxng.org/admin/engines/index.html

## API Reference

### Search Endpoint

```
GET /search?q=QUERY&format=json
```

| Parameter | Type | Description |
|---|---|---|
| `q` | string | Search query (required) |
| `format` | string | `json` (required for API use) |
| `categories` | string | Comma-separated: general, news, science, files, images, videos, it, social_media |
| `engines` | string | Comma-separated engine names |
| `language` | string | BCP 47 language code (e.g., `en`, `de`, `fr`) |
| `time_range` | string | `day`, `week`, `month`, `year` |
| `pageno` | int | Page number (starts at 1) |

### Response Format

```json
{
  "query": "python web scraping",
  "number_of_results": 1234,
  "results": [
    {
      "url": "https://...",
      "title": "...",
      "content": "Snippet text...",
      "engine": "google",
      "score": 1.5,
      "category": "general",
      "engines": ["google", "duckduckgo"]
    }
  ]
}
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `Connection refused` | Is SearXNG running? `docker ps \| grep wrs-searxng` |
| HTML returned instead of JSON | Add `json` to `search.formats` in settings.yml |
| No results | Check if engines are enabled and not rate-limited |
| Slow responses | Normal for first query (engine warm-up). Subsequent queries use cache. |
| Port conflict | Change port mapping in docker-compose: `"9090:8080"` and update `SEARXNG_URL` |

## Production Considerations

- Change `server.secret_key` in settings.yml
- Use a reverse proxy (nginx/caddy) for HTTPS
- Set `SEARXNG_API_KEY` for authenticated access
- Monitor with: `docker logs -f wrs-searxng`
