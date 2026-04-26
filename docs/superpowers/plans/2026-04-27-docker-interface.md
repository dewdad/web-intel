# Docker Container Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `scripts/_docker.py` as a reusable Docker/SearXNG interface module, fix the port auto-detection issue, surface stale volume mounts, short-circuit on engine rate-limiting, and wire it into `cmd_search`, `doctor`, and `setup`.

**Architecture:** A new `scripts/_docker.py` module owns all Docker subprocess calls and SearXNG health probing. `cmd_search` calls `get_searxng_url()` once before firing `_searxng.search()`, which resolves the live container port via `docker inspect` and updates `os.environ["SEARXNG_URL"]` as a side-effect. `doctor` and `setup` use `discover_container()`, `probe_searxng()`, and `ensure_searxng_running()` to replace duplicated inline subprocess boilerplate.

**Tech Stack:** Python 3.11+, stdlib only (`subprocess`, `urllib.request`, `dataclasses`, `collections.namedtuple`), pytest with `unittest.mock`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/_docker.py` | **Create** | All Docker/SearXNG container logic |
| `tests/test_docker.py` | **Create** | Unit tests for `_docker.py` (no Docker required) |
| `scripts/web.py` | **Modify** | Wire `_docker` into `cmd_search`, `doctor`, `setup` |
| `.env.example` | **Modify** | Clarify `SEARXNG_URL` comment with auto-detection note; keep default `8080` |

> **`docker/docker-compose.searxng.yml` is intentionally NOT changed.** Port `8080:8080` is the correct canonical default for new installs. The `get_searxng_url()` auto-detection handles any runtime port mismatch, making a hardcoded port commit unnecessary and harmful for other users.

---

## Task 1: Create `scripts/_docker.py` — dataclasses and `discover_container`

**Files:**
- Create: `scripts/_docker.py`

- [ ] **Step 1: Write the failing test for `discover_container` — running container**

```python
# tests/test_docker.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import json
from unittest.mock import patch, MagicMock
from _docker import discover_container, ContainerInfo

MOCK_INSPECT = json.dumps([{
    "Name": "/wrs-searxng",
    "State": {"Status": "running"},
    "HostConfig": {},
    "Config": {"Labels": {"com.docker.compose.project": "web-intel"}},
    "Mounts": [{"Source": "/home/user/web-intel/docker/searxng", "Destination": "/etc/searxng"}],
    "NetworkSettings": {
        "Ports": {
            "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8888"}]
        }
    }
}])

def test_discover_container_running():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = MOCK_INSPECT

    with patch("subprocess.run", return_value=mock_result):
        info = discover_container("wrs-searxng")

    assert info is not None
    assert isinstance(info, ContainerInfo)
    assert info.name == "wrs-searxng"
    assert info.status == "running"
    assert info.host_port == 8888
    assert info.compose_project == "web-intel"
    assert "/home/user/web-intel/docker/searxng" in info.volume_sources


def test_discover_container_not_found():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        info = discover_container("wrs-searxng")

    assert info is None


def test_discover_container_no_docker():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        info = discover_container("wrs-searxng")
    assert info is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named '_docker'`

- [ ] **Step 3: Implement `_docker.py` with dataclasses and `discover_container`**

```python
# scripts/_docker.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import NamedTuple

from _config import get_logger

log = get_logger("docker")


@dataclass
class ContainerInfo:
    name: str
    status: str           # "running", "exited", "paused", etc.
    host_port: int        # host-side port (e.g. 8888)
    compose_project: str | None
    volume_sources: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    reachable: bool
    engines_degraded: bool  # True = API up but 0 results (rate-limited engines)
    url: str
    latency_ms: int = 0


@dataclass
class EnsureResult:
    action: str           # "started" | "already_running" | "failed" | "no_docker"
    stale_mount: bool = False
    stale_mount_hint: str = ""
    error: str | None = None


class ResolvedBackend(NamedTuple):
    url: str
    engines_degraded: bool


def discover_container(name: str) -> ContainerInfo | None:
    """Run `docker inspect <name>` and return parsed ContainerInfo, or None."""
    try:
        result = subprocess.run(
            ["docker", "inspect", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        data = json.loads(result.stdout)
        if not data:
            return None
        c = data[0]

        status = c.get("State", {}).get("Status", "unknown")
        labels = c.get("Config", {}).get("Labels", {}) or {}
        compose_project = labels.get("com.docker.compose.project")

        # Extract host port from PortBindings
        ports = c.get("NetworkSettings", {}).get("Ports", {})
        host_port = 0
        for _container_port, bindings in ports.items():
            if bindings:
                try:
                    host_port = int(bindings[0].get("HostPort", 0))
                    break
                except (ValueError, TypeError):
                    pass

        # Extract volume mount sources
        volume_sources = [
            m.get("Source", "") for m in c.get("Mounts", []) if m.get("Source")
        ]

        return ContainerInfo(
            name=name.lstrip("/"),
            status=status,
            host_port=host_port,
            compose_project=compose_project,
            volume_sources=volume_sources,
        )
    except (json.JSONDecodeError, KeyError, IndexError):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py::test_discover_container_running tests/test_docker.py::test_discover_container_not_found tests/test_docker.py::test_discover_container_no_docker -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/_docker.py tests/test_docker.py
git commit -m "feat: add _docker.py with ContainerInfo dataclass and discover_container"
```

---

## Task 2: Add `probe_searxng` to `_docker.py`

**Files:**
- Modify: `scripts/_docker.py`
- Modify: `tests/test_docker.py`

- [ ] **Step 1: Write the failing tests for `probe_searxng`**

Add to `tests/test_docker.py`:

```python
import time
from unittest.mock import patch, MagicMock
from _docker import probe_searxng, ProbeResult


def _mock_urlopen(body: bytes, status: int = 200):
    """Helper: return a mock context manager for urlopen."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(
        status=status,
        read=MagicMock(return_value=body),
    ))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_probe_searxng_ok():
    body = json.dumps({"results": [{"url": "https://example.com"}]}).encode()
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
        result = probe_searxng("http://localhost:8888")
    assert result.reachable is True
    assert result.engines_degraded is False
    assert result.url == "http://localhost:8888"


def test_probe_searxng_engines_degraded():
    # API up but zero results = engines suspended
    body = json.dumps({"results": []}).encode()
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
        result = probe_searxng("http://localhost:8888")
    assert result.reachable is True
    assert result.engines_degraded is True


def test_probe_searxng_unreachable():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        result = probe_searxng("http://localhost:8888")
    assert result.reachable is False
    assert result.engines_degraded is False


def test_probe_searxng_non_json_response():
    body = b"<html>Not JSON</html>"
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
        result = probe_searxng("http://localhost:8888")
    # Non-JSON means SearXNG returned HTML (json format not enabled)
    assert result.reachable is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -k "probe" -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'probe_searxng'`

- [ ] **Step 3: Implement `probe_searxng` in `_docker.py`**

Add after the `ContainerInfo`/`ProbeResult` dataclasses:

```python
def probe_searxng(url: str, timeout: int = 3) -> ProbeResult:
    """Probe SearXNG API. Returns ProbeResult with reachable + engines_degraded flags."""
    import time
    import urllib.request
    import urllib.error

    probe_url = f"{url.rstrip('/')}/search?q=test&format=json"
    start = time.monotonic()
    try:
        req = urllib.request.Request(probe_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if resp.status != 200:
                return ProbeResult(reachable=False, engines_degraded=False,
                                   url=url, latency_ms=elapsed_ms)
            body = resp.read()
    except Exception:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProbeResult(reachable=False, engines_degraded=False,
                           url=url, latency_ms=elapsed_ms)

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return ProbeResult(reachable=False, engines_degraded=False,
                           url=url, latency_ms=elapsed_ms)

    engines_degraded = len(data.get("results", [])) == 0
    return ProbeResult(reachable=True, engines_degraded=engines_degraded,
                       url=url, latency_ms=elapsed_ms)
```

- [ ] **Step 4: Run to verify passage**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -k "probe" -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/_docker.py tests/test_docker.py
git commit -m "feat: add probe_searxng to _docker.py with degraded-engine detection"
```

---

## Task 3: Add `get_searxng_url` to `_docker.py`

**Files:**
- Modify: `scripts/_docker.py`
- Modify: `tests/test_docker.py`

- [ ] **Step 1: Write the failing tests for `get_searxng_url`**

Add to `tests/test_docker.py`:

```python
import os
from _docker import get_searxng_url, ResolvedBackend


def test_get_searxng_url_env_url_works(monkeypatch):
    """Priority 1: env URL probes OK — return it without touching Docker."""
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")
    good_probe = ProbeResult(reachable=True, engines_degraded=False, url="http://localhost:8080")

    with patch("_docker.probe_searxng", return_value=good_probe) as mock_probe, \
         patch("_docker.discover_container") as mock_discover:
        result = get_searxng_url()

    assert result.url == "http://localhost:8080"
    assert result.engines_degraded is False
    mock_discover.assert_not_called()  # Docker not consulted when env URL works


def test_get_searxng_url_env_fails_docker_works(monkeypatch):
    """Priority 2: env URL fails, but container is running on different port."""
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")

    failing_probe = ProbeResult(reachable=False, engines_degraded=False, url="http://localhost:8080")
    ok_probe = ProbeResult(reachable=True, engines_degraded=False, url="http://localhost:8888")
    container = ContainerInfo(name="wrs-searxng", status="running", host_port=8888,
                               compose_project="web-intel", volume_sources=[])

    def side_effect(url, **kwargs):
        if "8888" in url:
            return ok_probe
        return failing_probe

    with patch("_docker.probe_searxng", side_effect=side_effect), \
         patch("_docker.discover_container", return_value=container):
        result = get_searxng_url()

    assert result.url == "http://localhost:8888"
    assert result.engines_degraded is False
    assert os.environ.get("SEARXNG_URL") == "http://localhost:8888"


def test_get_searxng_url_container_running_but_crashed(monkeypatch):
    """Container exists + running, but SearXNG process inside is dead — fall back to env URL."""
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")

    failing_probe = ProbeResult(reachable=False, engines_degraded=False, url="")
    container = ContainerInfo(name="wrs-searxng", status="running", host_port=8888,
                               compose_project=None, volume_sources=[])

    with patch("_docker.probe_searxng", return_value=failing_probe), \
         patch("_docker.discover_container", return_value=container):
        result = get_searxng_url()

    # Returns env URL silently — upstream _searxng.py will fail and trigger fallback chain
    assert result.url == "http://localhost:8080"


def test_get_searxng_url_no_docker(monkeypatch):
    """Priority 4: Docker not available — return env URL, no-op."""
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")
    failing_probe = ProbeResult(reachable=False, engines_degraded=False, url="http://localhost:8080")

    with patch("_docker.probe_searxng", return_value=failing_probe), \
         patch("_docker.discover_container", return_value=None):
        result = get_searxng_url()

    assert result.url == "http://localhost:8080"


def test_get_searxng_url_engines_degraded(monkeypatch):
    """Env URL reachable but engines rate-limited — return it with degraded=True."""
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")
    degraded_probe = ProbeResult(reachable=True, engines_degraded=True, url="http://localhost:8080")

    with patch("_docker.probe_searxng", return_value=degraded_probe):
        result = get_searxng_url()

    assert result.url == "http://localhost:8080"
    assert result.engines_degraded is True
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -k "get_searxng_url" -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'get_searxng_url'`

- [ ] **Step 3: Implement `get_searxng_url` in `_docker.py`**

Add after `probe_searxng`:

```python
def get_searxng_url() -> ResolvedBackend:
    """Resolve the live SearXNG URL using the priority chain.

    Priority:
      1. SEARXNG_URL from env probes OK → return it.
      2. Docker available + container running → inspect port, probe. If OK → update env + return.
      3. Container running but unresponsive → return env URL silently (fallback chain handles it).
      4. Docker unavailable / container not found → return env URL (no-op path).
    """
    import os
    from _config import SEARXNG_URL

    env_url = os.environ.get("SEARXNG_URL", SEARXNG_URL)

    # Priority 1: env URL works → fast path, no Docker needed
    env_probe = probe_searxng(env_url)
    if env_probe.reachable:
        return ResolvedBackend(url=env_url, engines_degraded=env_probe.engines_degraded)

    # Priority 2: env URL failed — try Docker
    info = discover_container("wrs-searxng")
    if info is None or info.host_port == 0:
        # Docker unavailable or container not found — return env URL
        return ResolvedBackend(url=env_url, engines_degraded=False)

    if info.status != "running":
        # Container exists but is stopped
        log.debug("wrs-searxng container exists but status=%s", info.status)
        return ResolvedBackend(url=env_url, engines_degraded=False)

    # Container is running — probe its actual port
    discovered_url = f"http://localhost:{info.host_port}"
    docker_probe = probe_searxng(discovered_url)

    if docker_probe.reachable:
        if discovered_url != env_url:
            log.info(
                "SearXNG running on port %d, overriding SEARXNG_URL (was %s)",
                info.host_port, env_url,
            )
            os.environ["SEARXNG_URL"] = discovered_url
        return ResolvedBackend(url=discovered_url, engines_degraded=docker_probe.engines_degraded)

    # Priority 3: container running but SearXNG process unresponsive — return env URL silently
    log.debug("wrs-searxng container running but probe failed on port %d", info.host_port)
    return ResolvedBackend(url=env_url, engines_degraded=False)
```

- [ ] **Step 4: Run to verify passage**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -k "get_searxng_url" -v
```
Expected: 5 PASSED

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/ --ignore=tests/e2e_test.py -v 2>&1 | tail -20
```
Expected: all previously passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add scripts/_docker.py tests/test_docker.py
git commit -m "feat: add get_searxng_url with port auto-detection and env override"
```

---

## Task 4: Add `ensure_searxng_running` and `recreate_searxng` to `_docker.py`

**Files:**
- Modify: `scripts/_docker.py`
- Modify: `tests/test_docker.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_docker.py`:

```python
from pathlib import Path
from _docker import ensure_searxng_running, EnsureResult


SKILL_DIR = Path("/fake/skill")
COMPOSE_FILE = SKILL_DIR / "docker" / "docker-compose.searxng.yml"


def test_ensure_searxng_already_running_clean_mount():
    container = ContainerInfo(
        name="wrs-searxng", status="running", host_port=8888,
        compose_project=None,
        volume_sources=[str(SKILL_DIR / "docker" / "searxng")],
    )
    with patch("_docker.discover_container", return_value=container):
        result = ensure_searxng_running(SKILL_DIR)

    assert result.action == "already_running"
    assert result.stale_mount is False


def test_ensure_searxng_already_running_stale_mount():
    container = ContainerInfo(
        name="wrs-searxng", status="running", host_port=8888,
        compose_project=None,
        volume_sources=["/some/other/path/docker/searxng"],
    )
    with patch("_docker.discover_container", return_value=container):
        result = ensure_searxng_running(SKILL_DIR)

    assert result.action == "already_running"
    assert result.stale_mount is True
    assert "recreate-searxng" in result.stale_mount_hint


def test_ensure_searxng_not_running_starts_container():
    mock_run = MagicMock()
    mock_run.returncode = 0

    with patch("_docker.discover_container", return_value=None), \
         patch("subprocess.run", return_value=mock_run) as mock_compose:
        result = ensure_searxng_running(SKILL_DIR)

    assert result.action == "started"
    # Verify compose up was called with the correct file
    call_args = mock_compose.call_args[0][0]
    assert "docker" in call_args
    assert "compose" in call_args
    assert "up" in call_args


def test_ensure_searxng_no_docker():
    with patch("_docker.discover_container", side_effect=FileNotFoundError):
        result = ensure_searxng_running(SKILL_DIR)
    assert result.action == "no_docker"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -k "ensure" -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'ensure_searxng_running'`

- [ ] **Step 3: Implement `ensure_searxng_running` and `recreate_searxng`**

Add to `_docker.py`:

```python
def ensure_searxng_running(skill_dir: "Path") -> EnsureResult:
    """Check if wrs-searxng is running; start it if not. Report stale volume mounts."""
    from pathlib import Path

    expected_mount = str(Path(skill_dir) / "docker" / "searxng")
    compose_file = Path(skill_dir) / "docker" / "docker-compose.searxng.yml"

    try:
        info = discover_container("wrs-searxng")
    except FileNotFoundError:
        return EnsureResult(action="no_docker")

    if info is not None and info.status == "running":
        stale = expected_mount not in info.volume_sources
        hint = (
            f"run: web-intel setup --recreate-searxng  "
            f"(container using {info.volume_sources} instead of {expected_mount})"
            if stale else ""
        )
        return EnsureResult(action="already_running", stale_mount=stale, stale_mount_hint=hint)

    # Not running — start it
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return EnsureResult(action="failed", error=result.stderr.strip())
        return EnsureResult(action="started")
    except FileNotFoundError:
        return EnsureResult(action="no_docker")
    except Exception as exc:
        return EnsureResult(action="failed", error=str(exc))


def recreate_searxng(skill_dir: "Path") -> EnsureResult:
    """Tear down and recreate wrs-searxng container (fixes stale volume mounts)."""
    from pathlib import Path

    compose_file = Path(skill_dir) / "docker" / "docker-compose.searxng.yml"
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "down", "--remove-orphans"],
            capture_output=True, text=True, timeout=30,
        )
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return EnsureResult(action="failed", error=result.stderr.strip())
        return EnsureResult(action="started")
    except FileNotFoundError:
        return EnsureResult(action="no_docker")
    except Exception as exc:
        return EnsureResult(action="failed", error=str(exc))
```

- [ ] **Step 4: Run to verify passage**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/test_docker.py -k "ensure" -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/_docker.py tests/test_docker.py
git commit -m "feat: add ensure_searxng_running and recreate_searxng to _docker.py"
```

---

## Task 5: Wire `_docker` into `cmd_search` in `web.py`

**Files:**
- Modify: `scripts/web.py` (function `cmd_search`, approx line 126)

- [ ] **Step 1: Read current `cmd_search` to confirm line numbers**

```bash
grep -n "def cmd_search\|from _searxng\|result = search(" /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py | head -10
```

- [ ] **Step 2: Add `get_searxng_url` call at the top of `cmd_search`**

Find this block (after `args = _apply_search_mode(args)`):

```python
def cmd_search(args: argparse.Namespace) -> None:
    args = _apply_search_mode(args)
    from _searxng import search

    result = search(
```

Replace with:

```python
def cmd_search(args: argparse.Namespace) -> None:
    args = _apply_search_mode(args)
    from _searxng import search
    from _docker import get_searxng_url

    resolved = get_searxng_url()

    # Short-circuit to fallback if SearXNG engines are known-degraded
    if resolved.engines_degraded and not getattr(args, "no_fallback", False):
        log.info("SearXNG engines degraded (rate-limited), skipping to fallback")
        result = None
    else:
        result = search(
            args.query,
            engines=args.engines,
            categories=args.categories,
            language=args.language,
            time_range=args.time_range,
            max_results=args.max_results,
            pageno=args.pageno,
            no_rerank=getattr(args, "no_rerank", False),
        )

    if result is None or (result.status == "failed" and not getattr(args, "no_fallback", False)):
```

- [ ] **Step 3: Locate the exact fallback block to replace**

```bash
grep -n "result.status == .failed. and not getattr" /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py
```

Expected output: one line like `141:    if result.status == "failed" and not getattr(args, "no_fallback", False):`

In the editor, replace **only that one condition line** with:
```python
    if result is None or (result.status == "failed" and not getattr(args, "no_fallback", False)):
```

The fallback body (brave key check → `search_brave` → `search_ddgs`) stays **completely unchanged**. The only edit is the `if` condition on that single line.

- [ ] **Step 4: Run all tests to verify no regressions**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/ --ignore=tests/e2e_test.py -v 2>&1 | tail -20
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add scripts/web.py
git commit -m "feat: wire get_searxng_url into cmd_search with engine-degraded short-circuit"
```

---

## Task 6: Wire `_docker` into `doctor` in `web.py`

**Files:**
- Modify: `scripts/web.py` (function `cmd_doctor`, approx lines 620–700)

- [ ] **Step 1: Locate the doctor Docker checks**

```bash
grep -n "searxng_ok\|searxng_docker\|searxng_api\|docker ps" /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py | head -20
```

- [ ] **Step 1b: Confirm `_SKILL_DIR` is already defined at module level**

```bash
grep -n "^_SKILL_DIR" /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py | head -5
```

Expected: `10:_SKILL_DIR = _SCRIPTS_DIR.parent` (or similar). This variable is available throughout `web.py` — no redefinition needed in the replacement block.

- [ ] **Step 2: Replace the duplicated Docker subprocess blocks**

Find and replace the block from `# 4. Docker available` through `# 6. SearXNG API reachable` (the `docker ps` subprocess + inline urllib probe). Replace with:

```python
    # 4. Docker available
    docker_ok = shutil.which("docker") is not None
    checks.append({
        "check": "docker",
        "status": "ok" if docker_ok else "missing",
        "hint": "" if docker_ok else "Install Docker: https://docs.docker.com/get-docker/",
    })

    # 5–6. SearXNG container + API (via _docker module)
    from _docker import discover_container, probe_searxng, EnsureResult
    from _config import SEARXNG_URL

    searxng_info = discover_container("wrs-searxng") if docker_ok else None
    searxng_running = searxng_info is not None and searxng_info.status == "running"

    checks.append({
        "check": "searxng_docker",
        "status": "ok" if searxng_running else "not_running",
        "hint": "" if searxng_running
                else f"docker compose -f {_SKILL_DIR}/docker/docker-compose.searxng.yml up -d",
    })

    # Determine URL to probe (use actual port if container is running)
    probe_url = (
        f"http://localhost:{searxng_info.host_port}"
        if searxng_running and searxng_info.host_port
        else os.environ.get("SEARXNG_URL", SEARXNG_URL)
    )
    searxng_probe = probe_searxng(probe_url) if searxng_running else None

    checks.append({
        "check": "searxng_api",
        "status": "ok" if (searxng_probe and searxng_probe.reachable) else ("skip" if not searxng_running else "fail"),
        "hint": "" if (searxng_probe and searxng_probe.reachable)
                else "Ensure 'json' is in search.formats in docker/searxng/settings.yml",
    })

    # New check: engine-level rate limiting
    engines_degraded = searxng_probe.engines_degraded if searxng_probe else False
    checks.append({
        "check": "searxng_engines",
        "status": "degraded" if engines_degraded else ("ok" if (searxng_probe and searxng_probe.reachable) else "skip"),
        "hint": "Upstream engines rate-limited; will auto-fallback to Brave/ddgs" if engines_degraded else "",
    })

    # New check: stale volume mount
    if searxng_running and searxng_info.volume_sources:
        expected_mount = str(_SKILL_DIR / "docker" / "searxng")
        stale = expected_mount not in searxng_info.volume_sources
        checks.append({
            "check": "searxng_volume_mount",
            "status": "stale" if stale else "ok",
            "hint": "run: web-intel setup --recreate-searxng" if stale else "",
        })
```

- [ ] **Step 3: Update `search_backend` resolution to use `probe_url`**

Find the `search_backend = ...` ternary near the end of `cmd_doctor` (approx line 842) and update it to use `searxng_probe` instead of `searxng_api_ok`:

```python
    searxng_api_ok = bool(searxng_probe and searxng_probe.reachable and not searxng_probe.engines_degraded)
    search_backend = (
        "searxng" if searxng_api_ok
        else "brave" if brave_key
        else "ddgs" if ddgs_ok
        else "none"
    )
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/ --ignore=tests/e2e_test.py -v 2>&1 | tail -20
```
Expected: all pass

- [ ] **Step 5: Smoke test `doctor`**

```bash
/Users/i071496/copilot-projects/web-intel-skill/bin/web-intel doctor --pretty 2>/dev/null | python3.13 -c "
import json, sys
d = json.load(sys.stdin)
print('search_backend:', d.get('search_backend'))
for c in d.get('checks', []):
    if 'searxng' in c['check']:
        print(c['check'], '->', c['status'], c.get('hint',''))
"
```
Expected: `search_backend: searxng`, `searxng_docker -> ok`, `searxng_api -> ok`, new `searxng_engines` and `searxng_volume_mount` checks visible.

- [ ] **Step 6: Commit**

```bash
git add scripts/web.py
git commit -m "feat: replace doctor Docker checks with _docker module; add engine/volume checks"
```

---

## Task 7: Wire `_docker` into `setup` + add `--recreate-searxng` flag

**Files:**
- Modify: `scripts/web.py` (function `cmd_setup` and argument parser)

- [ ] **Step 1: Locate setup Docker block**

```bash
grep -n "def cmd_setup\|searxng.*started\|ensure_searxng\|docker.*compose.*up" /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py | head -15
```

- [ ] **Step 2: Replace inline `docker ps` + `docker compose up` in `cmd_setup`**

Find the `# 3. Start SearXNG if Docker available` block and replace it:

```python
    # 3. Start SearXNG if Docker available and not running
    from _docker import ensure_searxng_running, recreate_searxng

    if getattr(args, "recreate_searxng", False):
        result = recreate_searxng(_SKILL_DIR)
        steps.append({"step": "searxng", "status": result.action,
                      "error": result.error} if result.error
                     else {"step": "searxng", "status": "recreated"})
    elif shutil.which("docker"):
        result = ensure_searxng_running(_SKILL_DIR)
        step = {"step": "searxng", "status": result.action}
        if result.stale_mount:
            step["warning"] = result.stale_mount_hint
        if result.error:
            step["error"] = result.error
        steps.append(step)
    else:
        steps.append({"step": "searxng", "status": "skip", "hint": "Docker not found"})
```

- [ ] **Step 3: Add `--recreate-searxng` to the `setup` argument parser**

Find the `setup` subparser definition (search for `add_parser.*setup`):

```bash
grep -n "add_parser.*setup\|setup.*add_argument" /Users/i071496/copilot-projects/web-intel-skill/scripts/web.py | head -10
```

Add after the existing `setup` parser arguments:

```python
p_setup.add_argument(
    "--recreate-searxng",
    action="store_true",
    default=False,
    help="Tear down and recreate the wrs-searxng container (fixes stale volume mounts).",
)
```

- [ ] **Step 4: Do the same replacement for the Crawl4AI Docker block**

Find the `# 4. Start Crawl4AI Docker container` block and replace with the exact same inline subprocess logic — Crawl4AI uses a different container name (`wrs-crawl4ai`) and is intentionally kept as inline subprocess code (not using `_docker` module). **No import from `_docker` is needed here.** The replacement code is identical to what's already there, just confirming no accidental changes:

```python
    # 4. Start Crawl4AI Docker container (only if tier=all)
    if tier == "all" and shutil.which("docker"):
        out = subprocess.run(
            ["docker", "ps", "--filter", "name=wrs-crawl4ai", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        if "Up" not in out.stdout:
            compose_file = _SKILL_DIR / "docker" / "docker-compose.yml"
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "up", "-d", "crawl4ai"],
                capture_output=True, text=True, timeout=120,
            )
            steps.append({"step": "crawl4ai_docker", "status": "started"})
        else:
            steps.append({"step": "crawl4ai_docker", "status": "already_running"})
```
*(No changes to Crawl4AI logic — this step only confirms the SearXNG block was replaced without accidentally touching the Crawl4AI block below it.)*

- [ ] **Step 5: Run all tests**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/ --ignore=tests/e2e_test.py -v 2>&1 | tail -20
```
Expected: all pass

- [ ] **Step 6: Smoke test `setup`**

```bash
/Users/i071496/copilot-projects/web-intel-skill/bin/web-intel setup --pretty 2>/dev/null | python3.13 -c "
import json, sys
d = json.load(sys.stdin)
for s in d.get('steps', []):
    print(s)
"
```
Expected: `{'step': 'searxng', 'status': 'already_running'}` (or `started`)

- [ ] **Step 7: Commit**

```bash
git add scripts/web.py
git commit -m "feat: replace setup Docker logic with ensure_searxng_running; add --recreate-searxng"
```

---

## Task 8: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Update the SEARXNG_URL comment**

Change:
```
# SearXNG instance URL (required for search command)
SEARXNG_URL=http://localhost:8080
```

To:
```
# SearXNG instance URL — default matches docker-compose.searxng.yml (port 8080:8080).
# If your container runs on a different port (e.g. 8888), web-intel auto-detects it via
# docker inspect and updates this value at runtime. Manual override only needed if
# SEARXNG_URL auto-detection is disabled.
SEARXNG_URL=http://localhost:8080
```

- [ ] **Step 2: Run full test suite one final time**

```bash
cd /Users/i071496/copilot-projects/web-intel-skill
python3.13 -m pytest tests/ --ignore=tests/e2e_test.py -v 2>&1 | tail -10
```
Expected: all previously passing tests still pass, new `test_docker.py` tests pass.

- [ ] **Step 3: Final commit**

```bash
git add .env.example
git commit -m "docs: clarify SEARXNG_URL in .env.example with auto-detection note"
```

---

## Summary

After all tasks complete:

- `scripts/_docker.py` — new module: `discover_container`, `probe_searxng`, `get_searxng_url`, `ensure_searxng_running`, `recreate_searxng`
- `tests/test_docker.py` — ~15 unit tests, all no-Docker, no-network
- `scripts/web.py` — `cmd_search` auto-detects live port + short-circuits on degraded engines; `doctor` uses `_docker` module + reports `searxng_engines` and `searxng_volume_mount`; `setup` uses `ensure_searxng_running` + exposes `--recreate-searxng`
- `.env.example` — clarified comment
