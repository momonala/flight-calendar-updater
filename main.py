import logging
from collections import OrderedDict
from datetime import datetime

import pandas as pd
from googleapiclient.discovery import build

from extract_flight import FlightInfo, get_flight_info
from values import CALENDAR_ID, RANGE_NAME, SPREADSHEET_ID, credentials

logging.basicConfig()
logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)


# Authenticate and build services
sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
calendar_service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
sheet = sheets_service.spreadsheets()
gcal_client = calendar_service.events()


def create_or_update_gcal_event(flight_info: FlightInfo, event_id: str | None):
    event_description = (
        f"✈️ {flight_info.departure_airport} → {flight_info.arrival_airport} {flight_info.flight_number}"
    )
    event = {
        "summary": event_description,
        "start": {
            "dateTime": flight_info.departure_time.isoformat(),
            "timeZone": flight_info.departure_time.tzinfo.zone,  # noqa
        },
        "end": {
            "dateTime": flight_info.arrival_time.isoformat(),
            "timeZone": flight_info.arrival_time.tzinfo.zone,  # noqa
        },
        "description": flight_info.as_gcal_description(),
    }

    if event_id:
        event = gcal_client.update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
        logger.info(f'📅 Updated event: {event_description} with ID {event["id"]}')

    else:
        event = gcal_client.insert(calendarId=CALENDAR_ID, body=event).execute()
        logger.info(f'📅 Created event: {event_description} with ID {event["id"]}')
    return event["id"]


def update_row_with_formulas(row_index: int, new_row: OrderedDict):
    """Updates a row in Google Sheets, ensuring formulas are used for 'Date' and 'Weekday' columns."""
    row_values = list(new_row.values())

    # Add formulas for 'Date' and Weekday
    date_formula = f"=DATE(A{row_index}, MONTH(B{row_index}&1), C{row_index})"
    weekday_formula = f'=TEXT(E{row_index}, "DDD")'  # Abbreviated weekday name, e.g., "Fri"

    # Replace 'Date' and 'Weekday' columns with formulas
    date_column_index = list(new_row.keys()).index("Date")
    weekday_column_index = list(new_row.keys()).index("Weekday")

    row_values[date_column_index] = date_formula
    row_values[weekday_column_index] = weekday_formula
    row_index_range = f"raw!A{row_index}:ZZ{row_index}"

    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=row_index_range,
        valueInputOption="USER_ENTERED",
        body={"values": [row_values]},
    ).execute()
    logger.info(f"✅ Row updated {row_index_range=} {new_row['Date']} {new_row['Flight #']}")


def main():
    # Read data from Google Sheets
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    rows = result.get("values", [])
    header = rows[0]

    for i, row in enumerate(rows):
        if i == 0:  # skip header
            continue

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
        new_row = OrderedDict(
            [
                ("Year", row["Year"]),
                ("Month", row["Month"]),
                ("Day", row["Day"]),
                ("Weekday", "Fri"),
                ("Date", "Feb 14,2025 "),
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
        update_row_with_formulas(i + 1, new_row)


if __name__ == "__main__":
    main()
