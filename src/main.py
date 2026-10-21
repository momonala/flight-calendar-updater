import logging
import sys
from datetime import datetime
from typing import Annotated

import typer

from src.calendar_client import create_or_update_gcal_event
from src.datamodels import GSheetIndexedRow, GSheetRow
from src.fetchers import get_flight_info
from src.fetchers.flighty import check_credentials, clear_cache
from src.sheets_client import fetch_flights_google_doc, update_row_with_formulas

_LEVEL_COLORS = {logging.WARNING: "\033[33m", logging.ERROR: "\033[31m", logging.CRITICAL: "\033[31m"}


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        color = _LEVEL_COLORS.get(record.levelno)
        return f"{color}{line}\033[0m" if color else line


_handler = logging.StreamHandler()
_log_format = "%(levelname)s: %(message)s"
_handler.setFormatter(_ColorFormatter(_log_format) if sys.stderr.isatty() else logging.Formatter(_log_format))
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
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


def _is_already_filled(row: GSheetRow) -> bool:
    if row.departure_time or row.arrival_time:
        logger.debug(f"❌ skipping: already filled ({row.flight_number!r} on {row.date})")
        return True
    return False


def _is_in_the_past(event_start: datetime) -> bool:
    if event_start < datetime.now():
        logger.debug(f"❌ skipping: in the past ({event_start} < {datetime.now()})")
        return True
    return False


def _should_skip_row(row: GSheetRow, update_all: bool) -> bool:
    if not _has_required_fields(row.date, row.flight_number):
        return True
    if _is_before_or_on_cutoff(row.date):
        return True
    if _is_in_the_past(row.date):
        return True
    if not update_all and _is_already_filled(row):
        return True
    return False


def _get_rows_for_processing(rows: list, update_all: bool) -> list[GSheetIndexedRow]:
    header, data_rows = rows[0], rows[1:]
    result = []
    for i, row in enumerate(data_rows):
        sheet_row = GSheetRow.from_sheet_row(header=header, values=row)
        if not _should_skip_row(sheet_row, update_all):
            result.append(GSheetIndexedRow(row_number=i + 2, row=sheet_row))
    return result


def _build_updated_row(row: GSheetRow, flight_info, event_id: str) -> GSheetRow:
    return GSheetRow(
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


def _process_flight(indexed_row: GSheetIndexedRow, header: list) -> None:
    row = indexed_row.row
    flight_info = get_flight_info(row.date, row.flight_number)
    if not flight_info:
        logger.error("❌ failed to get flight for: Date=%r Flight #=%r", row.date, row.flight_number)
        return
    event_id = create_or_update_gcal_event(flight_info, row.gcal_event_id)
    new_row = _build_updated_row(row, flight_info, event_id)
    update_row_with_formulas(indexed_row.row_number, header=header, new_row=new_row)


app = typer.Typer(add_completion=False)


@app.command()
def main(
    update: Annotated[
        bool, typer.Option("--update", help="Re-fetch all future flights, not just unfilled rows")
    ] = False,
    clear_airline_cache: Annotated[
        bool, typer.Option("--clear-cache", help="Clear the cached Flighty airline table")
    ] = False,
):
    check_credentials()
    if clear_airline_cache:
        logger.info("--clear-cache flag set: clearing Flighty airline cache")
        clear_cache()

    rows = fetch_flights_google_doc()
    if not rows:
        logger.warning("❌ Failed to fetch flights from Google Sheets.")
        return

    rows_for_processing = _get_rows_for_processing(rows, update_all=update)
    if not rows_for_processing:
        logger.info("%d rows in google sheet, but no new flights to process.", len(rows) - 1)
        return

    header = rows[0]
    logger.info("Processing %d flights", len(rows_for_processing))
    for indexed_row in rows_for_processing:
        print("-" * 100)
        _process_flight(indexed_row, header)


if __name__ == "__main__":
    app()
