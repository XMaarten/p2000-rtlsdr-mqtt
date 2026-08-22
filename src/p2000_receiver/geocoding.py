from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from .config import GeocodingConfig
from .database import CapcodeDatabase
from .models import P2000Message

_LOG = logging.getLogger(__name__)


class Geocoder:
    def __init__(self, config: GeocodingConfig, db: CapcodeDatabase):
        self.config = config
        self.db = db

    def enrich(self, message: P2000Message) -> None:
        if not self.config.enabled or not message.postal_code:
            return
        if self.config.provider != "opencage" or not self.config.api_key:
            return
        query = f"{message.postal_code}, Netherlands"
        cached = self.db.geocode_get(query)
        if cached:
            message.latitude, message.longitude = cached
            return
        params = urllib.parse.urlencode({"q": query, "key": self.config.api_key, "limit": 1})
        url = f"https://api.opencagedata.com/geocode/v1/json?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "p2000-rtlsdr-mqtt/0.1"})
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=self.config.timeout_seconds
            ) as response:
                payload = json.load(response)
            results = payload.get("results") or []
            if not results:
                return
            geometry = results[0].get("geometry") or {}
            lat, lng = geometry.get("lat"), geometry.get("lng")
            if lat is None or lng is None:
                return
            message.latitude = float(lat)
            message.longitude = float(lng)
            self.db.geocode_put(query, message.latitude, message.longitude)
        except Exception as exc:  # external provider must never stop reception
            _LOG.warning("Geocoding failed for %s: %s", query, exc)
