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
- atomic capcode database updates from `XMaarten/p2000-capcodes`;
- separate replaceable reference data and persistent local runtime state;
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

### USB and receiver selection

The example maps `/dev/bus/usb`. If you prefer a narrower device mapping, identify your
RTL-SDR device on the host and change the compose file.

When multiple RTL-SDR dongles are connected, select the receiver by **serial number** rather
than device index. Device indexes can change after a reboot or USB reconnect. `rtl_fm` accepts
either an index or a serial number for `-d`. For example:

```yaml
receiver:
  device: "00000001"
```

Use `rtl_test` to list the connected receivers and their serial numbers.

### Docker health check

The image has a built-in health check that verifies that both `rtl_fm` and `multimon-ng` are
running. It uses `/proc` directly and does not depend on `pgrep`/`procps`, which are not
installed in the slim runtime image. A short automatic decoder restart will not normally mark
the container unhealthy because Docker requires multiple consecutive failures.

If your Compose file overrides the image health check, use:

```yaml
healthcheck:
  test: ["CMD", "p2000-rtlsdr", "--healthcheck"]
  interval: 90s
  timeout: 10s
  retries: 3
  start_period: 30s
```

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
  "stations": ["Alkmaar"],
  "callsigns": ["TS-3531"],
  "unit_type_names": ["Tankautospuit"],
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
`region`, `location`, `station`, `description`, `unit_type`, `callsign`, `capcodes`, postal code, coordinates and message ID.
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

Example routes:

```yaml
routes:
  - id: all
    name: P2000 alle meldingen
    icon: mdi:radio-tower

  - id: alkmaar
    name: P2000 Alkmaar
    icon: mdi:map-marker-alert
    include:
      text: ["*alkmaar*"]

  - id: grip
    name: P2000 GRIP
    icon: mdi:alert
    include:
      text: ["*grip*"]
```

An exclude match rejects the route. Global ignore filters run before routes.

`ignore_capcodes_mode` can be:

- `any`: ignore when any capcode matches;
- `all`: ignore only when all capcodes match.

## Capcode databases

The receiver deliberately uses **two separate SQLite databases**:

```text
/data/capcodes.sqlite3   read-only reference dataset
/data/runtime.sqlite3    local writable state
```

`capcodes.sqlite3` is downloaded from
[`XMaarten/p2000-capcodes`](https://github.com/XMaarten/p2000-capcodes) and is used
directly for capcode metadata and abbreviations. It contains the merged/enriched data from
the source project, including normalized service, station, unit type, callsign and unit
number fields.

`runtime.sqlite3` contains only local information owned by this receiver:

- route history;
- geocode cache;
- capcode download/check metadata.

This split means a database refresh never has to merge imported capcodes into a writable
runtime database. The new reference artifact is downloaded to a temporary file, checked
with SQLite `PRAGMA quick_check`, validated for required tables/columns and minimum record
count, and then installed with an **atomic file replacement**. A failed or incomplete
download leaves the previous `capcodes.sqlite3` untouched.

The receiver no longer supports the legacy Bommel CSV importer. `p2000-capcodes` is the
single source artifact; source collection and conflict resolution belong in that project.

Default configuration:

```yaml
database:
  capcodes_path: /data/capcodes.sqlite3
  runtime_path: /data/runtime.sqlite3
  auto_update: true
  update_interval_hours: 168
  source_url: https://raw.githubusercontent.com/XMaarten/p2000-capcodes/main/data/capcodes.sqlite3
  min_records: 5000
```

A fresh installation downloads the reference dataset before reception starts. Later checks
run periodically in a background thread. When the remote file is unchanged, only the local
`capcodes_checked_at` timestamp is updated.

Manual update:

```bash
p2000-rtlsdr --config /config/config.yaml --update-db
```

### Upgrade from the old combined database

Older releases used `/data/p2000.sqlite3` for both capcodes and local state. Version 0.2.0
uses the two files above instead. The old file can be removed once the new version is
running. No migration is required.

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
