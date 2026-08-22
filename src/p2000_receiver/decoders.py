from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from .config import ReceiverConfig
from .models import RawPage
from .parsers import parse_deflex_log_line, parse_multimon_line

_LOG = logging.getLogger(__name__)

def build_rtl_command(config: ReceiverConfig) -> list[str]:
    """Build rtl_fm command. `device` may be an index or an RTL-SDR serial number."""
    command = [
        "rtl_fm", "-f", f"{config.frequency_mhz}M", "-M", "fm",
        "-s", str(config.sample_rate), "-d", str(config.device),
        "-p", str(config.ppm),
    ]
    if str(config.gain).lower() != "auto":
        command += ["-g", str(config.gain)]
    return command


def build_multimon_command(config: ReceiverConfig) -> list[str]:
    return [
        "multimon-ng", "-q", "-a", config.multimon_demodulator,
        "-t", "raw", "-",
    ]



class MultimonDecoder:
    def __init__(self, config: ReceiverConfig):
        self.config = config
        self._rtl: subprocess.Popen[bytes] | None = None
        self._multimon: subprocess.Popen[str] | None = None
        self._stderr_threads: list[threading.Thread] = []

    def pages(self) -> Iterator[RawPage]:
        while True:
            try:
                yield from self._run_once()
            except GeneratorExit:
                raise
            except Exception:
                _LOG.exception("Decoder failed")
            finally:
                self.stop()
            _LOG.warning("Restarting decoder in %.1f seconds", self.config.restart_delay_seconds)
            time.sleep(self.config.restart_delay_seconds)

    def _run_once(self) -> Iterator[RawPage]:
        rtl_cmd = build_rtl_command(self.config)
        multimon_cmd = build_multimon_command(self.config)
        _LOG.info("Starting receiver: %s -> %s", " ".join(rtl_cmd), " ".join(multimon_cmd))
        self._rtl = subprocess.Popen(  # noqa: S603
            rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
        )
        assert self._rtl.stderr is not None
        self._stderr_threads.append(
            threading.Thread(
                target=self._log_binary_stderr,
                args=(self._rtl.stderr, "rtl_fm"),
                daemon=True,
            )
        )
        self._stderr_threads[-1].start()
        assert self._rtl.stdout is not None
        self._multimon = subprocess.Popen(  # noqa: S603
            multimon_cmd,
            stdin=self._rtl.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        assert self._multimon.stderr is not None
        self._stderr_threads.append(
            threading.Thread(
                target=self._log_text_stderr,
                args=(self._multimon.stderr, "multimon-ng"),
                daemon=True,
            )
        )
        self._stderr_threads[-1].start()
        self._rtl.stdout.close()
        assert self._multimon.stdout is not None
        for line in self._multimon.stdout:
            page = parse_multimon_line(line)
            if page:
                yield page
        rc = self._multimon.wait()
        rtl_rc = self._rtl.poll()
        raise RuntimeError(f"multimon-ng exited rc={rc}, rtl_fm rc={rtl_rc}")


    @staticmethod
    def _log_binary_stderr(stream, process_name: str) -> None:
        for raw_line in iter(stream.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                _LOG.warning("%s: %s", process_name, line)

    @staticmethod
    def _log_text_stderr(stream, process_name: str) -> None:
        for line in stream:
            line = line.strip()
            if line:
                _LOG.warning("%s: %s", process_name, line)

    def stop(self) -> None:
        for process in (self._multimon, self._rtl):
            if process and process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
        for process in (self._multimon, self._rtl):
            if process:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
        self._multimon = None
        self._rtl = None
        self._stderr_threads.clear()


class DeflexDecoder:
    """Experimental external deFLEX adapter.

    deFLEX is not bundled. The configured process is started and its log file is tailed.
    Current FLEX logs do not contain the real capcode, so emitted RawPage.capcodes is empty.
    """

    def __init__(self, config: ReceiverConfig):
        self.config = config
        self._process: subprocess.Popen[str] | None = None

    def pages(self) -> Iterator[RawPage]:
        if not self.config.deflex_command:
            raise RuntimeError("receiver.deflex_command is empty")
        log_path = Path(self.config.deflex_log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(  # noqa: S603
            self.config.deflex_command, text=True, start_new_session=True
        )
        _LOG.warning(
            "deFLEX adapter enabled: current FLEX output has no usable capcode; "
            "capcode enrichment will be unavailable"
        )
        position = log_path.stat().st_size if log_path.exists() else 0
        try:
            while self._process.poll() is None:
                if not log_path.exists():
                    time.sleep(0.5)
                    continue
                with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    while self._process.poll() is None:
                        line = handle.readline()
                        if not line:
                            position = handle.tell()
                            time.sleep(0.25)
                            continue
                        position = handle.tell()
                        page = parse_deflex_log_line(line)
                        if page:
                            yield page
            raise RuntimeError(f"deFLEX exited rc={self._process.returncode}")
        finally:
            self.stop()

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                os.killpg(self._process.pid, signal.SIGTERM)
                self._process.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        self._process = None


def make_decoder(config: ReceiverConfig):
    if config.decoder == "deflex":
        return DeflexDecoder(config)
    return MultimonDecoder(config)
