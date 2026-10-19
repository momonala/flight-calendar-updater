"""Look up a flight by number and date on Flighty's private API.

Reverse-engineered from the iOS app. The API speaks protobuf both ways; the
minimal wire codec below is all that is needed for the two calls we make.
No .proto files, no protobuf dependency.

Auth: two JWTs supplied via FLIGHTY_AUTH_TOKEN and FLIGHTY_BUILD_TOKEN. Both
are read from a traffic capture of the app (e.g. mitmproxy on the phone):
the `authorization: Bearer ...` header is the auth token for an anonymous
account and does not expire; `x-flighty-build-token` is baked into the app
build and attests the client version.
"""

import json
import logging
import struct
import time
from base64 import urlsafe_b64encode
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from src.env import FLIGHTY_AUTH_TOKEN, FLIGHTY_BUILD_TOKEN
from src.datamodels import FlightInfo

logger = logging.getLogger(__name__)

_API = "https://api.flightyapp.com"
_SYNC_SCHEMA = "V_2026_07_10"
_AIRLINES_CACHE = Path(".cache/flighty_airlines.json")
_AIRLINES_CACHE_TTL_S = 7 * 24 * 3600
_TIMEOUT = 30

Msg = dict[str, list]  # field number -> values, one per occurrence


# --- protobuf wire codec --------------------------------------------------------------------------


def _varint(n: int) -> bytes:
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if not n:
            return out + bytes([b])
        out += bytes([b | 0x80])


def _field(number: int, value: str | bytes) -> bytes:
    """Encode one length-delimited field (string or nested message)."""
    raw = value.encode() if isinstance(value, str) else value
    return _varint(number << 3 | 2) + _varint(len(raw)) + raw


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")


def _decode(buf: bytes, depth: int = 0) -> Msg:
    """Schema-less decode: field number -> list of values. Nested messages decode recursively."""
    out: Msg = {}
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        number, wire_type = key >> 3, key & 7
        if number == 0:
            raise ValueError("field 0")
        if wire_type == 0:
            value, i = _read_varint(buf, i)
        elif wire_type == 1:
            value = struct.unpack("<d", buf[i : i + 8])[0]
            i += 8
        elif wire_type == 5:
            value = struct.unpack("<f", buf[i : i + 4])[0]
            i += 4
        elif wire_type == 2:
            n, i = _read_varint(buf, i)
            if i + n > len(buf):
                raise ValueError("truncated bytes")
            value = _decode_bytes(buf[i : i + n], depth)
            i += n
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        out.setdefault(str(number), []).append(value)
    return out


def _decode_bytes(raw: bytes, depth: int) -> Msg | str:
    """Printable text is a string; anything else is tried as a nested message, then shown as text."""
    try:
        text = raw.decode("utf-8")
        if text.isprintable():
            return text
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    if depth < 12:
        try:
            return _decode(raw, depth + 1)
        except (ValueError, struct.error):
            pass
    return text


def _first(msg: Msg | None, *path: str):
    """Walk field numbers, taking the first occurrence at each step. None if any step is missing."""
    node = msg
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key][0]
    return node


# --- HTTP ------------------------------------------------------------------------------------------


def check_credentials() -> None:
    """Fail fast at startup; get_flight_info swallows errors per row and would hide this."""
    if not (FLIGHTY_AUTH_TOKEN and FLIGHTY_BUILD_TOKEN):
        raise RuntimeError("FLIGHTY_AUTH_TOKEN and FLIGHTY_BUILD_TOKEN must be set")


def _headers() -> dict[str, str]:
    check_credentials()
    return {
        "authorization": f"Bearer {FLIGHTY_AUTH_TOKEN}",
        "x-flighty-build-token": FLIGHTY_BUILD_TOKEN,
        "user-agent": "Flighty 4.11.1 (4818) com.flightyapp.flighty",
        "x-flighty-locale": "en_DE",
        "content-type": "application/x-protobuf",
        "accept": "application/x-protobuf",
    }


def _post(path: str, body: bytes = b"") -> Msg:
    response = requests.post(_API + path, data=body, headers=_headers(), timeout=_TIMEOUT)
    response.raise_for_status()
    return _decode(response.content)


# --- airline table ---------------------------------------------------------------------------------


def _fetch_airlines() -> dict[str, list[dict]]:
    """IATA code -> airline rows, from the sync endpoint. Cursor skips the 13k-row airport table."""
    cursor = {"$sv": _SYNC_SCHEMA, "airport": int(time.time())}
    token = urlsafe_b64encode(json.dumps(cursor).encode()).decode().rstrip("=")
    page = _post(f"/v1/sync/full?token={token}")
    by_iata: dict[str, list[dict]] = {}
    for item in page.get("2", []):
        airline = _first(item, "2")
        iata = _first(airline, "3")
        if not isinstance(iata, str):
            continue
        by_iata.setdefault(iata, []).append(
            {
                "uuid": _first(airline, "1"),
                "name": _first(airline, "2"),
                "rank": _first(airline, "12") or 0,
            }
        )
    # Shared codes (LH: Lufthansa + Lufthansa Cargo) have no flag; the primary carrier has the highest rank.
    for rows in by_iata.values():
        rows.sort(key=lambda r: r["rank"], reverse=True)
    return by_iata


def clear_cache() -> None:
    _AIRLINES_CACHE.unlink(missing_ok=True)


def _airlines() -> dict[str, list[dict]]:
    """Airline table, cached on disk for a week. An empty table is never cached: it means the sync
    response did not have the shape we expect, and caching it would make every lookup fail until
    someone deleted the file by hand."""
    if _AIRLINES_CACHE.exists() and time.time() - _AIRLINES_CACHE.stat().st_mtime < _AIRLINES_CACHE_TTL_S:
        return json.loads(_AIRLINES_CACHE.read_text())
    airlines = _fetch_airlines()
    if not airlines:
        logger.error("Flighty sync returned no airlines; not caching")
        return airlines
    _AIRLINES_CACHE.parent.mkdir(exist_ok=True)
    _AIRLINES_CACHE.write_text(json.dumps(airlines))
    logger.info("Cached %d Flighty airline codes to %s", len(airlines), _AIRLINES_CACHE)
    return airlines


# --- search ----------------------------------------------------------------------------------------


def _split_flight_number(flight_number: str) -> tuple[str, str]:
    s = flight_number.replace(" ", "").upper()
    code = s[:3] if len(s) > 3 and s[2].isalpha() else s[:2]
    if len(s) <= len(code) or not s[len(code) :].isdigit():
        raise ValueError(f"Cannot parse flight number {flight_number!r}")
    return code, s[len(code) :]


def _search(airline_uuid: str, number: str, flight_date: str) -> list[Msg]:
    body = (
        _field(1, _field(1, airline_uuid) + _field(2, number))
        + _field(3, flight_date)
        + _field(4, "FLIGHT_NUMBER")
    )
    result = _post("/v1/search", body)
    results = _first(result, "2")
    return results.get("1", []) if isinstance(results, dict) else []


def search_flight(flight_number: str, flight_date: str) -> Msg | None:
    """Raw Flighty flight record for e.g. ("TK1730", "2026-10-03"), or None if nothing is scheduled.

    A flight number that flies several legs under the same number yields one record per leg;
    we return the earliest-departing one.
    """
    code, number = _split_flight_number(flight_number)
    candidates = _airlines().get(code, [])
    if not candidates:
        logger.warning("Flighty knows no airline with code %s", code)
        return None
    for airline in candidates:
        flights = _search(airline["uuid"], number, flight_date)
        if flights:
            logger.debug(
                "%s%s on %s matched airline %s",
                code,
                number,
                flight_date,
                airline["name"],
            )
            return min(flights, key=lambda f: _first(f, "2", "4", "1", "1") or float("inf"))
    return None


# --- mapping to FlightInfo -------------------------------------------------------------------------


def _local_time(epoch: int | None, tz_name: str | None) -> datetime | None:
    if epoch is None or not tz_name:
        return None
    return datetime.fromtimestamp(epoch, tz=ZoneInfo(tz_name))


def _flight_info_from_record(flight_number: str, flight: Msg) -> dict:
    dep, arr = _first(flight, "2"), _first(flight, "3")
    dep_airport, arr_airport = _first(dep, "1"), _first(arr, "1")
    dep_time = _local_time(_first(dep, "4", "1", "1"), _first(dep_airport, "5"))
    arr_time = _local_time(_first(arr, "7", "1", "1"), _first(arr_airport, "5"))
    if dep_time is None or arr_time is None:
        raise ValueError("Flighty record is missing scheduled times")
    return {
        "flight_number": flight_number,
        "airline": _first(flight, "4", "2"),
        "departure_airport": _first(dep_airport, "3"),
        "arrival_airport": _first(arr_airport, "3"),
        "departure_city": _first(dep_airport, "7"),
        "arrival_city": _first(arr_airport, "7"),
        "departure_country": _first(dep_airport, "9"),
        "arrival_country": _first(arr_airport, "9"),
        "departure_terminal": _first(dep, "2"),
        "arrival_terminal": _first(arr, "3"),
        "departure_time": dep_time,
        "arrival_time": arr_time,
        "duration": arr_time - dep_time,
        "aircraft": _first(flight, "7", "13") or _first(flight, "7", "2"),
    }


def get_flight_info(date: datetime, flight_number: str) -> FlightInfo | None:
    """Same contract as extract_flight_scrape.get_flight_info, backed by Flighty instead of a browser."""
    flight_date = date.strftime("%Y-%m-%d")
    try:
        flight = search_flight(flight_number, flight_date)
        if flight is None:
            logger.warning("Flighty has no %s on %s", flight_number, flight_date)
            return None
        info = FlightInfo.model_validate(_flight_info_from_record(flight_number.strip(), flight))
        logger.info(
            "Flighty: %s %s→%s",
            flight_number,
            info.departure_airport,
            info.arrival_airport,
        )
        return info
    except Exception:
        logger.exception("Flighty lookup failed for %s on %s", flight_number, flight_date)
        return None
