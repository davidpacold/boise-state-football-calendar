#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import generate_calendar as calendar

ESPN_CORE_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
ESPN_CORE_ODDS_URL = f"{ESPN_CORE_BASE}/events/{{event_id}}/competitions/{{competition_id}}/odds"
PREFERRED_PROVIDER_IDS = ("37", "41", "58", "68")
AP_POLL_URL = "https://www.collegepollarchive.com/football/ap/seasons.cfm"
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


def core_date_odds(date_str: str) -> str:
    """Use Boise State's core team event feed to find the game and its pregame odds."""
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


def normalize_poll_team(name: str) -> str:
    value = calendar.clean(name)
    value = re.sub(r"\s*\(\d+\)\s*$", "", value)
    aliases = {
        "Miami (FL)": "Miami",
        "Mississippi": "Ole Miss",
    }
    return aliases.get(value, value)


def fetch_ap_rankings() -> dict[str, int]:
    """Scrape the latest AP Top 25 table as a non-blocking rankings fallback."""
    try:
        response = _original_requests_get(
            AP_POLL_URL,
            timeout=20,
            headers={
                "User-Agent": BROWSER_HEADERS["User-Agent"],
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as exc:
        print(f"Warning: AP rankings unavailable: {exc}")
        return {}

    rankings: dict[str, int] = {}
    for row in soup.find_all("tr"):
        cells = [calendar.clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
        if not cells:
            continue
        rank_match = re.fullmatch(r"(\d{1,2})", cells[0])
        if not rank_match:
            continue
        rank = int(rank_match.group(1))
        if not 1 <= rank <= 25:
            continue
        team = ""
        for link in row.find_all("a"):
            text = calendar.clean(link.get_text(" ", strip=True))
            if text and not text.isdigit() and text not in {"<", ">"}:
                team = normalize_poll_team(text)
        if team:
            rankings[team.lower()] = rank

    if rankings:
        print(f"AP rankings loaded: {len(rankings)} teams")
    else:
        print("Warning: AP rankings table parsed no Top 25 teams")
    return rankings


def unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def previous_betting_lines() -> dict[str, str]:
    """Read already-published spreads so they can be frozen at kickoff."""
    if not calendar.OUTPUT_PATH.exists():
        return {}
    try:
        lines = unfold_ics(calendar.OUTPUT_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {}

    found: dict[str, str] = {}
    uid = ""
    for line in lines:
        if line == "BEGIN:VEVENT":
            uid = ""
        elif line.startswith("UID:"):
            uid = line[4:]
        elif uid and line.startswith("DESCRIPTION:"):
            match = re.search(r"(?:^| \| )Betting line: ([^|]+?)(?: \| |$)", line[12:])
            if match:
                found[uid] = calendar.clean(match.group(1))
        elif uid and line.startswith("SUMMARY:") and uid not in found:
            match = re.search(r"🎲\s*([^·]+)$", line[8:])
            if match:
                found[uid] = calendar.clean(match.group(1))
    return found


def game_has_started(game: calendar.Game, now: datetime) -> bool:
    if game.time is None:
        return datetime.strptime(game.date, "%Y-%m-%d").date() < now.date()
    hh, mm = map(int, game.time.split(":"))
    d = datetime.strptime(game.date, "%Y-%m-%d")
    kickoff = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(calendar.TIMEZONE))
    return now >= kickoff


def rank_for(name: str, rankings: dict[str, int]) -> int | None:
    normalized = calendar.normalized_opponent(name)
    aliases = {
        "miami (fl)": "miami",
        "mississippi": "ole miss",
    }
    key = aliases.get(normalized.lower(), normalized.lower())
    return rankings.get(key)


def hardened_enrich_games(games: list[calendar.Game]) -> list[calendar.Game]:
    by_season: dict[int, dict[str, dict]] = {}
    official_tv: dict[int, dict[str, str]] = {}
    games_by_season: dict[int, list[calendar.Game]] = {}
    for game in games:
        games_by_season.setdefault(game.season, []).append(game)

    for season in sorted(games_by_season):
        by_season[season] = calendar.fetch_espn_enrichment(season)
        official_tv[season] = calendar.fetch_official_tv_networks(season, games_by_season[season])

    rankings = fetch_ap_rankings()
    prior_lines = previous_betting_lines()
    now = datetime.now(ZoneInfo(calendar.TIMEZONE))
    scoreboard_end = now.date() + timedelta(days=calendar.ESPN_SCOREBOARD_LOOKAHEAD_DAYS)
    scoreboard_cache: dict[str, dict] = {}
    enriched_games: list[calendar.Game] = []

    for game in games:
        info = dict(by_season.get(game.season, {}).get(game.date, {}))
        game_date = datetime.strptime(game.date, "%Y-%m-%d").date()
        started = game_has_started(game, now)

        if not started and now.date() <= game_date <= scoreboard_end:
            if game.date not in scoreboard_cache:
                fresh = calendar.fetch_espn_scoreboard_date(game.date)
                if not fresh.get("betting_line"):
                    fresh = dict(fresh)
                    line = core_date_odds(game.date)
                    if line:
                        fresh["betting_line"] = line
                scoreboard_cache[game.date] = fresh
            info = calendar.merge_espn_info(info, scoreboard_cache[game.date])

        official_result = game.result if game.result and game.result != "-" else ""
        betting_line = info.get("betting_line", "")
        if started:
            betting_line = prior_lines.get(game.uid, betting_line)

        boise_rank = rank_for(calendar.TEAM, rankings)
        opponent_rank = rank_for(game.opponent, rankings)
        if boise_rank is None:
            boise_rank = info.get("boise_rank")
        if opponent_rank is None:
            opponent_rank = info.get("opponent_rank")

        enriched_games.append(calendar.replace(
            game,
            result=official_result or info.get("result", ""),
            boise_rank=boise_rank,
            opponent_rank=opponent_rank,
            betting_line=betting_line,
            tv_network=official_tv.get(game.season, {}).get(game.date) or info.get("tv_network", ""),
        ))

    return enriched_games


calendar.enrich_games = hardened_enrich_games

if __name__ == "__main__":
    calendar.main()
