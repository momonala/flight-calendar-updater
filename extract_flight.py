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
        processed_flight_info = process_flight_info(flight_info)
        correct_flight_dates_inplace(date, processed_flight_info)
        # print(processed_flight_info)
        return processed_flight_info
    except requests.exceptions.HTTPError as e:
        logger.warning(e)
        return


def correct_flight_dates_inplace(date: datetime, processed_flight_info: FlightInfo):
    """Corrects flight dates, if needed. Inplace mutation."""
    processed_flight_info.departure_time = processed_flight_info.departure_time.replace(
        year=date.year
    )
    processed_flight_info.arrival_time = processed_flight_info.arrival_time.replace(
        year=date.year
    )


def make_flight_info_request(date: datetime, flight_number: str) -> str:
    """Scrapes the web for flight info. Just gets the HTTP response."""
    # do the flight search
    flight_search_url = "https://aviability.com/flight-number/index.php"
    payload = {"FlightNumber": flight_number}
    response = requests.post(flight_search_url, data=payload)
    response.raise_for_status()

    # then the flight info search
    info_search_url = response.url
    date_to_pass = date.strftime("%Y-%m-%d")
    payload = {"_date": date_to_pass}
    response = requests.post(info_search_url, data=payload)
    response.raise_for_status()
    return response.text


def parse_response(response_text: str) -> dict[str, str]:
    """Extracts flight info from HTTP response. No post processing done yet."""
    soup = BeautifulSoup(response_text, "html.parser")
    stz = soup.find_all("div", class_="stp stz")
    stv = soup.find_all("div", class_="stv")
    stp = soup.find_all("div", class_="stp")

    flight_info = {
        "flight_number": soup.find("div", class_="stn").get_text(strip=True),
        "airline": soup.find("div", class_="sta").get_text(strip=True),
        "departure_airport": stz[0].get_text(strip=True),
        "arrival_airport": stz[1].get_text(strip=True),
        "departure_time": stv[0].get_text(strip=True),
        "arrival_time": stv[1].get_text(strip=True),
        "departure_country": stp[2].get_text(strip=True),
        "arrival_country": stp[3].get_text(strip=True),
        "departure_date": stp[-2].get_text(strip=True),
        "arrival_date": stp[-1].get_text(strip=True),
    }

    if len(stp) >= 8:
        flight_info["departure_terminal"] = stp[4].get_text(strip=True)
        flight_info["arrival_terminal"] = stp[5].get_text(strip=True)

    html_for_aircraft_and_duration = soup.find_all("div", class_="stg stu")
    for html in html_for_aircraft_and_duration:
        html = html.get_text(strip=True)
        if html.startswith("Flight duration"):
            flight_info["duration"] = html.replace("Flight duration: ", "")
        else:
            flight_info["aircraft"] = html
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
    departure_airport = extract_airport_code(
        raw_flight_info.get("departure_airport", "")
    )
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
