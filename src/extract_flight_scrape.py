"""Scrape aviability.com for live flight data, then use LLM for structured extraction."""

import json
import logging
import os
from datetime import datetime

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
memory = Memory(location=".cache")

_airports = airportsdata.load("IATA")

_EXTRACTION_PROMPT = """\
Extract structured flight data from the HTML of a flight detail page. Return JSON only — no markdown, no prose.

HTML:
{main_html}

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
  "arrival_terminal": string | null,
  "dep_utc_iso": string,
  "arr_utc_iso": string
}}

Rules:
- departure_airport / arrival_airport: IATA code (e.g. "BRS", "BER")
- departure_country / arrival_country: ISO 3166-1 alpha-2 (e.g. "GB", "DE")
- arrival_terminal: raw value from text (e.g. "1", "Terminal 1") or null if absent
- aircraft: most specific model known (e.g. "Airbus A320-214") or null
- dep_utc_iso / arr_utc_iso: from <time datetime="..."> elements whose value contains "T" (e.g. "2026-05-20T06:50Z");
  the first such element is departure, the second is arrival"""


def _make_driver() -> webdriver.Chrome:
    opts = Options()
    # opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=opts)
    # Block Google Funding Choices at network level so the consent wall never loads
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*fundingchoicesmessages.google.com*"]})
    return driver


def _dump_html(driver: webdriver.Chrome, label: str) -> None:
    os.makedirs(".cache", exist_ok=True)
    path = f".cache/debug_{label.replace(' ', '_').replace('/', '-')}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    logger.debug("[HTML dump] %s → %s  (url=%s)", label, path, driver.current_url)


def _post_form(driver: webdriver.Chrome, action: str, field_name: str, field_value: str) -> None:
    driver.execute_script(
        """
        var f = document.createElement('form');
        f.method = 'POST'; f.action = arguments[0];
        var i = document.createElement('input');
        i.type = 'hidden'; i.name = arguments[1]; i.value = arguments[2];
        f.appendChild(i); document.body.appendChild(f); f.submit();
        """,
        action,
        field_name,
        field_value,
    )


def _wait_for(driver: webdriver.Chrome, css: str, label: str, timeout: int = 20) -> None:
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))
        logger.debug("Page ready [%s]: %s", label, driver.current_url)
    except Exception as e:
        _dump_html(driver, f"{label}_timeout")
        raise RuntimeError(f"Timed out waiting for {label} ({css!r}): {e}") from e


def _find_route_path(driver: webdriver.Chrome) -> str:
    for el in driver.find_elements(By.CSS_SELECTOR, 'script[type="application/json"]'):
        try:
            parsed = json.loads(el.get_attribute("innerHTML"))
        except json.JSONDecodeError:
            continue
        routes = parsed.get("r")
        if isinstance(routes, list) and routes:
            route_path = routes[0][2]
            logger.debug("Route path: %s  dep=%s arr=%s", route_path, routes[0][0], routes[0][1])
            return route_path
    raise RuntimeError("No JSON script with routes 'r' key found on overview page")


def _scrape_main_html(flight_number: str, flight_date: str) -> str:
    """Navigate aviability.com to the flight detail page and return the <main> HTML."""
    driver = _make_driver()
    try:
        logger.debug("Navigating to aviability.com for %s", flight_number)
        driver.get("https://aviability.com/en/flight")
        _post_form(driver, "https://aviability.com/en/flight", "fn", flight_number)
        _wait_for(driver, 'script[type="application/json"]', "overview")

        route_path = _find_route_path(driver)
        detail_url = "https://aviability.com" + route_path

        logger.debug("Posting date %s to %s", flight_date, detail_url)
        _post_form(driver, detail_url, "date", flight_date)
        _wait_for(driver, f'time[datetime^="{flight_date}T"]', "detail")

        _dump_html(driver, "03_detail")
        main_html = driver.find_element(By.TAG_NAME, "main").get_attribute("outerHTML")
        logger.debug("main HTML length: %d chars", len(main_html))
        return main_html
    finally:
        driver.quit()


def _utc_to_local(utc_iso: str, airport_iata: str) -> datetime:
    dt_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    tz = pytz.timezone(_airports[airport_iata]["tz"])
    return dt_utc.astimezone(tz)


def _extract_with_llm(main_html: str) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[{"role": "user", "content": _EXTRACTION_PROMPT.format(main_html=main_html)}],
    )
    output_texts = [
        c.text
        for item in response.output
        if item.type == "message"
        for c in item.content
        if c.type == "output_text"
    ]
    if not output_texts:
        raise ValueError("No output_text in LLM response")
    text = output_texts[0].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n```", 1)[0].strip()
    return json.loads(text)


@memory.cache
def get_flight_data(flight_number: str, flight_date: str) -> dict:
    """Scrape aviability.com + LLM extraction → raw dict matching FlightInfo schema."""
    logger.debug("Fetching flight data for %s on %s", flight_number, flight_date)
    main_html = _scrape_main_html(flight_number, flight_date)
    fields = _extract_with_llm(main_html)
    logger.debug("LLM extraction result: %s", fields)

    dep_airport = fields["departure_airport"]
    arr_airport = fields["arrival_airport"]
    dep_time = _utc_to_local(fields["dep_utc_iso"], dep_airport)
    arr_time = _utc_to_local(fields["arr_utc_iso"], arr_airport)
    logger.debug("Computed dep=%s arr=%s duration=%s", dep_time, arr_time, arr_time - dep_time)

    return {
        "flight_number": flight_number,
        "operating_flight_number": "",
        "airline": fields["airline"],
        "operating_airline": "",
        "departure_airport": dep_airport,
        "arrival_airport": arr_airport,
        "departure_city": fields["departure_city"],
        "arrival_city": fields["arrival_city"],
        "departure_country": fields["departure_country"],
        "arrival_country": fields["arrival_country"],
        "departure_terminal": None,
        "arrival_terminal": fields.get("arrival_terminal"),
        "departure_time": dep_time,
        "arrival_time": arr_time,
        "duration": arr_time - dep_time,
        "aircraft": fields.get("aircraft"),
        "route_distance_km": None,
    }


def get_flight_info(date: datetime, flight_number: str) -> FlightInfo | None:
    """Scrape + extract FlightInfo for a given flight and date."""
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
    data = get_flight_data("U22933", "2026-06-23")
    print(json.dumps(data, indent=2, default=str))
