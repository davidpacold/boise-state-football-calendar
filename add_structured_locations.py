#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ICS_PATH = Path("docs/boise-state-football.ics")
STATE_PATH = Path("state.json")
TIMEZONE = "America/Denver"
TEAM_ID = "68"
CORE_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.espn.com/",
}

ALBERTSONS = {
    "title": "Albertsons Stadium",
    "address": "1400 Bronco Ln, Boise, ID 83706",
    "latitude": 43.6028,
    "longitude": -116.1958,
}

# Stable venue fallbacks for cities on Boise State's current rolling schedule.
# ESPN core venue metadata remains the first choice when it includes coordinates.
VENUE_BY_LOCATION = {
    "Eugene, Ore.": {
        "title": "Autzen Stadium",
        "address": "2727 Leo Harris Pkwy, Eugene, OR 97401",
        "latitude": 44.0583,
        "longitude": -123.0685,
    },
    "Kalamazoo, Mich.": {
        "title": "Waldo Stadium",
        "address": "1903 W Michigan Ave, Kalamazoo, MI 49008",
        "latitude": 42.2858,
        "longitude": -85.6017,
    },
    "Fresno, Calif.": {
        "title": "Valley Children's Stadium",
        "address": "1620 E Bulldog Ln, Fresno, CA 93740",
        "latitude": 36.8140,
        "longitude": -119.7580,
    },
    "Pullman, Wash.": {
        "title": "Martin Stadium",
        "address": "1775 NE Stadium Way, Pullman, WA 99164",
        "latitude": 46.7318,
        "longitude": -117.1605,
    },
    "Fort Collins, Colo.": {
        "title": "Canvas Stadium",
        "address": "751 W Pitkin St, Fort Collins, CO 80521",
        "latitude": 40.5700,
        "longitude": -105.0888,
    },
    "Reno, Nev.": {
        "title": "Mackay Stadium",
        "address": "1664 N Virginia St, Reno, NV 89557",
        "latitude": 39.5469,
        "longitude": -119.8179,
    },
    "USAFA, Colo.": {
        "title": "Falcon Stadium",
        "address": "2169 Field House Dr, USAF Academy, CO 80840",
        "latitude": 38.9969,
        "longitude": -104.8437,
    },
    "Tampa, Fla.": {
        "title": "Raymond James Stadium",
        "address": "4201 N Dale Mabry Hwy, Tampa, FL 33607",
        "latitude": 27.9759,
        "longitude": -82.5033,
    },
    "San Diego, Calif.": {
        "title": "Snapdragon Stadium",
        "address": "2101 Stadium Way, San Diego, CA 92108",
        "latitude": 32.7841,
        "longitude": -117.1227,
    },
}


def clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def get_json(url: str, params: dict | None = None) -> dict:
    response = requests.get(url, params=params, timeout=20, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def local_date(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    return dt.astimezone(ZoneInfo(TIMEZONE)).date().isoformat()


def full_address(address: dict) -> str:
    parts = []
    for key in ("address1", "address2", "city", "state", "postalCode", "country"):
        value = clean(address.get(key))
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


def venue_from_payload(payload: dict) -> dict | None:
    title = clean(payload.get("fullName") or payload.get("name"))
    address = payload.get("address") or {}
    address_text = full_address(address)
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    geo = payload.get("geo") or {}
    latitude = latitude if latitude is not None else geo.get("latitude")
    longitude = longitude if longitude is not None else geo.get("longitude")
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None
    if not title:
        return None
    return {
        "title": title,
        "address": address_text or title,
        "latitude": latitude,
        "longitude": longitude,
    }


def resolve_ref(ref: str) -> dict:
    return get_json(ref.replace("http://", "https://"))


def venue_for_event(event: dict) -> dict | None:
    for competition in event.get("competitions") or []:
        if not isinstance(competition, dict):
            continue
        if competition.get("$ref"):
            try:
                competition = resolve_ref(str(competition["$ref"]))
            except (requests.RequestException, ValueError):
                continue
        venue = competition.get("venue") or {}
        if isinstance(venue, dict) and venue.get("$ref"):
            try:
                venue = resolve_ref(str(venue["$ref"]))
            except (requests.RequestException, ValueError):
                venue = {}
        if isinstance(venue, dict):
            parsed = venue_from_payload(venue)
            if parsed:
                return parsed
    return None


def fetch_venues(seasons: set[int]) -> dict[str, dict]:
    venues: dict[str, dict] = {}
    for season in sorted(seasons):
        url = f"{CORE_BASE}/seasons/{season}/teams/{TEAM_ID}/events"
        try:
            listing = get_json(url, {"limit": 50})
        except (requests.RequestException, ValueError) as exc:
            print(f"Warning: venue listing unavailable for {season}: {exc}")
            continue
        for item in listing.get("items") or []:
            ref = clean((item or {}).get("$ref"))
            if not ref:
                continue
            try:
                event = resolve_ref(ref)
            except (requests.RequestException, ValueError):
                continue
            date = local_date(clean(event.get("date")))
            if not date:
                continue
            venue = venue_for_event(event)
            if venue:
                venues[date] = venue
    return venues


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def fold(line: str) -> list[str]:
    out: list[str] = []
    current = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        if current and size + width > 73:
            out.append(current)
            current = " " + char
            size = 1 + width
        else:
            current += char
            size += width
    out.append(current)
    return out


def ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def structured_line(venue: dict) -> str:
    title = parameter_value(clean(venue["title"]))
    address = parameter_value(clean(venue["address"]))
    lat = float(venue["latitude"])
    lon = float(venue["longitude"])
    return (
        "X-APPLE-STRUCTURED-LOCATION;VALUE=URI;"
        f"X-ADDRESS={address};X-APPLE-RADIUS=150;X-TITLE={title}:geo:{lat:.6f},{lon:.6f}"
    )


def parameter_value(value: str) -> str:
    # Parameters use quoted strings and RFC 6868, not TEXT backslash escaping.
    value = value.replace("^", "^^").replace('"', "^'").replace("\n", "^n")
    return f'"{value}"'


def location_lines(venue: dict) -> list[str]:
    display = clean(venue["title"]) + "\n" + clean(venue["address"])
    return [
        f"LOCATION:{ics_escape(display)}",
        structured_line(venue),
        f"GEO:{float(venue['latitude']):.6f};{float(venue['longitude']):.6f}",
    ]


def enrich_event(event: list[str], venues: dict, state: dict, now: str) -> list[str]:
    uid = next(line[4:] for line in event if line.startswith("UID:"))
    match = re.match(r"boisestate-football-(\d{4}-\d{2}-\d{2})@", uid)
    if not match:
        return event
    location = next((line for line in event if line.startswith("LOCATION:")), "")
    display = location[9:].replace("\\,", ",")
    venue = venues.get(match.group(1))
    if "Albertsons Stadium" in display:
        venue = ALBERTSONS
    elif not venue:
        venue = VENUE_BY_LOCATION.get(display)
        if not venue:
            venue = next((v for v in VENUE_BY_LOCATION.values()
                          if location == location_lines(v)[0]), None)
    properties = location_lines(venue) if venue else ([location] if location else [])
    prior = state["events"][uid]
    fingerprint = hashlib.sha256("\n".join(properties).encode()).hexdigest()
    sequence = max(int(prior["sequence"]), int(next(
        (line[9:] for line in event if line.startswith("SEQUENCE:")), "0")))
    if prior.get("location_fingerprint") != fingerprint:
        # Migrate existing subscriptions once, then update only on real changes.
        if venue or "location_fingerprint" in prior:
            sequence += 1
            prior["location_modified"] = now
        prior["location_fingerprint"] = fingerprint
    prior["sequence"] = sequence
    output = []
    for line in event:
        if line.startswith(("LOCATION:", "GEO:", "X-APPLE-STRUCTURED-LOCATION;", "LAST-MODIFIED:")):
            continue
        if line.startswith("SEQUENCE:"):
            line = f"SEQUENCE:{sequence}"
        if line == "END:VEVENT":
            output.extend(properties)
            if prior.get("location_modified"):
                output.append(f"LAST-MODIFIED:{prior['location_modified']}")
        output.append(line)
    return output


def enrich_calendar(text: str, venues: dict, state: dict) -> str:
    output: list[str] = []
    event: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for line in unfold(text):
        if not line:
            continue
        if event or line == "BEGIN:VEVENT":
            event.append(line)
            if line == "END:VEVENT":
                output.extend(enrich_event(event, venues, state, now))
                event = []
        else:
            output.append(line)
    return "\r\n".join(part for line in output for part in fold(line)) + "\r\n"


def main() -> None:
    text = ICS_PATH.read_text(encoding="utf-8")
    dates = re.findall(r"UID:boisestate-football-(\d{4}-\d{2}-\d{2})@", text)
    venues = fetch_venues({int(date[:4]) for date in dates})
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    folded = enrich_calendar(text, venues, state)
    ICS_PATH.write_text(folded, encoding="utf-8", newline="")
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    count = folded.count("X-APPLE-STRUCTURED-LOCATION;")
    print(f"Added Apple structured locations for {count} games")


if __name__ == "__main__":
    main()
