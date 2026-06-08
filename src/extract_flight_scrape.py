"""Scrape aviability.com for live flight data, then use LLM for structured extraction."""

import json
import logging
import os
from datetime import datetime

import airportsdata
import pytz
from joblib import Memory
from openai import OpenAI
from playwright.sync_api import Page, sync_playwright

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


def _dump_html(page: Page, label: str) -> None:
    os.makedirs(".cache", exist_ok=True)
    path = f".cache/debug_{label.replace(' ', '_').replace('/', '-')}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(page.content())
    logger.debug("[HTML dump] %s → %s  (url=%s)", label, path, page.url)


def _post_form(page: Page, action: str, field_name: str, field_value: str) -> None:
    page.evaluate(
        """([action, name, value]) => {
            var f = document.createElement('form');
            f.method = 'POST'; f.action = action;
            var i = document.createElement('input');
            i.type = 'hidden'; i.name = name; i.value = value;
            f.appendChild(i); document.body.appendChild(f); f.submit();
        }""",
        [action, field_name, field_value],
    )


def _wait_for(page: Page, css: str, label: str, timeout: int = 20) -> None:
    try:
        page.wait_for_selector(css, state="attached", timeout=timeout * 1000)
        logger.debug("Page ready [%s]: %s", label, page.url)
    except Exception as e:
        _dump_html(page, f"{label}_timeout")
        raise RuntimeError(f"Timed out waiting for {label} ({css!r}): {e}") from e


def _find_route_path(page: Page) -> str:
    for el in page.query_selector_all('script[type="application/json"]'):
        try:
            parsed = json.loads(el.inner_html())
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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.route("**/*fundingchoicesmessages.google.com*/**", lambda route: route.abort())
        try:
            logger.debug("Navigating to aviability.com for %s", flight_number)
            page.goto("https://aviability.com/en/flight")
            _post_form(page, "https://aviability.com/en/flight", "fn", flight_number)
            _wait_for(page, 'script[type="application/json"]', "overview")

            route_path = _find_route_path(page)
            detail_url = "https://aviability.com" + route_path

            logger.debug("Posting date %s to %s", flight_date, detail_url)
            _post_form(page, detail_url, "date", flight_date)
            _wait_for(page, f'time[datetime^="{flight_date}T"]', "detail")

            _dump_html(page, "03_detail")
            main_el = page.query_selector("main")
            main_html = main_el.inner_html()
            logger.debug("main HTML length: %d chars", len(main_html))
            return main_html
        finally:
            browser.close()


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
