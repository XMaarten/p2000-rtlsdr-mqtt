from __future__ import annotations

import argparse
import logging
import os
import sys

from .app import App
from .config import load_config
from .health import receiver_is_healthy


def main() -> None:
    parser = argparse.ArgumentParser(description="P2000 RTL-SDR MQTT receiver")
    parser.add_argument("--config", default=os.environ.get("P2000_CONFIG", "/config/config.yaml"))
    parser.add_argument("--update-db", action="store_true", help="update capcode DB and exit")
    parser.add_argument(
        "--healthcheck", action="store_true", help="check whether receiver processes are running"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.healthcheck:
        sys.exit(0 if receiver_is_healthy(config.receiver) else 1)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = App(config)
    if args.update_db:
        try:
            app.prepare_database(force=True)
        finally:
            app.db.close()
        return
    try:
        app.run()
    except KeyboardInterrupt:
        return
    except Exception:
        logging.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
