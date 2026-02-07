import json
import logging
from datetime import datetime

from joblib import Memory
from openai import OpenAI

from src.datamodels import FlightInfo
from src.values import OPENAI_API_KEY

logging.basicConfig()
logger = logging.getLogger(__name__)

memory = Memory(location=".cache")

system_prompt = """
You are a data extraction and normalization engine for commercial flights.

Given:
- flight_number (string, IATA format, e.g. "LX4407")
- flight_date (ISO 8601 date, YYYY-MM-DD)

Your task:
1. Search multiple independent sources for the flight, including:
   - Airline official site
   - FlightAware
   - Flightradar24
   - Aviability
   - At least one additional reputable flight status or schedule aggregator
2. Prefer official airline data when conflicts exist.
3. If exact data for the given date is unavailable (future or missing),
   infer from the most recent consistent schedule pattern and clearly mark it as "scheduled".

Normalization rules:
- Airports must be IATA codes (e.g. "BER", "ZRH")
- Countries must be ISO 3166-1 alpha-2 codes (e.g. "DE", "CH")
- Times must be local to the airport and returned as ISO 8601 datetime strings
- Duration must be ISO 8601 duration format (e.g. "PT1H30M")
- Aircraft must be the most specific known model (e.g. "Airbus A320-214"), otherwise family ("Airbus A320")

Compute additional statistics (route- or flight-level):
- average_departure_delay_minutes (number)
- average_arrival_delay_minutes (number)
- on_time_performance_percent (0–100)
- typical_flight_time_minutes (number)
- route_distance_km (number, great-circle)

If a value cannot be confidently determined:
- Use null
- Do NOT guess
- Do NOT fabricate precision

Return ONLY valid JSON matching exactly this schema:

{
  "flight_number": string,
  "operating_flight_number": string,
  "airline": string,
  "operating_airline": string,
  "departure_airport": string,
  "arrival_airport": string,
  "departure_city": string,
  "arrival_city": string,
  "departure_country": string,
  "arrival_country": string,
  "departure_terminal": string | null,
  "arrival_terminal": string | null,
  "departure_time": string,        // ISO 8601, local
  "arrival_time": string,          // ISO 8601, local
  "duration": string,              // ISO 8601 duration
  "aircraft": string | null,
  "route_distance_km": number | null,
  "data_sources": [
    {
      "source": string,
      "used_for": string
    }
  ],
  "data_quality": {
    "status": "actual" | "scheduled" | "inferred",
    "confidence": "high" | "medium" | "low",
    "notes": string
  }
}

Constraints:
- Output JSON only (no markdown, no prose).
- Dates and times must be internally consistent.
- Do not include fields not defined in the schema.
"""


def extract_json_from_response(response) -> dict:
    """Extract raw JSON from the assistant's final text (handles optional markdown code fence)."""
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    text = content.text.strip()
                    if text.startswith("```"):
                        lines = text.split("\n")
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        text = "\n".join(lines)
                    return json.loads(text)
    raise ValueError("No output_text found in response")


@memory.cache
def get_flight_data(
    flight_number: str,
    flight_date: str,
    system_prompt: str = system_prompt,
) -> dict:
    """Fetch normalized flight data for a given flight number and date (raw dict from API)."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    user_prompt = {"flight_number": flight_number, "flight_date": flight_date}
    response = client.responses.create(
        model="gpt-5.2",
        tools=[{"type": "web_search"}],
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
    )
    return extract_json_from_response(response)


def get_flight_info(date: datetime, flight_number: str) -> FlightInfo | None:
    """Pipeline: fetch AI flight data, validate into FlightInfo for calendar/sheets. Drop-in for extract_flight.get_flight_info."""
    try:
        flight_date = date.strftime("%Y-%m-%d")
        raw = get_flight_data(flight_number.strip(), flight_date)
        return FlightInfo.model_validate(raw)
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("Failed to get flight info for %s on %s: %s", flight_number, date, e)
        return None


if __name__ == "__main__":
    flight_data = get_flight_data("LX4407", "2025-07-23")
    print(json.dumps(flight_data, indent=2))
