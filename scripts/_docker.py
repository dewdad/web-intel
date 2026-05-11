from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import dataclass, field
from typing import NamedTuple

from _config import get_logger

log = get_logger("docker")

# Default host port for SearXNG — chosen to avoid conflicts with common services
# (8080 = many proxies/dev servers, 8443 = HTTPS alt, 3000/5000 = dev servers)
DEFAULT_SEARXNG_HOST_PORT = 9871

# Candidate ports to try if default is occupied (all uncommon, >9000, no well-known services)
_PORT_CANDIDATES = [9871, 9872, 9873, 9874, 9875, 9881, 9891, 9841, 9851, 9861]


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is free on the given host (bind-based check).

    Uses bind() instead of connect() to detect ports held by Docker/wslrelay
    that accept connections but don't serve HTTP properly.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True  # bind succeeded = port is free
        except OSError:
            return False  # bind failed = port in use


def find_free_port(preferred: int = DEFAULT_SEARXNG_HOST_PORT) -> int:
    """Find a free port, starting with the preferred port then trying candidates.

    Returns the first available port from the candidate list.
    Falls back to OS-assigned ephemeral port if all candidates are taken.
    """
    # Try preferred first
    if is_port_free(preferred):
        return preferred

    # Try candidate list (skip preferred since we already checked)
    for port in _PORT_CANDIDATES:
        if port == preferred:
            continue
        if is_port_free(port):
            log.info("Default port %d in use, selected free port %d", preferred, port)
            return port

    # All candidates taken — ask OS for an ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log.info("All candidate ports in use, using OS-assigned port %d", port)
    return port


@dataclass
class ContainerInfo:
    name: str
    status: str
    host_port: int
    compose_project: str | None
    volume_sources: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    reachable: bool
    engines_degraded: bool
    url: str
    latency_ms: int = 0


@dataclass
class EnsureResult:
    action: str
    stale_mount: bool = False
    stale_mount_hint: str = ""
    error: str | None = None


class ResolvedBackend(NamedTuple):
    url: str
    engines_degraded: bool


def discover_container(name: str) -> ContainerInfo | None:
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

        ports = c.get("NetworkSettings", {}).get("Ports", {})
        host_port = 0
        for _container_port, bindings in ports.items():
            if bindings:
                try:
                    host_port = int(bindings[0].get("HostPort", 0))
                    break
                except (ValueError, TypeError):
                    pass

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


def probe_searxng(url: str, timeout: int = 3) -> ProbeResult:
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


def get_searxng_url() -> ResolvedBackend:
    import os
    from _config import SEARXNG_URL

    env_url = os.environ.get("SEARXNG_URL", SEARXNG_URL)

    env_probe = probe_searxng(env_url)
    if env_probe.reachable:
        return ResolvedBackend(url=env_url, engines_degraded=env_probe.engines_degraded)

    info = discover_container("wrs-searxng")
    if info is None or info.host_port == 0:
        return ResolvedBackend(url=env_url, engines_degraded=False)

    if info.status != "running":
        log.debug("wrs-searxng container exists but status=%s", info.status)
        return ResolvedBackend(url=env_url, engines_degraded=False)

    discovered_url = f"http://127.0.0.1:{info.host_port}"
    docker_probe = probe_searxng(discovered_url)

    if docker_probe.reachable:
        if discovered_url != env_url:
            log.info(
                "SearXNG running on port %d, overriding SEARXNG_URL (was %s)",
                info.host_port, env_url,
            )
            os.environ["SEARXNG_URL"] = discovered_url
        return ResolvedBackend(url=discovered_url, engines_degraded=docker_probe.engines_degraded)

    log.debug("wrs-searxng container running but probe failed on port %d", info.host_port)
    return ResolvedBackend(url=env_url, engines_degraded=False)


def _compose_env(skill_dir: "Path", port: int | None = None) -> dict[str, str]:
    """Build environment dict for docker-compose with the resolved host port."""
    import os
    env = os.environ.copy()
    if port is not None:
        env["SEARXNG_HOST_PORT"] = str(port)
    elif "SEARXNG_HOST_PORT" not in env:
        env["SEARXNG_HOST_PORT"] = str(DEFAULT_SEARXNG_HOST_PORT)
    return env


def ensure_searxng_running(skill_dir: "Path") -> EnsureResult:
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

    # Find a free port for the host binding
    import os
    preferred = int(os.environ.get("SEARXNG_HOST_PORT", str(DEFAULT_SEARXNG_HOST_PORT)))
    host_port = find_free_port(preferred)
    env = _compose_env(skill_dir, port=host_port)

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if result.returncode != 0:
            return EnsureResult(action="failed", error=result.stderr.strip())

        # Update runtime SEARXNG_URL to reflect the actual port used
        os.environ["SEARXNG_URL"] = f"http://127.0.0.1:{host_port}"
        os.environ["SEARXNG_HOST_PORT"] = str(host_port)
        log.info("SearXNG started on port %d", host_port)
        return EnsureResult(action="started")
    except FileNotFoundError:
        return EnsureResult(action="no_docker")
    except Exception as exc:
        return EnsureResult(action="failed", error=str(exc))


def recreate_searxng(skill_dir: "Path") -> EnsureResult:
    import os
    from pathlib import Path

    compose_file = Path(skill_dir) / "docker" / "docker-compose.searxng.yml"

    # Find a free port for the host binding
    preferred = int(os.environ.get("SEARXNG_HOST_PORT", str(DEFAULT_SEARXNG_HOST_PORT)))
    host_port = find_free_port(preferred)
    env = _compose_env(skill_dir, port=host_port)

    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "down", "--remove-orphans"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        if result.returncode != 0:
            return EnsureResult(action="failed", error=result.stderr.strip())

        os.environ["SEARXNG_URL"] = f"http://127.0.0.1:{host_port}"
        os.environ["SEARXNG_HOST_PORT"] = str(host_port)
        log.info("SearXNG recreated on port %d", host_port)
        return EnsureResult(action="started")
    except FileNotFoundError:
        return EnsureResult(action="no_docker")
    except Exception as exc:
        return EnsureResult(action="failed", error=str(exc))
