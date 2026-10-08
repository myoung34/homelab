"""Printer inventory: a generic printer model loaded from YAML.

Nothing in the agent is specific to a particular printer. Adding a printer is
an entry in printers.yaml (a ConfigMap in the homelab repo).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from printer_agent.safety import RiskLevel


class InventoryError(Exception):
    """The inventory file is missing or invalid."""


class UnknownPrinterError(InventoryError):
    def __init__(self, printer_id: str, known: list[str]) -> None:
        super().__init__(f"unknown printer {printer_id!r}; known printers: {', '.join(known)}")
        self.printer_id = printer_id


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KlipperEndpoint(_Model):
    host: str | None = None
    moonraker_url: str
    fluidd_url: str | None = None
    # Moonraker API key, read from this environment variable if set. The
    # current homelab Moonraker config trusts in-cluster clients, so this is
    # normally unset.
    api_key_env: str | None = None
    config_file: str = "printer.cfg"


class Hardware(_Model):
    mcu: dict[str, str] = Field(default_factory=dict)
    board: str | None = None
    extruder: str | None = None
    hotend: str | None = None
    bed: str | None = None
    probe: str | None = None
    endstops: str | None = None
    motors: str | None = None
    notes: list[str] = Field(default_factory=list)


class Capabilities(_Model):
    camera: bool = False
    bed_mesh: bool = False
    input_shaper: bool = False
    filament_sensor: bool = False
    accelerometer: bool = False


class GitSeed(_Model):
    """Where this printer's config lives in the homelab repo.

    `path` is a ConfigMap manifest and `key` the data key holding printer.cfg.
    In the homelab this is a first-boot *seed*; the live file is on a PVC.
    """

    path: str
    key: str = "printer.cfg"


class KubernetesRef(_Model):
    namespace: str
    selector: str  # label selector, e.g. app.kubernetes.io/instance=enderbig


class PrinterPolicy(_Model):
    max_risk: RiskLevel = RiskLevel.HIGH_RISK_WRITE
    # Upper bounds for printer_set_temperature, independent of (and never
    # above) the max_temp in Klipper's config.
    max_extruder_temp: float = 260.0
    max_bed_temp: float = 100.0

    @field_validator("max_risk", mode="before")
    @classmethod
    def _parse_risk(cls, v: object) -> object:
        return RiskLevel.parse(v) if isinstance(v, str) else v


class Printer(_Model):
    id: str
    name: str
    manufacturer: str | None = None
    model: str | None = None
    enabled: bool = True
    klipper: KlipperEndpoint
    hardware: Hardware = Field(default_factory=Hardware)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    git: GitSeed | None = None
    kubernetes: KubernetesRef | None = None
    policy: PrinterPolicy = Field(default_factory=PrinterPolicy)

    @field_validator("id")
    @classmethod
    def _id_is_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("printer id must be alphanumeric with - or _")
        return v


class Inventory(_Model):
    printers: list[Printer]

    def get(self, printer_id: str) -> Printer:
        for p in self.printers:
            if p.id == printer_id or p.name.lower() == printer_id.lower():
                return p
        raise UnknownPrinterError(printer_id, [p.id for p in self.printers])

    def enabled(self) -> list[Printer]:
        return [p for p in self.printers if p.enabled]


def load_inventory(path: Path) -> Inventory:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise InventoryError(f"inventory file {path} not found") from err
    except yaml.YAMLError as err:
        raise InventoryError(f"inventory file {path} is not valid YAML: {err}") from err
    try:
        inv = Inventory.model_validate(raw)
    except ValueError as err:
        raise InventoryError(f"inventory file {path} is invalid: {err}") from err
    ids = [p.id for p in inv.printers]
    if len(ids) != len(set(ids)):
        raise InventoryError("duplicate printer ids in inventory")
    return inv
