import logging
from datetime import datetime

from src.calendar_client import create_or_update_gcal_event
from src.datamodels import GSheetIndexedRow, GSheetRow
from src.extract_flight_ai import get_flight_info
from src.sheets_client import fetch_flights_google_doc, update_row_with_formulas

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", force=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CUTOFF_DATE = datetime(2024, 9, 29)


def _has_required_fields(event_date: datetime | None, flight_no: str | None) -> bool:
    if event_date and flight_no:
        return True
    logger.debug(f"❌ skipping: missing values ({event_date!r}, {flight_no!r})")
    return False


def _is_before_or_on_cutoff(event_start: datetime) -> bool:
    if event_start <= CUTOFF_DATE:
        logger.debug(f"❌ skipping: before cutoff ({event_start} < {CUTOFF_DATE})")
        return True
    return False


def _has_gcal_event_id(gcal_event_id: str | None) -> bool:
    if gcal_event_id and str(gcal_event_id).strip():
        logger.debug(f"❌ skipping: gcal_event_id already set ({gcal_event_id!r})")
        return True
    return False


def _should_skip_row(row: GSheetRow) -> bool:
    if not _has_required_fields(row.date, row.flight_number):
        return True
    if _is_before_or_on_cutoff(row.date):
        return True
    if _has_gcal_event_id(row.gcal_event_id):
        return True
    return False


def main():
    rows = fetch_flights_google_doc()
    if not rows:
        logger.debug("❌ Failed to fetch flights from Google Sheets.")
        return
    header = rows[0]
    rows = rows[1:]

    rows_for_processing: list[GSheetIndexedRow] = []

    for i, row in enumerate(rows):
        sheet_row = GSheetRow.from_sheet_row(header=header, values=row)

        if _should_skip_row(sheet_row):
            continue

        sheet_row_number = i + 2  # row 1 = header, row 2 = first data row
        rows_for_processing.append(GSheetIndexedRow(row_number=sheet_row_number, row=sheet_row))

    if not rows_for_processing:
        logger.info("%d rows in google sheet, but no new flights to process.", len(rows))
        return

    logger.info(f"Processing {len(rows_for_processing)} flights")
    for indexed_row in rows_for_processing:
        print("-" * 100)
        row = indexed_row.row
        flight_info = get_flight_info(row.date, row.flight_number)
        if not flight_info:
            logger.error(f"❌ failed to get flight for: Date={row.date!r} Flight #={row.flight_number!r}")
            continue

        event_id = create_or_update_gcal_event(flight_info, row.gcal_event_id)
        new_row = GSheetRow(
            year=row.year,
            month=row.month,
            day=row.day,
            weekday="Fri",
            date=flight_info.departure_time,
            flight_number=row.flight_number,
            departure_airport=flight_info.departure_airport,
            arrival_airport=flight_info.arrival_airport,
            departure_time=flight_info.format_time_with_offset(flight_info.departure_time),
            arrival_time=flight_info.format_time_with_offset(flight_info.arrival_time),
            duration=flight_info.formatted_duration,
            origin=flight_info.departure_city,
            destination=flight_info.arrival_city,
            flighty=row.flighty,
            gcal_event_id=event_id,
            note=row.note,
            duration_s=flight_info.duration.total_seconds(),
            airline=flight_info.airline,
            aircraft=flight_info.aircraft,
            departure_country=flight_info.departure_country.name,
            arrival_country=flight_info.arrival_country.name,
            departure_terminal=flight_info.departure_terminal,
            arrival_terminal=flight_info.arrival_terminal,
        )
        update_row_with_formulas(indexed_row.row_number, header=header, new_row=new_row)


if __name__ == "__main__":
    main()
