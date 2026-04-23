"""Pydantic models for flight extraction."""

from datetime import datetime, timedelta

import airportsdata
import aniso8601
import pycountry
import pytz
from pydantic import BaseModel, Field, field_validator, model_validator

airports = airportsdata.load("IATA")


def _localize_datetime(iso_str: str, airport_iata: str) -> datetime:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    tz = pytz.timezone(airports[airport_iata]["tz"])
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return tz.localize(dt)


class FlightInfo(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    flight_number: str
    operating_flight_number: str = ""
    airline: str
    operating_airline: str = ""
    departure_airport: str
    arrival_airport: str
    departure_city: str
    arrival_city: str
    departure_country: pycountry.db.Country
    arrival_country: pycountry.db.Country
    departure_terminal: str | None = None
    arrival_terminal: str | None = None
    departure_time: datetime
    arrival_time: datetime
    duration: timedelta
    aircraft: str | None = None
    route_distance_km: float | None = None

    @field_validator("departure_country", "arrival_country", mode="before")
    @classmethod
    def _country(cls, v: str | pycountry.db.Country) -> pycountry.db.Country:
        if hasattr(v, "alpha_2"):
            return v
        c = pycountry.countries.get(alpha_2=str(v).upper())
        if c is None:
            raise ValueError(f"Unknown country: {v}")
        return c

    @field_validator("departure_terminal", "arrival_terminal", mode="before")
    @classmethod
    def _terminal(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        s = str(v).strip()
        if s.isdigit() or (len(s) == 1 and s.isalpha()):
            return f"Terminal {s}"
        return s

    @model_validator(mode="before")
    @classmethod
    def _parse_times(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if isinstance(out.get("departure_time"), str) and out.get("departure_airport"):
            out["departure_time"] = _localize_datetime(out["departure_time"], out["departure_airport"])
        if isinstance(out.get("arrival_time"), str) and out.get("arrival_airport"):
            out["arrival_time"] = _localize_datetime(out["arrival_time"], out["arrival_airport"])
        if isinstance(out.get("duration"), str) and out.get("duration"):
            out["duration"] = aniso8601.parse_duration(out["duration"])
        return out

    @staticmethod
    def format_datetime_with_offset(dt: datetime) -> str:
        offset = dt.utcoffset()
        if offset is None:
            return dt.strftime("%Y-%m-%d %H:%M")
        h = int(offset.total_seconds() // 3600)
        tz_name = dt.tzinfo.tzname(dt) if dt.tzinfo else ""
        return f"{dt.strftime('%Y-%m-%d %H:%M')} ({tz_name} {h:+.0f})"

    @staticmethod
    def format_time_with_offset(dt: datetime) -> str:
        offset = dt.utcoffset()
        if offset is None:
            return dt.strftime("%H:%M")
        h = int(offset.total_seconds() // 3600)
        tz_name = dt.tzinfo.tzname(dt) if dt.tzinfo else ""
        return f"{dt.strftime('%H:%M')} ({tz_name} {h:+.0f})"

    @property
    def formatted_duration(self) -> str:
        total = int(self.duration.total_seconds() // 60)
        h, m = divmod(total, 60)
        return f"{h:02}:{m:02}"

    def as_gcal_description(self) -> str:
        dep = self.departure_country
        arr = self.arrival_country
        dep_suffix = f" ({self.departure_terminal})" if self.departure_terminal else ""
        arr_suffix = f" ({self.arrival_terminal})" if self.arrival_terminal else ""
        return (
            f"{dep.flag} Flight Details {arr.flag}\n"
            f"✈️ Airline: {self.airline} ({self.flight_number})\n"
            f"⏱️ Duration: {self.formatted_duration}\n"
            f"🛩️ Aircraft: {self.aircraft or 'TBD'}\n"
            f"📍 Departure:\n"
            f"\t{dep.flag} {self.departure_airport}, {self.departure_city} {dep.name}{dep_suffix}\n"
            f"\t🛫 {self.format_datetime_with_offset(self.departure_time)}\n"
            f"📍 Arrival:\n"
            f"\t{arr.flag} {self.arrival_airport}, {self.arrival_city} {arr.name}{arr_suffix}\n"
            f"\t🛬 {self.format_datetime_with_offset(self.arrival_time)}\n"
        )


class GSheetRow(BaseModel):
    """A single row from the Google Sheet, keyed by the sheet's column names."""

    model_config = {"populate_by_name": True}  # accept populate be field name (off in Pydantic v2)

    year: str | None = Field(default=None, alias="Year")
    month: str | None = Field(default=None, alias="Month")
    day: str | None = Field(default=None, alias="Day")
    weekday: str | None = Field(default=None, alias="Weekday")
    date: datetime | None = Field(default=None, alias="Date")
    flight_number: str | None = Field(default=None, alias="Flight #")
    departure_airport: str | None = Field(default=None, alias="Departure Airport")
    arrival_airport: str | None = Field(default=None, alias="Arrival Airport")
    departure_time: str | None = Field(default=None, alias="Departure Time")
    arrival_time: str | None = Field(default=None, alias="Arrival Time")
    duration: str | None = Field(default=None, alias="Duration")
    origin: str | None = Field(default=None, alias="Origin")
    destination: str | None = Field(default=None, alias="Destination")
    flighty: str | None = Field(default=None, alias="Flighty")
    gcal_event_id: str | None = Field(default=None, alias="gcal_event_id")
    note: str | None = Field(default=None, alias="note")
    duration_s: float | None = Field(default=None, alias="duration_s")
    airline: str | None = Field(default=None, alias="airline")
    aircraft: str | None = Field(default=None, alias="aircraft")
    departure_country: str | None = Field(default=None, alias="departure_country")
    arrival_country: str | None = Field(default=None, alias="arrival_country")
    departure_terminal: str | None = Field(default=None, alias="departure_terminal")
    arrival_terminal: str | None = Field(default=None, alias="arrival_terminal")

    @field_validator("date", mode="before")
    @classmethod
    def _parse_sheet_date(cls, v: object) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        s = str(v).strip()
        if not s:
            return None
        # Expected sheet format: "Nov 30, 1996"
        try:
            return datetime.strptime(s, "%b %d, %Y")
        except ValueError as exc:
            raise ValueError(f"Unsupported date format: {s!r}") from exc

    @classmethod
    def from_sheet_row(cls, *, header: list[str], values: list[str | None]) -> "GSheetRow":
        padded = [values[i] if i < len(values) else None for i in range(len(header))]
        return cls.model_validate(dict(zip(header, padded, strict=True)))


class GSheetIndexedRow(BaseModel):
    """A Google Sheet row plus its 1-based row number (metadata, not a sheet column)."""

    row_number: int
    row: GSheetRow
