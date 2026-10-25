import logging

from googleapiclient.discovery import build

from src.config import RANGE_NAME
from src.config import google_credentials
from src.datamodels import GSheetRow
from src.env import SPREADSHEET_ID

logger = logging.getLogger(__name__)

_sheet = None


def _get_sheet():
    global _sheet
    if _sheet is None:
        service = build("sheets", "v4", credentials=google_credentials, cache_discovery=False)
        _sheet = service.spreadsheets()
    return _sheet


def fetch_flights_google_doc() -> list[list[str]]:
    try:
        result = _get_sheet().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        rows = result.get("values", [])
        return rows
    except Exception as e:
        logger.error(f"❌ failed to fetch flights from Google Sheets: {e}")
        return []


def update_row_with_formulas(row_index: int, *, header: list[str], new_row: GSheetRow) -> None:
    """Updates a row in Google Sheets, ensuring formulas are used for 'Date' and 'Weekday' columns."""
    dumped = new_row.model_dump(by_alias=True)
    row_values = [dumped.get(col) for col in header]

    date_formula = f"=DATE(A{row_index}, MONTH(B{row_index}&1), C{row_index})"
    weekday_formula = f'=TEXT(E{row_index}, "DDD")'

    date_column_index = header.index("Date")
    weekday_column_index = header.index("Weekday")

    row_values[date_column_index] = date_formula
    row_values[weekday_column_index] = weekday_formula
    row_index_range = f"raw!A{row_index}:ZZ{row_index}"

    _get_sheet().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=row_index_range,
        valueInputOption="USER_ENTERED",
        body={"values": [row_values]},
    ).execute()

    logger.info(
        f"✅ Row updated | Row: {row_index_range} | Date: {dumped.get('Date')} | Flight: {dumped.get('Flight #')}"
    )
