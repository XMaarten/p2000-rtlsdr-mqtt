from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default or "")

        return _ENV_RE.sub(repl, value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


@dataclass(slots=True)
class ReceiverConfig:
    decoder: str = "multimon"
    frequency_mhz: float = 169.65
    device: str = "0"
    gain: str | float = "auto"
    ppm: int = 0
    sample_rate: int = 22050
    multimon_demodulator: str = "FLEX"
    restart_delay_seconds: float = 5.0
    deflex_command: list[str] = field(default_factory=list)
    deflex_log_file: str = "/data/deflex/169650000.flexdec.log"


@dataclass(slots=True)
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    keepalive: int = 60
    qos: int = 1
    base_topic: str = "p2000"
    home_assistant_discovery: bool = True
    discovery_prefix: str = "homeassistant"


@dataclass(slots=True)
class DatabaseConfig:
    path: str = "/data/p2000.sqlite3"
    auto_update: bool = True
    update_interval_hours: int = 168
    source_url: str = "https://p2000.bommel.net/cap2csv.php"
    min_records: int = 5000


@dataclass(slots=True)
class DedupeConfig:
    window_seconds: int = 30
    max_entries: int = 5000


@dataclass(slots=True)
class GlobalFilterConfig:
    ignore_text: list[str] = field(default_factory=list)
    ignore_capcodes: list[str] = field(default_factory=list)
    ignore_capcodes_mode: str = "any"


@dataclass(slots=True)
class GeocodingConfig:
    enabled: bool = False
    provider: str = "opencage"
    api_key: str = ""
    timeout_seconds: int = 8


@dataclass(slots=True)
class MatchConfig:
    text: list[str] = field(default_factory=list)
    capcodes: list[str] = field(default_factory=list)
    disciplines: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remarks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RouteConfig:
    id: str
    name: str
    icon: str = "mdi:radio-tower"
    include: MatchConfig = field(default_factory=MatchConfig)
    exclude: MatchConfig = field(default_factory=MatchConfig)


@dataclass(slots=True)
class AppConfig:
    log_level: str
    receiver: ReceiverConfig
    mqtt: MqttConfig
    database: DatabaseConfig
    dedupe: DedupeConfig
    global_filters: GlobalFilterConfig
    geocoding: GeocodingConfig
    routes: list[RouteConfig]


def _match(data: dict[str, Any] | None) -> MatchConfig:
    data = data or {}
    return MatchConfig(
        text=_list(data.get("text") or data.get("keyword")),
        capcodes=_list(data.get("capcodes") or data.get("capcode")),
        disciplines=_list(data.get("disciplines") or data.get("discipline")),
        regions=_list(data.get("regions") or data.get("region")),
        locations=_list(data.get("locations") or data.get("location")),
        remarks=_list(data.get("remarks") or data.get("remark")),
    )


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = _expand_env(yaml.safe_load(handle) or {})

    receiver = ReceiverConfig(**(raw.get("receiver") or {}))
    receiver.decoder = receiver.decoder.lower()
    receiver.multimon_demodulator = receiver.multimon_demodulator.upper()
    if receiver.decoder not in {"multimon", "deflex"}:
        raise ValueError("receiver.decoder must be 'multimon' or 'deflex'")
    if receiver.multimon_demodulator not in {"FLEX", "FLEX_NEXT"}:
        raise ValueError("receiver.multimon_demodulator must be FLEX or FLEX_NEXT")

    gf_raw = raw.get("global_filters") or {}
    global_filters = GlobalFilterConfig(
        ignore_text=_list(gf_raw.get("ignore_text")),
        ignore_capcodes=_list(gf_raw.get("ignore_capcodes")),
        ignore_capcodes_mode=str(gf_raw.get("ignore_capcodes_mode", "any")).lower(),
    )
    if global_filters.ignore_capcodes_mode not in {"any", "all"}:
        raise ValueError("ignore_capcodes_mode must be 'any' or 'all'")

    routes: list[RouteConfig] = []
    for item in raw.get("routes") or []:
        route_id = str(item["id"]).strip()
        if not route_id or not re.fullmatch(r"[A-Za-z0-9_-]+", route_id):
            raise ValueError(f"invalid route id: {route_id!r}")
        routes.append(
            RouteConfig(
                id=route_id,
                name=str(item.get("name") or route_id),
                icon=str(item.get("icon") or "mdi:radio-tower"),
                include=_match(item.get("include")),
                exclude=_match(item.get("exclude")),
            )
        )
    if not routes:
        routes = [RouteConfig(id="all", name="P2000")]

    general = raw.get("general") or {}
    return AppConfig(
        log_level=str(general.get("log_level", "INFO")).upper(),
        receiver=receiver,
        mqtt=MqttConfig(**(raw.get("mqtt") or {})),
        database=DatabaseConfig(**(raw.get("database") or {})),
        dedupe=DedupeConfig(**(raw.get("dedupe") or {})),
        global_filters=global_filters,
        geocoding=GeocodingConfig(**(raw.get("geocoding") or {})),
        routes=routes,
    )
