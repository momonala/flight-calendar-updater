import logging
import time

import schedule

from src.config import SCHEDULER_TRIGGER_TIME
from src.main import main

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    schedule.every().day.at(SCHEDULER_TRIGGER_TIME).do(main)
    logger.info("Init scheduler!")
    while True:
        schedule.run_pending()
        time.sleep(1)
