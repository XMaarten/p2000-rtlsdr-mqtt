from __future__ import annotations

from fnmatch import fnmatchcase

from .config import GlobalFilterConfig, MatchConfig, RouteConfig
from .models import P2000Message


def _matches(patterns: list[str], values: list[str]) -> bool:
    if not patterns:
        return True
    p = [pattern.casefold() for pattern in patterns]
    return any(fnmatchcase(value.casefold(), pattern) for value in values for pattern in p)


def _any_matches(patterns: list[str], values: list[str]) -> bool:
    if not patterns:
        return False
    p = [pattern.casefold() for pattern in patterns]
    return any(fnmatchcase(value.casefold(), pattern) for value in values for pattern in p)


def globally_ignored(message: P2000Message, config: GlobalFilterConfig) -> bool:
    if _any_matches(config.ignore_text, [message.body]):
        return True
    if config.ignore_capcodes and message.capcodes:
        per_code = [
            _any_matches(config.ignore_capcodes, [capcode]) for capcode in message.capcodes
        ]
        if config.ignore_capcodes_mode == "all":
            return all(per_code)
        return any(per_code)
    return False


def _include_matches(message: P2000Message, include: MatchConfig) -> bool:
    checks = [
        _matches(include.text, [message.body]),
        _matches(include.capcodes, message.capcodes),
        _matches(include.disciplines, message.disciplines),
        _matches(include.regions, message.regions),
        _matches(include.locations, message.locations),
        _matches(include.remarks, message.remarks),
    ]
    return all(checks)


def _exclude_matches(message: P2000Message, exclude: MatchConfig) -> bool:
    return any([
        _any_matches(exclude.text, [message.body]),
        _any_matches(exclude.capcodes, message.capcodes),
        _any_matches(exclude.disciplines, message.disciplines),
        _any_matches(exclude.regions, message.regions),
        _any_matches(exclude.locations, message.locations),
        _any_matches(exclude.remarks, message.remarks),
    ])


def route_matches(message: P2000Message, route: RouteConfig) -> bool:
    return _include_matches(message, route.include) and not _exclude_matches(message, route.exclude)
