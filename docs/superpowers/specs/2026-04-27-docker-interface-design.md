# Docker Container Interface — Design Spec

**Date:** 2026-04-27  
**Status:** Approved

---

## Problem Statement

The `web-intel` skill's SearXNG search backend fails silently in three distinct ways:

1. **Blind HTTP fire**: `cmd_search` calls `_searxng.search()` which immediately fires an HTTP request to `SEARXNG_URL`. If the container is running on a *different* port than `SEARXNG_URL` specifies (e.g. `8888` vs `8080`), the request fails and falls through to the Brave/ddgs fallback — with no indication that SearXNG was available at all.

2. **Stale volume mount**: The `wrs-searxng` container was originally started from a *different skillshare install path* (`~/.config/skillshare/skills/_dewdad-web-intel/`) that no longer exists. Any changes to `docker/searxng/settings.yml` in the current repo have no effect until the container is recreated against the correct path.

3. **Silent engine rate-limiting**: SearXNG's upstream search engines return `SearxEngineTooManyRequestsException` (suspended_time=180). The current code treats this as a total SearXNG failure and falls back — burning ~5s of timeout before discovering the engine suspension.

---

## Goals

- Auto-detect the running `wrs-searxng` container's actual host port via `docker inspect` — no manual `.env` editing required.
- Surface stale volume mount as a warning with a self-healing `setup --recreate-searxng` flag.
- Distinguish engine-level rate limiting from container-down failures for faster fallback.
- Centralize all Docker/container knowledge in a single reusable `scripts/_docker.py` module.
- Keep the fallback chain (`SearXNG → Brave → ddgs`) intact and unchanged.

---

## Out of Scope

- Changing the fallback chain order or adding new backends.
- Migrating to a different container runtime.
- Changing any fetch/crawl behaviour.

---

## Architecture

### New module: `scripts/_docker.py`

Single source of truth for all Docker interactions. Exposes three public functions:

```
get_searxng_url() -> str
  Resolves the live SearXNG URL:
    1. Try SEARXNG_URL from env — if it probes OK, return it immediately.
    2. Run docker inspect wrs-searxng, extract host port.
    3. Probe discovered URL. If OK, update os.environ["SEARXNG_URL"] and return.
    4. If container exists but is down, log warning, return env value.
    5. If Docker unavailable, return env value (no-op path).
  Side effects: may update os.environ["SEARXNG_URL"] for downstream _searxng.py.

discover_container(name: str) -> ContainerInfo | None
  Runs `docker inspect <name>` (subprocess). Returns ContainerInfo or None.
  Parses: Status, host port from PortBindings, volume mounts, Labels (compose project).

probe_searxng(url: str, timeout: int = 3) -> ProbeResult
  HEAD or GET /search?q=test&format=json. Returns:
    ProbeResult(reachable=True, engines_degraded=False)  — OK
    ProbeResult(reachable=True, engines_degraded=True)   — API up but 0 results (rate-limited)
    ProbeResult(reachable=False, engines_degraded=False)  — connection refused / timeout

ensure_searxng_running(skill_dir: Path) -> EnsureResult
  1. discover_container("wrs-searxng")
  2. If running: check volume mount against skill_dir/docker/searxng. Set stale_mount flag if mismatch.
  3. If not running: docker compose -f skill_dir/docker/docker-compose.searxng.yml up -d
  Returns EnsureResult(started, already_running, stale_mount, stale_mount_hint)

recreate_searxng(skill_dir: Path) -> None
  docker compose -f skill_dir/docker/docker-compose.searxng.yml down --remove-orphans
  docker compose -f skill_dir/docker/docker-compose.searxng.yml up -d
```

### Dataclasses

```python
@dataclass
class ContainerInfo:
    name: str
    status: str           # "running", "exited", "paused", etc.
    host_port: int        # e.g. 8888 (host-side of the port binding)
    compose_project: str | None
    volume_sources: list[str]  # host-side mount paths

@dataclass
class ProbeResult:
    reachable: bool
    engines_degraded: bool   # True = API up but 0 results returned
    url: str
    latency_ms: int

@dataclass
class EnsureResult:
    action: str           # "started" | "already_running" | "failed" | "no_docker"
    stale_mount: bool
    stale_mount_hint: str
    error: str | None
```

---

## Integration Points

### `cmd_search` (web.py)

**Before** calling `_searxng.search()`, add:

```python
from _docker import get_searxng_url
get_searxng_url()  # resolves live URL, updates os.environ as side-effect
```

If `ProbeResult.engines_degraded` is True (available via `get_searxng_url()` internal state), skip SearXNG and jump directly to fallback. This avoids a ~5s timeout on a known-degraded instance.

To expose this, `get_searxng_url()` returns a `ResolvedBackend` named tuple:

```python
ResolvedBackend = namedtuple("ResolvedBackend", ["url", "engines_degraded"])
```

`cmd_search` uses `resolved.engines_degraded` to short-circuit.

### `doctor` (web.py)

Replace:
- `docker ps --filter name=wrs-searxng` subprocess → `discover_container("wrs-searxng")`
- Inline urllib probe → `probe_searxng(url)`

Adds new check:
```json
{"check": "searxng_engines", "status": "ok"|"degraded", "hint": "Engines rate-limited; will use fallback"}
```

Also adds:
```json
{"check": "searxng_volume_mount", "status": "ok"|"stale", "hint": "run: web-intel setup --recreate-searxng"}
```

### `setup` (web.py)

Replace inline `docker ps` + `docker compose up` with `ensure_searxng_running(skill_dir)`.

Add `--recreate-searxng` flag:
```
web-intel setup --recreate-searxng
```
Calls `recreate_searxng(skill_dir)`. Reports result as JSON step.

---

## Port Resolution Contract

`get_searxng_url()` follows this priority order:

1. **Env URL probes OK** → use it, no Docker needed.
2. **Docker available + container running** → inspect port, probe discovered URL. If OK, use it (and update `SEARXNG_URL` env var in-process).
3. **Docker available + container not running** → return env URL (search will fail and fall back, as today).
4. **Docker unavailable** → return env URL (no-op, current behavior preserved).

This means: if SearXNG is running on port 8888 but `.env` says 8080, it still works.

---

## Error Handling

- All `subprocess.run` calls: `capture_output=True`, `timeout=5`, wrapped in `try/except Exception`.
- `docker inspect` returns non-zero if container doesn't exist → `None` returned from `discover_container`.
- `probe_searxng` never raises; always returns a `ProbeResult`.
- `ensure_searxng_running` captures all Docker errors in `EnsureResult.error`.

---

## Testing

Unit tests (no network, no Docker required) in `tests/test_docker.py`:

- `discover_container` with mocked `subprocess.run` JSON output.
- `probe_searxng` with mocked `urllib.request.urlopen` — test OK, degraded, and unreachable paths.
- `get_searxng_url` with mocked `discover_container` + `probe_searxng` — test all 4 priority paths.
- `ensure_searxng_running` — mock container not running → verify compose command called with correct args.

Existing tests must not break. Run `pytest tests/ -v` (excluding `e2e_test.py`) to verify.

---

## Files Changed

| File | Action |
|------|--------|
| `scripts/_docker.py` | **Create** — new module, all Docker logic |
| `scripts/web.py` | **Modify** — `cmd_search`, `doctor`, `setup` |
| `tests/test_docker.py` | **Create** — unit tests for `_docker.py` |
| `.env.example` | **Modify** — clarify `SEARXNG_URL` comment with auto-detection note; keep default `http://localhost:8080` (matches compose default for new installs) |

> **Note:** `docker/docker-compose.searxng.yml` is **not** changed. The port in the compose file (`8080:8080`) is the canonical default for new installs. The auto-detection logic in `get_searxng_url()` handles any mismatch between the running container's port and `SEARXNG_URL` at runtime, making a hardcoded port change in the committed compose file unnecessary and harmful for other users.
