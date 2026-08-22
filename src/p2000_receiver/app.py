from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timezone

from .config import AppConfig
from .database import CapcodeDatabase
from .decoders import make_decoder
from .dedupe import DedupeCache
from .enrichment import enrich
from .filters import globally_ignored, route_matches
from .geocoding import Geocoder
from .home_assistant import history_entry
from .mqtt import MqttPublisher

_LOG = logging.getLogger(__name__)


class App:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db = CapcodeDatabase(config.database.path)
        self.decoder = make_decoder(config.receiver)
        self.dedupe = DedupeCache(config.dedupe.window_seconds, config.dedupe.max_entries)
        self.geocoder = Geocoder(config.geocoding, self.db)
        self.mqtt = MqttPublisher(config.mqtt, config.routes)
        self.mqtt.set_discovery_callback(self.mqtt.publish_discovery)
        self.running = True
        self._stop_event = threading.Event()
        self._maintenance: threading.Thread | None = None
        self.stats = {
            "received": 0,
            "accepted": 0,
            "duplicates": 0,
            "ignored": 0,
            "published_routes": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    def _signal(self, signum, frame) -> None:
        _LOG.info("Stopping on signal %s", signum)
        self.running = False
        self._stop_event.set()
        self.decoder.stop()

    def prepare_database(self, force: bool = False) -> bool:
        cfg = self.config.database
        if not cfg.auto_update and not force:
            return True
        if not force and not self.db.needs_update(cfg.update_interval_hours):
            return True
        try:
            self.db.update_from_url(cfg.source_url, min_records=cfg.min_records)
            return True
        except Exception:
            _LOG.exception("Capcode database update failed; keeping existing database")
            return False

    def _database_maintenance(self) -> None:
        cfg = self.config.database
        # Use a separate SQLite connection in this thread. SQLite commits become visible
        # to the main read connection without sharing a connection across threads.
        db = CapcodeDatabase(cfg.path)
        check_every = max(300, min(3600, int(cfg.update_interval_hours * 3600 / 4)))
        try:
            while not self._stop_event.wait(check_every):
                if not db.needs_update(cfg.update_interval_hours):
                    continue
                try:
                    db.update_from_url(cfg.source_url, min_records=cfg.min_records)
                except Exception:
                    _LOG.exception("Periodic capcode database update failed")
        finally:
            db.close()

    def _start_database_maintenance(self) -> None:
        if not self.config.database.auto_update:
            return
        self._maintenance = threading.Thread(
            target=self._database_maintenance, name="capcode-updater", daemon=True
        )
        self._maintenance.start()

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._signal)
        signal.signal(signal.SIGTERM, self._signal)
        # On a fresh installation, fetch synchronously so the first message can already
        # be enriched. With an existing DB, stale-data refreshes happen in the background.
        if self.config.database.auto_update and self.db.record_count() == 0:
            self.prepare_database(force=True)
        self._start_database_maintenance()
        self.mqtt.connect()
        self.mqtt.publish_discovery()
        for route in self.config.routes:
            self.mqtt.publish_route_history(route, self.db.history_get(route.id, 10))
        self.mqtt.publish_stats(self.stats)
        try:
            for page in self.decoder.pages():
                if not self.running:
                    break
                self.stats["received"] += 1
                message = enrich(page, self.db)
                self.geocoder.enrich(message)
                if globally_ignored(message, self.config.global_filters):
                    self.stats["ignored"] += 1
                    continue
                if self.dedupe.is_duplicate(message):
                    self.stats["duplicates"] += 1
                    continue
                self.stats["accepted"] += 1
                self.mqtt.publish_message(message)
                matched = 0
                for route in self.config.routes:
                    if route_matches(message, route):
                        history = self.db.history_add(
                            route.id,
                            message.message_id,
                            message.received_at.isoformat(),
                            history_entry(message),
                            limit=10,
                        )
                        self.mqtt.publish_route(route, message, history)
                        matched += 1
                self.stats["published_routes"] += matched
                self.stats["last_message_at"] = datetime.now(timezone.utc).isoformat()
                self.mqtt.publish_stats(self.stats)
                _LOG.info(
                    "P2000 %s prio=%s capcodes=%s routes=%s %s",
                    message.message_id,
                    message.priority,
                    ",".join(message.capcodes) or "-",
                    matched,
                    message.summary,
                )
        finally:
            self.running = False
            self._stop_event.set()
            self.decoder.stop()
            self.mqtt.close()
            if self._maintenance and self._maintenance.is_alive():
                self._maintenance.join(timeout=2)
            self.db.close()
