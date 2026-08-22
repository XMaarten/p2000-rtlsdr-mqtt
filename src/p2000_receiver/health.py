from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .config import ReceiverConfig


def _iter_cmdlines(proc_root: Path = Path('/proc')) -> Iterable[tuple[str, ...]]:
    """Yield process command lines from procfs without requiring procps/pgrep."""
    try:
        entries = proc_root.iterdir()
    except OSError:
        return

    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / 'cmdline').read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        args = tuple(part.decode('utf-8', errors='replace') for part in raw.split(b'\0') if part)
        if args:
            yield args


def _has_executable(cmdlines: Iterable[tuple[str, ...]], executable: str) -> bool:
    for args in cmdlines:
        if args and Path(args[0]).name == executable:
            return True
    return False


def _has_command_tokens(cmdlines: Iterable[tuple[str, ...]], tokens: list[str]) -> bool:
    if not tokens:
        return False
    for args in cmdlines:
        if all(token in args for token in tokens):
            return True
    return False


def receiver_is_healthy(config: ReceiverConfig, cmdlines: Iterable[tuple[str, ...]] | None = None) -> bool:
    """Return True when the configured decoder processes are currently running."""
    processes = list(_iter_cmdlines() if cmdlines is None else cmdlines)

    if config.decoder == 'multimon':
        return _has_executable(processes, 'rtl_fm') and _has_executable(processes, 'multimon-ng')

    if config.decoder == 'deflex':
        # Match the configured script/path rather than just `python3`, which would be too broad.
        if len(config.deflex_command) >= 2:
            return _has_command_tokens(processes, [config.deflex_command[1]])
        if config.deflex_command:
            return _has_executable(processes, Path(config.deflex_command[0]).name)
        return False

    return False
