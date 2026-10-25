"""Flight lookup sources, tried in order until one returns a result."""

from collections.abc import Callable
from datetime import datetime

from src.datamodels import FlightInfo
from src.fetchers import aviability
from src.fetchers import flighty

Fetcher = Callable[[datetime, str], FlightInfo | None]

FETCHERS: tuple[Fetcher, ...] = (flighty.get_flight_info, aviability.get_flight_info)


def get_flight_info(date: datetime, flight_number: str) -> FlightInfo | None:
    for fetch in FETCHERS:
        if info := fetch(date, flight_number):
            return info
    return None
