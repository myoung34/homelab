"""Runtime settings, all from environment variables (set in the homelab repo)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from printer_agent.safety import RiskLevel


@dataclass(frozen=True, slots=True)
class Settings:
    inventory_path: Path
    data_dir: Path
    max_risk: RiskLevel
    git_url: str
    git_branch: str
    git_paths: tuple[str, ...]
    git_fetch_ttl: float
    github_repo: str
    github_token: str | None
    taxonomy_extra: Path | None
    poll_interval: float
    http_timeout: float
    host: str
    port: int
    kube_enabled: bool
    max_gcode_bytes: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ) if env is None else env
        extra = e.get("PRINTER_AGENT_TAXONOMY_EXTRA")
        return cls(
            inventory_path=Path(e.get("PRINTER_AGENT_INVENTORY", "/etc/printer-agent/printers.yaml")),
            data_dir=Path(e.get("PRINTER_AGENT_DATA_DIR", "/data")),
            max_risk=RiskLevel.parse(e.get("PRINTER_AGENT_MAX_RISK", "SAFE_AUTOMATION")),
            git_url=e.get("PRINTER_AGENT_GIT_URL", "https://github.com/myoung34/homelab.git"),
            git_branch=e.get("PRINTER_AGENT_GIT_BRANCH", "main"),
            git_paths=tuple(
                p.strip()
                for p in e.get("PRINTER_AGENT_GIT_PATHS", "k8s/prod/klipper,k8s/prod/printer-agent").split(",")
                if p.strip()
            ),
            git_fetch_ttl=float(e.get("PRINTER_AGENT_GIT_FETCH_TTL", "120")),
            github_repo=e.get("PRINTER_AGENT_GITHUB_REPO", "myoung34/homelab"),
            github_token=e.get("GITHUB_TOKEN") or None,
            taxonomy_extra=Path(extra) if extra else None,
            poll_interval=float(e.get("PRINTER_AGENT_POLL_INTERVAL", "30")),
            http_timeout=float(e.get("PRINTER_AGENT_HTTP_TIMEOUT", "10")),
            host=e.get("PRINTER_AGENT_HOST", "0.0.0.0"),  # noqa: S104 - in-cluster service
            port=int(e.get("PRINTER_AGENT_PORT", "8080")),
            kube_enabled=e.get("PRINTER_AGENT_KUBE", "auto") != "off",
            max_gcode_bytes=int(e.get("PRINTER_AGENT_MAX_GCODE_BYTES", str(128 * 1024 * 1024))),
        )
