import logging
from collections import OrderedDict

from googleapiclient.discovery import build

from src.values import RANGE_NAME, SPREADSHEET_ID, credentials

logger = logging.getLogger(__name__)

_sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
_sheet = _sheets_service.spreadsheets()


def fetch_flights_google_doc() -> list[list[str]]:
    try:
        result = _sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        rows = result.get("values", [])
        return rows
    except Exception as e:
        logger.error(f"❌ failed to fetch flights from Google Sheets: {e}")
        return []


def update_row_with_formulas(row_index: int, new_row: OrderedDict) -> None:
    """Updates a row in Google Sheets, ensuring formulas are used for 'Date' and 'Weekday' columns."""
    row_values = list(new_row.values())

    date_formula = f"=DATE(A{row_index}, MONTH(B{row_index}&1), C{row_index})"
    weekday_formula = f'=TEXT(E{row_index}, "DDD")'

    date_column_index = list(new_row.keys()).index("Date")
    weekday_column_index = list(new_row.keys()).index("Weekday")

    row_values[date_column_index] = date_formula
    row_values[weekday_column_index] = weekday_formula
    row_index_range = f"raw!A{row_index}:ZZ{row_index}"

    _sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=row_index_range,
        valueInputOption="USER_ENTERED",
        body={"values": [row_values]},
    ).execute()

    logger.info(
        f"\033[92m✅ Row updated\033[0m | \033[94mRow:\033[0m {row_index_range} | \033[93mDate:\033[0m {new_row['Date']} | \033[96mFlight:\033[0m {new_row['Flight #']}"
    )
