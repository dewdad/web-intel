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


# ─── probe_searxng tests ───────────────────────────────────────────────────────

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


# ─── get_searxng_url tests ────────────────────────────────────────────────────

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
    """Priority 2: env URL fails, but container is running on different port.

    NOTE: ``get_searxng_url`` builds the discovered URL with ``127.0.0.1``
    (not ``localhost``) to dodge IPv6 / wslrelay interception on Windows.
    See commit 5758c2a and the comment in .env.example.
    """
    monkeypatch.setenv("SEARXNG_URL", "http://localhost:8080")

    failing_probe = ProbeResult(reachable=False, engines_degraded=False, url="http://localhost:8080")
    ok_probe = ProbeResult(reachable=True, engines_degraded=False, url="http://127.0.0.1:8888")
    container = ContainerInfo(name="wrs-searxng", status="running", host_port=8888,
                               compose_project="web-intel", volume_sources=[])

    def side_effect(url, **kwargs):
        if "8888" in url:
            return ok_probe
        return failing_probe

    with patch("_docker.probe_searxng", side_effect=side_effect), \
         patch("_docker.discover_container", return_value=container):
        result = get_searxng_url()

    assert result.url == "http://127.0.0.1:8888"
    assert result.engines_degraded is False
    assert os.environ.get("SEARXNG_URL") == "http://127.0.0.1:8888"


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


# ─── ensure_searxng_running tests ─────────────────────────────────────────────

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
