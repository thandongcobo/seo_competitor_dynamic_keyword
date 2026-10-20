"""Run the opt-in recurring public-page monitor until stopped with Ctrl+C."""
from __future__ import annotations

import argparse
import logging
import time

from monitoring import store
from monitoring.scheduler import run_due


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tick-seconds", type=int, default=300,
                        help="How often to check whether a page is due (default: 300 seconds)")
    args = parser.parse_args()
    if args.tick_seconds < 30:
        parser.error("--tick-seconds must be at least 30")
    store.init_db()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Monitoring scheduler started; active pages are captured at their configured interval.")
    try:
        while True:
            for result in run_due():
                logging.info("Scheduled capture result: %s", result)
            time.sleep(args.tick_seconds)
    except KeyboardInterrupt:
        logging.info("Monitoring scheduler stopped.")


if __name__ == "__main__":
    main()
