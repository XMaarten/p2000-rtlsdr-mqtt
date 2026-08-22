from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from . import __version__
from .config import MqttConfig, RouteConfig
from .home_assistant import history_attributes, sensor_attributes, sensor_state
from .models import P2000Message

_LOG = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, config: MqttConfig, routes: list[RouteConfig]):
        self.config = config
        self.routes = routes
        self.status_topic = f"{config.base_topic}/status"
        self._connected = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="p2000-rtlsdr")
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        if config.tls:
            self._client.tls_set()
        self._client.will_set(self.status_topic, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._discovery_callback: Callable[[], None] | None = None

    def set_discovery_callback(self, callback: Callable[[], None]) -> None:
        self._discovery_callback = callback

    def connect(self, timeout: float = 15) -> None:
        self._client.connect_async(
            self.config.host, self.config.port, keepalive=self.config.keepalive
        )
        self._client.loop_start()
        if not self._connected.wait(timeout):
            raise TimeoutError(f"MQTT connection timed out: {self.config.host}:{self.config.port}")

    def close(self) -> None:
        if self._connected.is_set():
            self.publish_raw(self.status_topic, "offline", retain=True, qos=1)
        self._client.disconnect()
        self._client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            _LOG.error("MQTT connection failed: %s", reason_code)
            return
        self._connected.set()
        _LOG.info("Connected to MQTT %s:%s", self.config.host, self.config.port)
        self.publish_raw(self.status_topic, "online", retain=True, qos=1)
        if self.config.home_assistant_discovery:
            client.subscribe(f"{self.config.discovery_prefix}/status", qos=0)
        if self._discovery_callback:
            self._discovery_callback()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self._connected.clear()
        if reason_code != 0:
            _LOG.warning("Unexpected MQTT disconnect: %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        if (
            message.topic == f"{self.config.discovery_prefix}/status"
            and message.payload.decode(errors="ignore").strip().lower() == "online"
            and self._discovery_callback
        ):
            self._discovery_callback()

    def publish_raw(self, topic: str, payload: str, retain: bool = False, qos: int | None = None):
        info = self._client.publish(
            topic, payload, qos=self.config.qos if qos is None else qos, retain=retain
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            _LOG.warning("MQTT publish failed rc=%s topic=%s", info.rc, topic)
        return info

    def publish_json(self, topic: str, payload: dict[str, Any], retain: bool = False) -> None:
        self.publish_raw(
            topic, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), retain
        )

    def publish_message(self, message: P2000Message) -> None:
        self.publish_json(f"{self.config.base_topic}/messages", message.to_dict(), retain=False)

    def publish_route(
        self, route: RouteConfig, message: P2000Message, history: list[dict[str, Any]]
    ) -> None:
        payload = message.to_dict()
        base = f"{self.config.base_topic}/routes/{route.id}"
        self.publish_json(f"{base}/event", payload, retain=False)
        # Keep the normalized full message for generic MQTT consumers.
        self.publish_json(f"{base}/last", payload, retain=True)
        # Home Assistant gets a short state plus a human-readable attribute set.
        self.publish_raw(f"{base}/state", sensor_state(message), retain=True)
        self.publish_json(f"{base}/attributes", sensor_attributes(route, message), retain=True)
        self.publish_route_history(route, history)

    def publish_route_history(self, route: RouteConfig, history: list[dict[str, Any]]) -> None:
        base = f"{self.config.base_topic}/routes/{route.id}"
        self.publish_json(f"{base}/history", history_attributes(route, history), retain=True)

    def publish_stats(self, stats: dict[str, Any]) -> None:
        self.publish_json(f"{self.config.base_topic}/stats", stats, retain=True)

    def publish_discovery(self) -> None:
        if not self.config.home_assistant_discovery:
            return
        device = {
            "identifiers": ["p2000_rtlsdr_mqtt"],
            "name": "P2000 RTL-SDR",
            "manufacturer": "XMaarten",
            "model": "P2000 RTL-SDR MQTT receiver",
            "sw_version": __version__,
        }
        origin = {
            "name": "p2000-rtlsdr-mqtt",
            "sw_version": __version__,
            "support_url": "https://github.com/XMaarten/p2000-rtlsdr-mqtt",
        }
        for route in self.routes:
            base = f"{self.config.base_topic}/routes/{route.id}"
            event_config = {
                "name": route.name,
                "unique_id": f"p2000_{route.id}_event",
                "state_topic": f"{base}/event",
                "event_types": ["message"],
                "availability_topic": self.status_topic,
                "icon": route.icon,
                "device": device,
                "origin": origin,
                "qos": self.config.qos,
            }
            sensor_config = {
                "name": f"{route.name} laatste melding",
                "unique_id": f"p2000_{route.id}_last",
                "state_topic": f"{base}/state",
                "json_attributes_topic": f"{base}/attributes",
                "availability_topic": self.status_topic,
                "icon": route.icon,
                "device": device,
                "origin": origin,
                "qos": self.config.qos,
                "force_update": True,
            }
            history_config = {
                "name": f"{route.name} recente meldingen",
                "unique_id": f"p2000_{route.id}_history",
                "state_topic": f"{base}/history",
                "value_template": "{{ value_json.count }}",
                "json_attributes_topic": f"{base}/history",
                "availability_topic": self.status_topic,
                "icon": route.icon,
                "device": device,
                "origin": origin,
                "qos": self.config.qos,
            }
            prefix = self.config.discovery_prefix
            self.publish_json(f"{prefix}/event/p2000/{route.id}/config", event_config, retain=True)
            self.publish_json(
                f"{prefix}/sensor/p2000/{route.id}_last/config", sensor_config, retain=True
            )
            self.publish_json(
                f"{prefix}/sensor/p2000/{route.id}_history/config",
                history_config,
                retain=True,
            )

        status_config = {
            "name": "P2000 receiver",
            "unique_id": "p2000_receiver_status",
            "state_topic": self.status_topic,
            "payload_on": "online",
            "payload_off": "offline",
            "device_class": "connectivity",
            "device": device,
            "origin": origin,
        }
        self.publish_json(
            f"{self.config.discovery_prefix}/binary_sensor/p2000/status/config",
            status_config,
            retain=True,
        )
