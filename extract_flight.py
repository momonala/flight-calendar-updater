import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pprint import pprint as print

import airportsdata
import country_converter as coco
import pycountry
import pytz
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

logging.basicConfig()
logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)


airports = airportsdata.load("IATA")
cc = coco.CountryConverter()


@dataclass
class FlightInfo:
    flight_number: str
    airline: str
    departure_airport: str
    arrival_airport: str
    departure_country: pycountry.db.Country
    arrival_country: pycountry.db.Country
    departure_city: str
    arrival_city: str
    departure_terminal: str
    arrival_terminal: str
    departure_time: datetime
    arrival_time: datetime
    duration: timedelta
    aircraft: str

    @staticmethod
    def format_datetime_with_offset(dt: datetime) -> str:
        offset = dt.utcoffset()
        offset_hours = offset.total_seconds() // 3600
        tz_name = dt.tzinfo.tzname(dt)
        return f"{dt.strftime('%Y-%m-%d %H:%M')} ({tz_name} {offset_hours:+.0f})"

    @staticmethod
    def format_time_with_offset(dt: datetime) -> str:
        offset = dt.utcoffset()
        offset_hours = offset.total_seconds() // 3600
        tz_name = dt.tzinfo.tzname(dt)
        return f"{dt.strftime('%H:%M')} ({tz_name} {offset_hours:+.0f})"

    @property
    def formatted_duration(self) -> str:
        total_minutes = int(self.duration.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02}:{minutes:02}"

    # fmt: off
    def as_gcal_description(self) -> str:
        return (
            f"{self.departure_country.flag} Flight Details {self.arrival_country.flag}\n"
            f"✈️ Airline: {self.airline} ({self.flight_number})\n"
            f"⏱️ Duration: {self.formatted_duration}\n"
            f"🛩️ Aircraft: {self.aircraft or 'TBD'}\n"
            f"📍 Departure:\n"
            f"\t{self.departure_country.flag} {self.departure_airport}, {self.departure_city} {self.departure_country.name} ({self.departure_terminal})\n"
            f"\t🛫 {self.format_datetime_with_offset(self.departure_time)}\n"
            f"📍 Arrival:\n"
            f"\t{self.arrival_country.flag} {self.arrival_airport}, {self.arrival_city} {self.arrival_country.name} ({self.arrival_terminal})\n"
            f"\t🛬 {self.format_datetime_with_offset(self.arrival_time)}\n"
        )


# fmt: on


def get_flight_info(date: datetime, flight_number: str) -> FlightInfo | None:
    """Pipeline to get FlightInfo from a date and flight number. Scrapes data from the web and formats."""
    try:
        response = make_flight_info_request(date, flight_number)
        flight_info = parse_response(response)
        if not flight_info:
            return
        processed_flight_info = process_flight_info(flight_info)
        correct_flight_dates_inplace(date, processed_flight_info)
        # print(processed_flight_info)
        return processed_flight_info
    except requests.exceptions.HTTPError as e:
        logger.warning(e)
        return


def correct_flight_dates_inplace(date: datetime, processed_flight_info: FlightInfo):
    """Corrects flight dates, if needed. Inplace mutation."""
    processed_flight_info.departure_time = processed_flight_info.departure_time.replace(year=date.year)
    processed_flight_info.arrival_time = processed_flight_info.arrival_time.replace(year=date.year)


def cleanse_flight_url(flight_url: str, date: datetime) -> str:
    "Cleanses the flight URL and add the correct date parameter."
    date_to_pass = date.strftime("%Y-%m-%d")
    parsed = urlparse(flight_url)
    query_params = parse_qs(parsed.query)
    query_params["date"] = [date_to_pass]
    new_query = urlencode(query_params, doseq=True)
    flight_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    return flight_url


def make_flight_info_request(date: datetime, flight_number: str) -> str:
    """Scrapes the web for flight info. Just gets the HTTP response."""
    # do the flight search
    flight_search_url = "https://aviability.com/en/flight/"
    payload = {"fn": flight_number.upper()}
    response = requests.post(flight_search_url, data=payload)
    response.raise_for_status()

    # Parse the response to find the flight-specific URL
    # Look for the flight URL - it should be something like /en/flight/ba999-british-airways
    soup = BeautifulSoup(response.content, "html.parser")
    flight_link = soup.find(
        "a", href=lambda x: x and x.startswith("/en/flight/") and flight_number.lower().replace(" ", "") in x.lower()
    )
    if not flight_link:
        raise RuntimeError(f"Flight URL for {flight_number} not found in the response.")

    # then the flight info search
    flight_url = "https://aviability.com" + flight_link["href"]
    flight_url = cleanse_flight_url(flight_url, date)
    response = requests.get(flight_url)
    response.raise_for_status()
    return response.text


def parse_response(response_text: str) -> dict[str, str]:
    """Extracts flight info from HTTP response. No post processing done yet."""
    soup = BeautifulSoup(response_text, "html.parser")

    # Check for no flights available
    if "No flights are available" in response_text:
        logger.warning("No flights are available for this departure date.")
        return {}

    # Extract flight number and airline from h1 tag
    h1 = soup.find("h1")
    if not h1:
        logger.warning("Could not find flight information in response")
        return {}

    h1_text = h1.get_text(strip=True)
    # Example: "BA 999 British Airways from Berlin to London on 19 July 2025"
    parts = h1_text.split()
    flight_number = f"{parts[0]} {parts[1]}"  # "BA 999"
    airline = parts[2]  # "British Airways"

    # Extract aircraft from meta description
    meta_desc = soup.find("meta", {"name": "Description"})
    aircraft = ""
    if meta_desc and "Plane" in meta_desc.get("content", ""):
        content = meta_desc.get("content")
        aircraft_part = content.split("Plane ")[1].split(",")[0] if "Plane " in content else ""
        aircraft = aircraft_part

    # Extract route information from the structured sections
    # Countries are in class "vc"
    countries = soup.find("div", class_="vc")
    country_divs = countries.find_all("div", class_="kc") if countries else []
    departure_country = country_divs[0].get_text(strip=True) if len(country_divs) > 0 else ""
    arrival_country = country_divs[1].get_text(strip=True) if len(country_divs) > 1 else ""

    # Airport names are in class "uc"
    airports = soup.find("div", class_="uc")
    airport_divs = airports.find_all("div", class_="kc") if airports else []
    departure_airport = airport_divs[0].get_text(strip=True) if len(airport_divs) > 0 else ""
    arrival_airport = airport_divs[1].get_text(strip=True) if len(airport_divs) > 1 else ""

    # Airport codes are in class "xc"
    codes = soup.find("div", class_="xc")
    code_divs = codes.find_all("div", class_="kc") if codes else []
    dep_code = code_divs[0].get_text(strip=True) if len(code_divs) > 0 else ""
    arr_code = code_divs[1].get_text(strip=True) if len(code_divs) > 1 else ""

    # Terminals are in class "wc"
    terminals = soup.find("div", class_="wc")
    terminal_divs = terminals.find_all("div", class_="kc") if terminals else []
    departure_terminal = terminal_divs[0].get_text(strip=True) if len(terminal_divs) > 0 else ""
    arrival_terminal = terminal_divs[1].get_text(strip=True) if len(terminal_divs) > 1 else ""

    # Flight times are in class "Ac"
    times = soup.find("div", class_="Ac")
    time_divs = times.find_all("div", class_="kc") if times else []
    departure_datetime = time_divs[0].get_text(strip=True) if len(time_divs) > 0 else ""
    arrival_datetime = time_divs[1].get_text(strip=True) if len(time_divs) > 1 else ""

    # Extract time and date parts
    # Format: "Jul 19, 07:55"
    if departure_datetime:
        dep_parts = departure_datetime.split(", ")
        departure_date = dep_parts[0] if len(dep_parts) > 0 else ""
        departure_time = dep_parts[1] if len(dep_parts) > 1 else ""
    else:
        departure_date = departure_time = ""

    if arrival_datetime:
        arr_parts = arrival_datetime.split(", ")
        arrival_date = arr_parts[0] if len(arr_parts) > 0 else ""
        arrival_time = arr_parts[1] if len(arr_parts) > 1 else ""
    else:
        arrival_date = arrival_time = ""

    # Duration is in class "Cc"
    duration_div = soup.find("div", class_="Cc")
    duration = ""
    if duration_div:
        duration_text = duration_div.get_text(strip=True)
        # Format: "Flight duration 2h 5 min"
        duration = duration_text.replace("Flight duration ", "")

    flight_info = {
        "flight_number": flight_number,
        "airline": airline,
        "departure_airport": f"{departure_airport} ({dep_code})",
        "arrival_airport": f"{arrival_airport} ({arr_code})",
        "departure_time": departure_time,
        "arrival_time": arrival_time,
        "departure_country": departure_country,
        "arrival_country": arrival_country,
        "departure_date": departure_date,
        "arrival_date": arrival_date,
        "departure_terminal": departure_terminal,
        "arrival_terminal": arrival_terminal,
        "duration": duration,
        "aircraft": aircraft,
    }

    return flight_info


def extract_airport_code(location: str) -> str:
    """Extract airport code from HTTP response"""
    return location.split("(")[-1].strip(")") if "(" in location else location


def extract_country(location: str) -> pycountry.db.Country:
    """Extract extract_country from HTTP response"""
    country_name = location.split(",")[-1].strip() if "," in location else location
    iso3 = cc.convert(country_name, to="ISO3")
    return pycountry.countries.get(alpha_3=iso3)


def extract_city_from_airport(airport_code: str) -> str:
    """Extract city from airport code"""
    return airports[airport_code]["city"]


def convert_to_datetime(date_str: str, time_str: str, airport_code: str) -> datetime:
    timezone = pytz.timezone(airports[airport_code]["tz"])

    # Handle new date format: "Jul 19" instead of "July 19, Saturday"
    try:
        date_obj = datetime.strptime(date_str, "%b %d")
    except ValueError:
        # Fallback to old format if needed
        date_obj = datetime.strptime(date_str, "%B %d, %A")

    time_obj = datetime.strptime(time_str, "%H:%M").time()
    combined_datetime = datetime.combine(date_obj, time_obj)
    combined_datetime = combined_datetime.replace(year=datetime.now().year)
    return timezone.localize(combined_datetime)


def parse_duration(duration_str: str) -> timedelta:
    hours, minutes = 0, 0
    if "h" in duration_str:
        hours = int(duration_str.split("h")[0].strip())
        duration_str = duration_str.split("h")[1].strip()
    if "m" in duration_str:
        minutes = int(duration_str.split("m")[0].strip())
    return timedelta(hours=hours, minutes=minutes)


def process_flight_info(raw_flight_info) -> FlightInfo:
    departure_airport = extract_airport_code(raw_flight_info.get("departure_airport", ""))
    arrival_airport = extract_airport_code(raw_flight_info.get("arrival_airport", ""))
    return FlightInfo(
        flight_number=raw_flight_info.get("flight_number"),
        airline=raw_flight_info.get("airline"),
        departure_airport=departure_airport,
        arrival_airport=arrival_airport,
        departure_country=extract_country(raw_flight_info.get("departure_country", "")),
        arrival_country=extract_country(raw_flight_info.get("arrival_country", "")),
        departure_city=extract_city_from_airport(departure_airport),
        arrival_city=extract_city_from_airport(arrival_airport),
        departure_terminal=raw_flight_info.get("departure_terminal"),
        arrival_terminal=raw_flight_info.get("arrival_terminal"),
        departure_time=convert_to_datetime(
            raw_flight_info.get("departure_date", ""),
            raw_flight_info.get("departure_time", ""),
            extract_airport_code(raw_flight_info.get("departure_airport", "")),
        ),
        arrival_time=convert_to_datetime(
            raw_flight_info.get("arrival_date", ""),
            raw_flight_info.get("arrival_time", ""),
            extract_airport_code(raw_flight_info.get("arrival_airport", "")),
        ),
        duration=parse_duration(raw_flight_info.get("duration", "")),
        aircraft=raw_flight_info.get("aircraft"),
    )


if __name__ == "__main__":
    d = datetime(2025, 2, 15)
    i = "LH2206"
    get_flight_info(d, i)
