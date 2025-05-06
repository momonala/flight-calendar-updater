import logging
import time

import schedule

from main import main

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    schedule.every().day.at("00:00").do(main)
    logger.info("Init scheduler!")
    while True:
        schedule.run_pending()
        time.sleep(1)
