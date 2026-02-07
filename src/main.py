import logging
from collections import OrderedDict
from datetime import datetime

import pandas as pd

from src.calendar_client import create_or_update_gcal_event
from src.extract_flight_ai import get_flight_info
from src.sheets_client import fetch_flights_google_doc, update_row_with_formulas

logger = logging.getLogger(__name__)


def main():
    rows = fetch_flights_google_doc()
    header = rows[0]
    rows = rows[1:]

    for i, row in enumerate(rows):
        row = [row[x] if x < len(row) else None for x in range(len(header))]
        row = OrderedDict(zip(header, row))

        event_date = row["Date"]
        event_start = pd.to_datetime(event_date)
        flight_no = row["Flight #"]

        if not all([event_date, flight_no]):
            logger.debug(f"❌ skipping: no values found for {event_date=} {flight_no=}")
            continue
        if event_start < datetime.now():
            logger.debug(f"❌ skipping: flight is in the past {event_date=} {flight_no=}")
            continue

        print("-" * 100)
        flight_info = get_flight_info(event_start, flight_no)
        if not flight_info:
            logger.error(f"❌ failed to get flight for: {event_date=} {flight_no=}")
            continue

        event_id = create_or_update_gcal_event(flight_info, row["gcal_event_id"])
        date = flight_info.departure_time.strftime("%Y-%m-%d")
        new_row = OrderedDict(
            [
                ("Year", row["Year"]),
                ("Month", row["Month"]),
                ("Day", row["Day"]),
                ("Weekday", "Fri"),
                ("Date", date),
                ("Flight #", row["Flight #"]),
                ("Departure Airport", flight_info.departure_airport),
                ("Arrival Airport", flight_info.arrival_airport),
                (
                    "Departure Time",
                    flight_info.format_time_with_offset(flight_info.departure_time),
                ),
                (
                    "Arrival Time",
                    flight_info.format_time_with_offset(flight_info.arrival_time),
                ),
                ("Duration", flight_info.formatted_duration),
                ("Origin", flight_info.departure_city),
                ("Destination", flight_info.arrival_city),
                ("Flighty", row["Flighty"]),
                ("gcal_event_id", event_id),
                ("note", row["note"]),
                ("duration_s", flight_info.duration.total_seconds()),
                ("airline", flight_info.airline),
                ("aircraft", flight_info.aircraft),
                ("departure_country", flight_info.departure_country.name),
                ("arrival_country", flight_info.arrival_country.name),
                ("departure_terminal", flight_info.departure_terminal),
                ("arrival_terminal", flight_info.arrival_terminal),
            ]
        )
        assert list(new_row.keys()) == header
        sheet_row = i + 2  # row 1 = header, row 2 = first data row
        update_row_with_formulas(sheet_row, new_row)


if __name__ == "__main__":
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    main()
