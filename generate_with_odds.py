#!/usr/bin/env python3
from __future__ import annotations

import re

import requests

import generate_calendar as calendar

ESPN_CORE_ODDS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/"
    "events/{event_id}/competitions/{competition_id}/odds"
)
PREFERRED_PROVIDER_IDS = ("37", "41", "58", "68")
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com",
}

_original_requests_get = requests.get


def espn_friendly_get(url, *args, **kwargs):
    if "espn.com" in str(url):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(BROWSER_HEADERS)
        kwargs["headers"] = headers
    return _original_requests_get(url, *args, **kwargs)


# generate_calendar imports the requests module, so replacing get here also fixes
# its schedule/scoreboard calls while leaving Boise State requests unchanged.
calendar.requests.get = espn_friendly_get


def clean_line(value: object) -> str:
    return calendar.clean(str(value or ""))


def normalize_line(details: str) -> str:
    return clean_line(details).replace("−", "-").replace("–", "-")


def fetch_core_odds(event: dict, competition: dict) -> str:
    event_id = str(event.get("id") or "").strip()
    competition_id = str(competition.get("id") or event_id).strip()
    if not event_id or not competition_id:
        return ""

    url = ESPN_CORE_ODDS_URL.format(event_id=event_id, competition_id=competition_id)
    try:
        response = _original_requests_get(
            url,
            params={"limit": 100},
            timeout=20,
            headers=BROWSER_HEADERS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Warning: ESPN core odds unavailable for event {event_id}: {exc}")
        return ""

    items = payload.get("items") or []
    if not items:
        return ""

    def provider_id(item: dict) -> str:
        provider = item.get("provider") or {}
        return str(provider.get("id") or "")

    def provider_priority(item: dict) -> int:
        provider = item.get("provider") or {}
        try:
            return int(provider.get("priority"))
        except (TypeError, ValueError):
            return 999

    ordered: list[dict] = []
    for preferred_id in PREFERRED_PROVIDER_IDS:
        ordered.extend(item for item in items if provider_id(item) == preferred_id)
    ordered.extend(sorted(
        (item for item in items if provider_id(item) not in PREFERRED_PROVIDER_IDS),
        key=provider_priority,
    ))

    seen: set[int] = set()
    for item in ordered:
        marker = id(item)
        if marker in seen:
            continue
        seen.add(marker)
        details = normalize_line(item.get("details") or "")
        if re.search(r"\b[A-Z0-9]{2,6}\s+[+-]?\d+(?:\.\d+)?\b", details):
            return details
    return ""


_original_event_info = calendar.espn_event_info


def enhanced_event_info(event: dict):
    local_date, info = _original_event_info(event)
    if not local_date or not info:
        return local_date, info

    competitions = event.get("competitions") or []
    if competitions and not info.get("betting_line"):
        completed = bool(
            (competitions[0].get("status") or event.get("status") or {})
            .get("type", {})
            .get("completed")
        )
        if not completed:
            line = fetch_core_odds(event, competitions[0])
            if line:
                info = dict(info)
                info["betting_line"] = line
    return local_date, info


calendar.espn_event_info = enhanced_event_info

if __name__ == "__main__":
    calendar.main()
