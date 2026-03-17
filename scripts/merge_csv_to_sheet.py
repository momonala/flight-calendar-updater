"""One-off script to merge Flighty CSV export data into the Google Sheet `bk` tab.

The script:
- Reads the existing `raw` tab (your canonical structure).
- Copies its data into a new `bk` tab.
- Overwrites selected columns in `bk` using the Flighty CSV.

Merge key: Date + Flight # (string match).
"""

from __future__ import annotations

import logging
from pathlib import Path

import airportsdata
import pandas as pd
import pycountry
from googleapiclient.discovery import build

from src.sheets_client import fetch_flights_google_doc
from src.values import SPREADSHEET_ID, credentials

logger = logging.getLogger(__name__)

_sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
_sheet = _sheets_service.spreadsheets()

AIRPORTS = airportsdata.load("IATA")

# CSV column name -> Sheet column name
# Note:
# - We do NOT overwrite the sheet's human-friendly "Flight #" column (e.g. "LH 1929").
#   The Flighty CSV only has the numeric flight number, which we use for the merge key
#   but leave the displayed value from the sheet.
# - We focus on enriching terminals, actual times, aircraft, airline, and notes.
CSV_TO_SHEET_COLUMN_MAP: dict[str, str] = {
    "Dep Terminal": "departure_terminal",
    "Arr Terminal": "arrival_terminal",
    "Gate Departure (Actual)": "Departure Time",
    "Gate Arrival (Actual)": "Arrival Time",
    "Airline": "airline",
    "Aircraft Type Name": "aircraft",
    "Notes": "note",
}


def build_merge_key(
    df: pd.DataFrame,
    *,
    date_column: str,
    flight_column: str,
    key_column: str = "__merge_key",
) -> pd.DataFrame:
    """Return a copy of `df` with a normalized merge key column: YYYY-MM-DD|flight_number."""
    frame = df.copy()

    for name in (date_column, flight_column):
        if name not in frame.columns:
            msg = f"Required column '{name}' not found in dataframe"
            raise KeyError(msg)

    # Normalize date to canonical YYYY-MM-DD
    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce")
    canonical_date = parsed_dates.dt.strftime("%Y-%m-%d").fillna("")

    # Normalize flight to numeric portion only (e.g. "SK 936" -> "936")
    flight_str = frame[flight_column].astype(str).str.strip()
    numeric_flight = flight_str.str.extract(r"(\d+)", expand=False).fillna("")

    frame[key_column] = canonical_date + "|" + numeric_flight
    return frame


def apply_overwrite_merge(
    *,
    bk_df: pd.DataFrame,
    csv_df: pd.DataFrame,
    column_mapping: dict[str, str],
    key_column: str = "__merge_key",
) -> pd.DataFrame:
    """Merge `csv_df` into `bk_df` based on the merge key and column mapping.

    For each row where the key matches, mapped columns in `bk_df` are overwritten
    with non-empty values from `csv_df`. Rows present only in `csv_df` are ignored.
    """
    if key_column not in bk_df.columns or key_column not in csv_df.columns:
        msg = f"Both dataframes must contain key column '{key_column}'"
        raise KeyError(msg)

    csv_columns = list(column_mapping.keys())
    missing_csv_columns = [name for name in csv_columns if name not in csv_df.columns]
    if missing_csv_columns:
        msg = f"CSV dataframe missing required columns: {', '.join(missing_csv_columns)}"
        raise KeyError(msg)

    csv_subset = csv_df[[key_column] + csv_columns].copy()

    merged = bk_df.merge(
        csv_subset,
        on=key_column,
        how="left",
        suffixes=("", "_csv"),
    )

    logger.info(
        "Merging dataframes on key '%s' | bk rows: %d | csv rows: %d | csv unique keys: %d",
        key_column,
        len(bk_df),
        len(csv_df),
        csv_subset[key_column].nunique(),
    )

    updated_rows_per_column: dict[str, int] = {}

    for csv_col, sheet_col in column_mapping.items():
        csv_value_column = f"{csv_col}_csv"
        if csv_value_column in merged.columns:
            values = merged[csv_value_column]
        elif csv_col in merged.columns:
            # No name collision during merge; CSV column kept its original name.
            values = merged[csv_col]
        else:
            continue
        has_csv_value = values.notna() & (values.astype(str) != "")
        sheet_empty = merged[sheet_col].isna() | (merged[sheet_col].astype(str).str.strip() == "")
        mask = has_csv_value & sheet_empty
        updated_count = int(mask.sum())
        if updated_count:
            merged.loc[mask, sheet_col] = values[mask]
        # Drop only the synthetic _csv column if it exists; keep original columns intact.
        if csv_value_column in merged.columns:
            merged = merged.drop(columns=[csv_value_column])
        updated_rows_per_column[sheet_col] = updated_count

    logger.info("Column overwrite counts (sheet col → rows updated): %s", updated_rows_per_column)

    return merged


def load_csv_to_dataframe(csv_path: str | Path) -> pd.DataFrame:
    """Load the Flighty CSV export into a DataFrame."""
    path = Path(csv_path)
    if not path.exists():
        msg = f"CSV file not found: {path}"
        raise FileNotFoundError(msg)
    return pd.read_csv(path)


def load_raw_tab_as_dataframe() -> pd.DataFrame:
    """Load the `raw` tab from Google Sheets into a DataFrame."""
    rows = fetch_flights_google_doc()
    if not rows:
        msg = "No rows returned from Google Sheets `raw` tab"
        raise ValueError(msg)

    header = rows[0]
    data_rows = rows[1:]
    normalized_rows: list[list[str | None]] = []
    for row in data_rows:
        normalized_row = [row[i] if i < len(row) else None for i in range(len(header))]
        normalized_rows.append(normalized_row)

    frame = pd.DataFrame(normalized_rows, columns=header)
    return frame


def dataframe_to_values(df: pd.DataFrame) -> list[list[str | None]]:
    """Convert a DataFrame to a Sheets-compatible list-of-lists with header."""
    filled = df.where(pd.notna(df), None)
    values: list[list[str | None]] = [list(filled.columns)]
    values.extend([list(row) for row in filled.itertuples(index=False, name=None)])
    return values


def _ensure_sheet_exists(title: str) -> None:
    """Ensure a sheet with the given title exists in the spreadsheet."""
    spreadsheet = _sheet.get(spreadsheetId=SPREADSHEET_ID).execute()
    existing_titles = {s["properties"]["title"] for s in spreadsheet.get("sheets", [])}
    if title in existing_titles:
        return

    _sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()


def write_bk_tab(values: list[list[str | None]]) -> None:
    """Write the given values (including header) to the `bk` tab."""
    _ensure_sheet_exists("bk")

    _sheet.values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range="bk!A:ZZ",
    ).execute()

    _sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="bk!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    logger.info("✅ Wrote %d data rows to `bk` tab", len(values) - 1)


def _enrich_duration_fields(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Fill missing Duration and duration_s values based on Departure/Arrival Time."""
    frame = df.copy()
    parsed_departure = pd.to_datetime(frame["Departure Time"], errors="coerce")
    parsed_arrival = pd.to_datetime(frame["Arrival Time"], errors="coerce")

    missing_duration = frame["Duration"].isna() | (frame["Duration"].astype(str).str.strip() == "")
    missing_duration_s = frame["duration_s"].isna() | (frame["duration_s"].astype(str).str.strip() == "")
    can_compute = parsed_departure.notna() & parsed_arrival.notna()

    mask = missing_duration & can_compute
    delta = parsed_arrival[mask] - parsed_departure[mask]
    # Handle overnight flights by normalizing negative durations to +24h.
    negative = delta.dt.total_seconds() < 0
    delta = delta.mask(negative, delta + pd.Timedelta(days=1))
    total_minutes = (delta.dt.total_seconds() // 60).astype(int)

    duration_filled = int(mask.sum())
    if duration_filled:
        hours = (total_minutes // 60).astype(int)
        minutes = (total_minutes % 60).astype(int)
        frame.loc[mask, "Duration"] = hours.astype(str).str.zfill(2) + ":" + minutes.astype(str).str.zfill(2)

    # Only fill duration_s where currently empty and we have a computed duration.
    mask_duration_s = missing_duration_s & can_compute
    duration_s_filled = int(mask_duration_s.sum())
    if duration_s_filled:
        seconds = (total_minutes * 60).astype(int)
        frame.loc[mask_duration_s, "duration_s"] = seconds

    return frame, duration_filled, duration_s_filled


def _lookup_country_name(iata: str) -> str | None:
    """Return the country name for a given IATA airport code, if known."""
    if not iata:
        return None
    code = str(iata).strip().upper()
    if not code or code not in AIRPORTS:
        return None
    country_code = AIRPORTS[code].get("country")
    if not country_code:
        return None
    country = pycountry.countries.get(alpha_2=str(country_code).upper())
    if country is None:
        return None
    return country.name


def _enrich_country_fields(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Fill missing departure_country and arrival_country based on airport IATA codes."""
    frame = df.copy()

    dep_country_missing = frame["departure_country"].isna() | (
        frame["departure_country"].astype(str).str.strip() == ""
    )
    arr_country_missing = frame["arrival_country"].isna() | (
        frame["arrival_country"].astype(str).str.strip() == ""
    )

    dep_filled = 0
    arr_filled = 0

    for idx in frame.index:
        if dep_country_missing.at[idx]:
            dep_airport = frame.at[idx, "Departure Airport"]
            name = _lookup_country_name(dep_airport)
            if name:
                frame.at[idx, "departure_country"] = name
                dep_filled += 1

        if arr_country_missing.at[idx]:
            arr_airport = frame.at[idx, "Arrival Airport"]
            name = _lookup_country_name(arr_airport)
            if name:
                frame.at[idx, "arrival_country"] = name
                arr_filled += 1

    return frame, dep_filled, arr_filled


def main(csv_path: str = "data/FlightyExport-2026-01-20.csv") -> None:
    """Run the CSV → bk merge pipeline."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    logger.info("Loading CSV from %s", csv_path)
    csv_df = load_csv_to_dataframe(csv_path)
    logger.info("Loaded CSV: %d rows (including header handled by pandas)", len(csv_df))

    logger.info("Loading `raw` tab from Google Sheets")
    raw_df = load_raw_tab_as_dataframe()
    logger.info("Loaded `raw` tab: %d data rows", len(raw_df))

    # Copy `raw` into bk and build merge keys (Date + Flight # / Flight)
    bk_df = raw_df.copy()
    bk_df = build_merge_key(
        bk_df,
        date_column="Date",
        flight_column="Flight #",
    )
    csv_df = build_merge_key(
        csv_df,
        date_column="Date",
        flight_column="Flight",
    )

    logger.info(
        "Built merge keys | bk unique keys: %d | csv unique keys: %d",
        bk_df["__merge_key"].nunique(),
        csv_df["__merge_key"].nunique(),
    )

    logger.info("Sample bk keys: %s", bk_df["__merge_key"].dropna().head().tolist())
    logger.info("Sample csv keys: %s", csv_df["__merge_key"].dropna().head().tolist())

    merged_bk = apply_overwrite_merge(
        bk_df=bk_df,
        csv_df=csv_df,
        column_mapping=CSV_TO_SHEET_COLUMN_MAP,
    )

    # Enrich duration and country fields where still missing.
    merged_bk, duration_filled, duration_s_filled = _enrich_duration_fields(merged_bk)
    merged_bk, dep_country_filled, arr_country_filled = _enrich_country_fields(merged_bk)

    # Preserve the original `raw` header order.
    header_columns = list(raw_df.columns)
    final_bk_df = merged_bk[header_columns]
    logger.info("Final `bk` dataframe shape: rows=%d, cols=%d", *final_bk_df.shape)
    logger.info(
        "Enriched fields | Duration filled: %d | duration_s filled: %d | "
        "departure_country filled: %d | arrival_country filled: %d",
        duration_filled,
        duration_s_filled,
        dep_country_filled,
        arr_country_filled,
    )

    values = dataframe_to_values(final_bk_df)
    write_bk_tab(values)


if __name__ == "__main__":
    main()
