#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import generate_calendar as calendar

ESPN_CORE_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
ESPN_CORE_ODDS_URL = f"{ESPN_CORE_BASE}/events/{{event_id}}/competitions/{{competition_id}}/odds"
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
}

_original_requests_get = requests.get
_original_scoreboard_date = calendar.fetch_espn_scoreboard_date


def espn_get(url: str, *, params: dict | None = None, timeout: int = 20):
    return _original_requests_get(url, params=params, timeout=timeout, headers=BROWSER_HEADERS)


def espn_friendly_get(url, *args, **kwargs):
    if "espn.com" in str(url):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(BROWSER_HEADERS)
        kwargs["headers"] = headers
    return _original_requests_get(url, *args, **kwargs)


calendar.requests.get = espn_friendly_get


def clean_line(value: object) -> str:
    return calendar.clean(str(value or ""))


def normalize_line(details: str) -> str:
    return clean_line(details).replace("−", "-").replace("–", "-")


def choose_odds_line(items: list[dict]) -> str:
    def provider_id(item: dict) -> str:
        return str((item.get("provider") or {}).get("id") or "")

    def provider_priority(item: dict) -> int:
        try:
            return int((item.get("provider") or {}).get("priority"))
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


def ref_id(ref: str, marker: str) -> str:
    match = re.search(rf"/{marker}/(\d+)(?:\?|$|/)", ref)
    return match.group(1) if match else ""


def event_local_date(event: dict) -> str:
    raw = str(event.get("date") or "")
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.astimezone(ZoneInfo(calendar.TIMEZONE)).date().isoformat()


def fetch_core_odds_by_ids(event_id: str, competition_id: str) -> str:
    try:
        response = espn_get(
            ESPN_CORE_ODDS_URL.format(event_id=event_id, competition_id=competition_id),
            params={"limit": 100},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Warning: ESPN core odds unavailable for event {event_id}: {exc}")
        return ""
    return choose_odds_line(payload.get("items") or [])


def fetch_core_odds(event: dict, competition: dict) -> str:
    event_id = str(event.get("id") or "").strip()
    competition_id = str(competition.get("id") or event_id).strip()
    if not event_id or not competition_id:
        return ""
    return fetch_core_odds_by_ids(event_id, competition_id)


def core_date_odds(date_str: str) -> str:
    """Use Boise State's core team event feed to find the game and its odds."""
    season = date_str[:4]
    team_events_url = f"{ESPN_CORE_BASE}/seasons/{season}/teams/{calendar.ESPN_TEAM_ID}/events"
    try:
        response = espn_get(team_events_url, params={"limit": 50})
        response.raise_for_status()
        listing = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Warning: ESPN core Boise events unavailable for {season}: {exc}")
        return ""

    for item in listing.get("items") or []:
        event_ref = str(item.get("$ref") or "")
        event_id = ref_id(event_ref, "events")
        if not event_id:
            continue
        try:
            event_response = espn_get(event_ref.replace("http://", "https://"))
            event_response.raise_for_status()
            event = event_response.json()
        except (requests.RequestException, ValueError):
            continue
        if event_local_date(event) != date_str:
            continue

        competitions = event.get("competitions") or []
        competition_refs = [
            str(c.get("$ref")) for c in competitions
            if isinstance(c, dict) and c.get("$ref")
        ]
        if not competition_refs:
            competition_refs = [f"{ESPN_CORE_BASE}/events/{event_id}/competitions/{event_id}"]

        for competition_ref in competition_refs:
            competition_id = ref_id(competition_ref, "competitions") or event_id
            line = fetch_core_odds_by_ids(event_id, competition_id)
            if line:
                print(f"ESPN core odds for {date_str}: {line}")
                return line
        break
    return ""


def enhanced_scoreboard_date(date_str: str) -> dict:
    info = _original_scoreboard_date(date_str)
    if info.get("betting_line"):
        return info
    line = core_date_odds(date_str)
    if line:
        info = dict(info)
        info["betting_line"] = line
    return info


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
calendar.fetch_espn_scoreboard_date = enhanced_scoreboard_date

if __name__ == "__main__":
    calendar.main()
