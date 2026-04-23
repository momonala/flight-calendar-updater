"""Scrape aviability.com for live flight data, then use LLM for structured extraction."""

import json
import logging
from datetime import datetime, timedelta

import airportsdata
import pytz
from joblib import Memory
from openai import OpenAI
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.datamodels import FlightInfo

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
memory = Memory(location=".cache")

_airports = airportsdata.load("IATA")

_EXTRACTION_PROMPT = """\
Extract structured flight data from the text signals below. Return JSON only — no markdown, no prose.

meta_description: {meta_description}

main_text: {main_text}

Return exactly these fields:
{{
  "departure_airport": string,
  "arrival_airport": string,
  "departure_city": string,
  "arrival_city": string,
  "departure_country": string,
  "arrival_country": string,
  "airline": string,
  "aircraft": string | null,
  "arrival_terminal": string | null
}}

Rules:
- departure_airport / arrival_airport: IATA code (e.g. "BRS", "BER")
- departure_country / arrival_country: ISO 3166-1 alpha-2 (e.g. "GB", "DE")
- arrival_terminal: raw value from text (e.g. "1", "Terminal 1") or null if absent
- aircraft: most specific model known (e.g. "Airbus A320-214") or null"""


def _make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def _scrape_signals(flight_number: str, flight_date: str) -> dict:
    """Navigate aviability.com to the flight detail page and return extracted text signals."""
    driver = _make_driver()
    try:
        # Step 1: POST flight number to search → overview page
        logger.debug("Navigating to aviability.com search for %s", flight_number)
        driver.get("https://aviability.com/en/flight")
        driver.execute_script(
            """
            var f = document.createElement('form');
            f.method = 'POST';
            f.action = 'https://aviability.com/en/flight';
            var i = document.createElement('input');
            i.type = 'hidden'; i.name = 'fn'; i.value = arguments[0];
            f.appendChild(i);
            document.body.appendChild(f);
            f.submit();
            """,
            flight_number,
        )
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-ct="q"]')))
        logger.debug("Overview page loaded: %s", driver.current_url)

        # Parse calendar JSON to get route path and availability bitset
        script_el = driver.find_element(By.CSS_SELECTOR, '[data-ct="q"] script[type="application/json"]')
        cal = json.loads(script_el.get_attribute("innerHTML"))
        route = cal["r"][0]  # [dep_iata, arr_iata, route_path]
        route_path = route[2]
        logger.debug("Route path: %s  dep=%s arr=%s", route_path, route[0], route[1])

        # Step 2: POST date → detail page
        logger.debug("Posting date %s to %s", flight_date, route_path)
        driver.execute_script(
            """
            var f = document.createElement('form');
            f.method = 'POST';
            f.action = 'https://aviability.com' + arguments[0];
            var i = document.createElement('input');
            i.type = 'hidden'; i.name = 'date'; i.value = arguments[1];
            f.appendChild(i);
            document.body.appendChild(f);
            f.submit();
            """,
            route_path,
            flight_date,
        )
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-ct="o"]')))
        logger.debug("Detail page loaded: %s", driver.current_url)

        # Extract stable signals from the detail page
        meta_desc = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]').get_attribute("content")
        main_text = driver.find_element(By.TAG_NAME, "main").text
        # data-ct="o" is an attribute ON the <time> elements, not a parent container
        time_els = driver.find_elements(By.CSS_SELECTOR, 'time[data-ct="o"][datetime]')

        logger.debug("Meta description: %s", meta_desc)
        logger.debug("Main text: %s", main_text)
        logger.debug("Time elements found: %d", len(time_els))

        if len(time_els) < 2:
            raise ValueError("Could not find both UTC departure/arrival <time> elements")

        dep_utc = time_els[0].get_attribute("datetime")
        arr_utc = time_els[1].get_attribute("datetime")
        logger.debug("Extracted UTC times: dep=%s arr=%s", dep_utc, arr_utc)

        return {
            "meta_description": meta_desc,
            "main_text": main_text,
            "dep_utc_iso": dep_utc,
            "arr_utc_iso": arr_utc,
        }
    finally:
        driver.quit()


def _utc_to_local(utc_iso: str, airport_iata: str) -> datetime:
    """Convert a UTC ISO datetime string to the airport's local timezone."""
    dt_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    tz = pytz.timezone(_airports[airport_iata]["tz"])
    return dt_utc.astimezone(tz)


def _extract_with_llm(signals: dict) -> dict:
    """Call OpenAI to extract structured fields from the scraped text signals."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = _EXTRACTION_PROMPT.format(
        meta_description=signals["meta_description"],
        main_text=signals["main_text"],
    )
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[{"role": "user", "content": prompt}],
    )
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    text = content.text.strip()
                    if text.startswith("```"):
                        lines = text.split("\n")[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        text = "\n".join(lines)
                    return json.loads(text)
    raise ValueError("No output_text in LLM response")


@memory.cache
def get_flight_data(flight_number: str, flight_date: str) -> dict:
    """Scrape aviability.com + LLM extraction → raw dict matching FlightInfo schema."""
    logger.debug("Fetching flight data for %s on %s", flight_number, flight_date)
    signals = _scrape_signals(flight_number, flight_date)
    logger.debug("Scrape complete, calling LLM for field extraction")
    llm_extracted_fields = _extract_with_llm(signals)
    logger.debug("LLM extraction result: %s", llm_extracted_fields)

    dep_airport = llm_extracted_fields["departure_airport"]
    arr_airport = llm_extracted_fields["arrival_airport"]

    dep_time = _utc_to_local(signals["dep_utc_iso"], dep_airport)
    arr_time = _utc_to_local(signals["arr_utc_iso"], arr_airport)
    duration: timedelta = arr_time - dep_time
    logger.debug("Computed dep=%s arr=%s duration=%s", dep_time, arr_time, duration)

    return {
        "flight_number": flight_number,
        "operating_flight_number": "",
        "airline": llm_extracted_fields["airline"],
        "operating_airline": "",
        "departure_airport": dep_airport,
        "arrival_airport": arr_airport,
        "departure_city": llm_extracted_fields["departure_city"],
        "arrival_city": llm_extracted_fields["arrival_city"],
        "departure_country": llm_extracted_fields["departure_country"],
        "arrival_country": llm_extracted_fields["arrival_country"],
        "departure_terminal": None,
        "arrival_terminal": llm_extracted_fields.get("arrival_terminal"),
        "departure_time": dep_time,
        "arrival_time": arr_time,
        "duration": duration,
        "aircraft": llm_extracted_fields.get("aircraft"),
        "route_distance_km": None,
    }


def get_flight_info(date: datetime, flight_number: str) -> FlightInfo | None:
    """Scrape + extract FlightInfo for a given flight and date. Drop-in for extract_flight_ai.get_flight_info."""
    try:
        flight_date = date.strftime("%Y-%m-%d")
        logger.info("Getting flight info for %s on %s", flight_number, flight_date)
        raw = get_flight_data(flight_number.strip(), flight_date)
        flight_info = FlightInfo.model_validate(raw)
        logger.info(
            "Successfully built FlightInfo: %s %s→%s",
            flight_number,
            raw["departure_airport"],
            raw["arrival_airport"],
        )
        return flight_info
    except Exception as e:
        logger.warning("Failed to get flight info for %s on %s: %s", flight_number, date, e)
        return None


if __name__ == "__main__":
    import json as _json

    data = get_flight_data("U22933", "2026-06-23")
    print(_json.dumps(data, indent=2, default=str))
