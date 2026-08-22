# P2000 RTL-SDR MQTT

Standalone P2000 receiver for an RTL-SDR dongle. It is designed for a separate SDR host
(Raspberry Pi, Debian machine, etc.) and publishes normalized P2000 messages to MQTT.
Home Assistant is optional and connects only through its normal MQTT integration.

## Why this project

This project is a clean implementation inspired by `cyberjunky/addon-p2000_rtlsdr`, but it
is **not** a Home Assistant Supervisor add-on and does not require Supervisor.

Design goals:

- standalone Docker deployment;
- no Home Assistant REST API or access token;
- persistent MQTT connection with Last Will and reconnect;
- MQTT Event entities plus last-message sensors through Home Assistant discovery;
- robust FLEX parsing with malformed-line handling;
- aggregate metadata from **all** capcodes instead of letting the last capcode win;
- transactional capcode database updates from the public Bommel CSV source;
- duplicate suppression;
- decoder abstraction: `multimon-ng` by default, experimental external `deFLEX` adapter;
- testable modules instead of one large Python file.

## Data flow

```text
RTL-SDR
  -> rtl_fm
  -> multimon-ng (FLEX/FLEX_NEXT)
  -> parser
  -> capcode database enrichment
  -> global filters + dedupe
  -> named routes
  -> MQTT
       -> generic JSON topics
       -> Home Assistant MQTT discovery/events/sensors
```

No shell pipeline is used internally: `rtl_fm` and `multimon-ng` are separate child
processes and are monitored/restarted by the application.

## Quick start

```bash
cp config.example.yaml config.yaml
mkdir -p data
docker compose -f docker-compose.example.yml up -d --build
```

Set the MQTT broker address and credentials in `config.yaml` / environment variables.
The broker can run on the Home Assistant host or elsewhere.

### USB

The example maps `/dev/bus/usb`. If you prefer a narrower device mapping, identify your
RTL-SDR device on the host and change the compose file.

## MQTT topics

With `base_topic: p2000`:

```text
p2000/status                    retained: online/offline
p2000/messages                  every accepted message as JSON
p2000/stats                     retained JSON statistics
p2000/routes/<route>/event      non-retained HA/event payload
p2000/routes/<route>/last       retained normalized latest-message JSON
p2000/routes/<route>/state      retained short Home Assistant sensor state
p2000/routes/<route>/attributes retained compact Home Assistant attributes
```

A normalized message contains, among other fields:

```json
{
  "event_type": "message",
  "id": "...",
  "received_at": "2026-08-22T12:00:00+00:00",
  "source_time": "2026-08-22T14:00:00",
  "body": "P 1 ...",
  "summary": "P 1 ...",
  "priority": 1,
  "capcodes": ["001234567", "001234568"],
  "disciplines": ["Brandweer"],
  "regions": ["Noord-Holland Noord"],
  "locations": ["Alkmaar"],
  "remarks": ["..."],
  "decoder": "multimon"
}
```

## Home Assistant

MQTT discovery creates for every configured route:

- an MQTT **Event** entity for automations;
- a last-message MQTT sensor for dashboards and Logbook.

The sensor state is a normalized, truncated message (maximum 200 characters). The full
message is kept in the `message` attribute together with `time`, `priority`, `discipline`,
`region`, `location`, `remark`, `capcodes`, postal code, coordinates and message ID.
`force_update` is enabled so Home Assistant can record a newly received message even when
the short state happens to be identical to the previous one.

It also publishes receiver availability. Discovery payloads are retained and are sent
again when Home Assistant publishes its MQTT birth message.

Example Mushroom card using the new attributes:

```yaml
type: custom:mushroom-template-card
entity: sensor.p2000_rtl_sdr_p2000_alle_meldingen_laatste_melding
primary: >-
  {% set p = state_attr(entity, 'priority') %}
  P2000{% if p %} · P{{ p }}{% endif %}
secondary: >-
  {{ state_attr(entity, 'message') or states(entity) }}
icon: mdi:radio-tower
multiline_secondary: true
tap_action:
  action: more-info
```

## Filters

Filters use case-insensitive `fnmatch` patterns. Different configured include fields are
ANDed; multiple patterns within one field are ORed.

Example:

```yaml
include:
  disciplines: [Brandweer]
  regions: [Noord-Holland Noord]
  text: ["*ALKMAAR*"]
```

An exclude match rejects the route. Global ignore filters run before routes.

`ignore_capcodes_mode` can be:

- `any`: ignore when any capcode matches;
- `all`: ignore only when all capcodes match.

## Capcode database

The database is SQLite and is created automatically. When enabled, the updater downloads
the CSV published by `p2000.bommel.net`, validates it, imports it into a staging table and
then swaps the data in one transaction. Local tables (such as geocode cache) are not
replaced.

The updater stores the source hash, record count and update time. A fresh installation
updates before reception starts; later refreshes run periodically in a background thread. A
failed or suspicious update leaves the existing capcode table intact.

Manual update:

```bash
p2000-rtlsdr --config /config/config.yaml --update-db
```

## multimon-ng

The Docker image builds and pins multimon-ng 1.6.0. The default demodulator remains
`FLEX` for compatibility. `FLEX_NEXT` can be selected in `receiver.multimon_demodulator`
for testing the newer decoder.

## deFLEX

`deFLEX` is supported only as an **experimental external adapter**. Its code is not
vendored here. At the time this project was created, its live FLEX log format emitted
clean message bodies and confidence tiers but used `0` instead of the actual FLEX capcode.
That means P2000 capcode enrichment cannot work correctly with it yet.

When deFLEX exposes the real FLEX address/capcode, only the adapter/parser needs changing;
the rest of this project can stay unchanged.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

## Credits

Functionally inspired by:

- `cyberjunky/addon-p2000_rtlsdr` (MIT)
- `cyberjunky/RTL-SDR-P2000Receiver-HA`
- `pagermon/pagermon`
- `EliasOenal/multimon-ng`
- the public P2000 capcode database at `p2000.bommel.net`

No deFLEX source code is included.

## Home Assistant route history (0.1.4+)

Each route exposes two MQTT-discovered sensors:

- `... laatste melding`: short state with full P2000 metadata as attributes.
- `... recente meldingen`: persistent history of the latest 10 matching messages.

The last-message attributes include normalized `service`/`services`, `discipline`,
`capcodes`, `capcodes_text` and human-readable `capcode_details`. The recent-message
sensor has a `messages` attribute containing up to 10 newest-first entries with time,
message, priority, service, discipline, capcodes, location and region. Route history is
stored in SQLite and survives container restarts and capcode database refreshes.
