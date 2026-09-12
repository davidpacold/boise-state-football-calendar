#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://broncosports.com/sports/football/schedule/text"
SCHEDULE_URL = "https://broncosports.com/sports/football/schedule"
ESPN_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/68/schedule"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
OUTPUT_PATH = Path("docs/boise-state-football.ics")
STATE_PATH = Path("state.json")
TIMEZONE = "America/Denver"
TEAM = "Boise State"
ESPN_TEAM_ID = "68"
ESPN_SCOREBOARD_LOOKAHEAD_DAYS = 21
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


@dataclass(frozen=True)
class Game:
    season: int
    date: str
    time: str | None
    site: str
    opponent: str
    location: str
    tournament: str
    result: str
    boise_rank: int | None = None
    opponent_rank: int | None = None
    betting_line: str = ""
    tv_network: str = ""

    @property
    def uid(self) -> str:
        return f"boisestate-football-{self.date}@boise-state-football-calendar"

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def source_url(self) -> str:
        return f"{SOURCE_URL}/{self.season}"


def clean(s: str) -> str:
    return " ".join(s.split()).strip()


def parse_kickoff(time_raw: str) -> str | None:
    if not time_raw or time_raw.upper() in {"TBA", "TBD", "-"}:
        return None
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", time_raw, re.I)
    if not m:
        raise RuntimeError(f"Could not parse kickoff time: {time_raw}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise RuntimeError(f"Could not parse kickoff time: {time_raw}")
    if m.group(3).lower() == "p" and hour != 12:
        hour += 12
    elif m.group(3).lower() == "a" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def fetch_schedule(season: int, *, allow_missing: bool = False) -> list[Game]:
    url = f"{SOURCE_URL}/{season}"
    r = requests.get(url, timeout=30, headers={"User-Agent": "BoiseStateFootballCalendar/1.0"})
    if allow_missing and r.status_code == 404:
        return []
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    m = re.search(r"\b(20\d{2})\s+Football Schedule\b", page_text, re.I)
    if not m:
        if allow_missing:
            return []
        raise RuntimeError(f"Could not determine season for {url}")
    page_season = int(m.group(1))
    if page_season != season:
        raise RuntimeError(f"Requested {season} schedule but Boise State returned {page_season}")
    table = soup.find("table")
    if table is None:
        if allow_missing:
            return []
        raise RuntimeError(f"Could not find schedule table for {season}")
    headers = [clean(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
    hm = {name: i for i, name in enumerate(headers)}
    games: list[Game] = []
    for tr in table.find_all("tr"):
        cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if not cells:
            continue

        def get(name: str, fallback: int) -> str:
            i = hm.get(name, fallback)
            return cells[i] if i < len(cells) else ""

        date_raw = get("date", 0)
        dm = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\b", date_raw)
        if not dm or dm.group(1) not in MONTHS:
            continue
        month = MONTHS[dm.group(1)]
        game_year = season + 1 if month <= 2 else season
        d = datetime(game_year, month, int(dm.group(2)))
        games.append(Game(
            season=season,
            date=d.strftime("%Y-%m-%d"),
            time=parse_kickoff(get("time", 1)),
            site=get("at", 2) or "Neutral",
            opponent=get("opponent", 3),
            location=get("location", 4),
            tournament=get("tournament", 5),
            result=get("result", 6),
        ))
    return sorted(games, key=lambda g: (g.date, g.opponent))


def normalized_opponent(name: str) -> str:
    return clean(re.sub(r"^#\S+\s+", "", name))


def normalize_network(name: str) -> str:
    value = clean(name)
    key = re.sub(r"[^a-z0-9]+", "", value.lower())
    aliases = {
        "usa": "USA Network",
        "usanetwork": "USA Network",
        "cbssportsnetwork": "CBS Sports Network",
        "cbssn": "CBS Sports Network",
        "cbs": "CBS",
        "thecw": "The CW",
        "cw": "The CW",
        "espn": "ESPN",
        "espn2": "ESPN2",
        "espnu": "ESPNU",
        "abc": "ABC",
        "fox": "FOX",
        "fs1": "FS1",
        "fs2": "FS2",
        "peacock": "Peacock",
        "paramount": "Paramount+",
        "paramountplus": "Paramount+",
    }
    return aliases.get(key, "")


def fetch_official_tv_networks(season: int, games: list[Game]) -> dict[str, str]:
    """Read TV networks from Boise State's full schedule page."""
    if not games:
        return {}
    try:
        r = requests.get(
            f"{SCHEDULE_URL}/{season}",
            timeout=30,
            headers={"User-Agent": "BoiseStateFootballCalendar/1.0"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except requests.RequestException as exc:
        print(f"Warning: Boise State TV data unavailable for {season}: {exc}")
        return {}

    opponent_names = {normalized_opponent(g.opponent).lower() for g in games}
    networks: dict[str, str] = {}
    for g in games:
        opponent = normalized_opponent(g.opponent)
        if not opponent:
            continue
        text_nodes = soup.find_all(
            string=lambda value: bool(value) and clean(str(value)).lower() == opponent.lower()
        )
        for text_node in text_nodes:
            found = ""
            seen = 0
            for element in text_node.next_elements:
                seen += 1
                if seen > 300:
                    break
                tag_name = getattr(element, "name", None)
                if tag_name is None:
                    value = clean(str(element)).lower()
                    if value in opponent_names and value != opponent.lower():
                        break
                    continue
                if tag_name == "img":
                    found = normalize_network(str(element.get("alt") or ""))
                if not found:
                    for raw in (element.get("title"), element.get("aria-label")):
                        found = normalize_network(str(raw or ""))
                        if found:
                            break
                if found:
                    break
            if found:
                networks[g.date] = found
                break

    if networks:
        print(f"Boise State TV networks for {season}: {len(networks)}")
    return networks


def parse_rank(competitor: dict) -> int | None:
    value = competitor.get("curatedRank", {}).get("current")
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if 1 <= rank <= 25 else None


def espn_local_date(event: dict) -> str | None:
    raw = event.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(ZoneInfo(TIMEZONE)).date().isoformat()


def score_from_espn(boise: dict, opponent: dict, completed: bool) -> str:
    if not completed:
        return ""
    try:
        boise_score = int(boise.get("score"))
        opponent_score = int(opponent.get("score"))
    except (TypeError, ValueError):
        return ""
    outcome = "W" if boise_score > opponent_score else "L" if boise_score < opponent_score else "T"
    return f"{outcome} {boise_score}-{opponent_score}"


def betting_line_from_competition(competition: dict) -> str:
    odds = competition.get("odds") or []
    if not odds:
        return ""
    return clean(str(odds[0].get("details") or ""))


def tv_network_from_event(event: dict, competition: dict) -> str:
    names: list[str] = []
    for broadcast in competition.get("broadcasts") or event.get("broadcasts") or []:
        for name in broadcast.get("names") or []:
            name = clean(str(name))
            if name and name not in names:
                names.append(name)
    return "/".join(names)


def espn_event_info(event: dict) -> tuple[str | None, dict | None]:
    local_date = espn_local_date(event)
    competitions = event.get("competitions") or []
    if not local_date or not competitions:
        return None, None
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    boise = next((c for c in competitors if str(c.get("team", {}).get("id")) == ESPN_TEAM_ID), None)
    opponent = next((c for c in competitors if str(c.get("team", {}).get("id")) != ESPN_TEAM_ID), None)
    if not boise or not opponent:
        return None, None
    completed = bool((competition.get("status") or event.get("status") or {}).get("type", {}).get("completed"))
    return local_date, {
        "boise_rank": parse_rank(boise),
        "opponent_rank": parse_rank(opponent),
        "betting_line": "" if completed else betting_line_from_competition(competition),
        "tv_network": tv_network_from_event(event, competition),
        "result": score_from_espn(boise, opponent, completed),
    }


def fetch_espn_enrichment(season: int) -> dict[str, dict]:
    try:
        r = requests.get(
            ESPN_SCHEDULE_URL,
            params={"season": season},
            timeout=30,
            headers={"User-Agent": "BoiseStateFootballCalendar/1.0"},
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Warning: ESPN enrichment unavailable for {season}: {exc}")
        return {}
    enriched: dict[str, dict] = {}
    for event in payload.get("events", []):
        local_date, info = espn_event_info(event)
        if local_date and info:
            enriched[local_date] = info
    return enriched


def fetch_espn_scoreboard_date(date_str: str) -> dict:
    try:
        r = requests.get(
            ESPN_SCOREBOARD_URL,
            params={"dates": date_str.replace("-", ""), "groups": 80, "limit": 500},
            timeout=30,
            headers={"User-Agent": "BoiseStateFootballCalendar/1.0"},
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Warning: ESPN scoreboard unavailable for {date_str}: {exc}")
        return {}
    for event in payload.get("events", []):
        local_date, info = espn_event_info(event)
        if local_date == date_str and info:
            return info
    return {}


def merge_espn_info(base: dict, fresh: dict) -> dict:
    if not fresh:
        return base
    merged = dict(base)
    for key in ("boise_rank", "opponent_rank"):
        if fresh.get(key) is not None:
            merged[key] = fresh[key]
    for key in ("betting_line", "tv_network", "result"):
        if fresh.get(key):
            merged[key] = fresh[key]
    return merged


def enrich_games(games: list[Game]) -> list[Game]:
    by_season: dict[int, dict[str, dict]] = {}
    official_tv: dict[int, dict[str, str]] = {}
    games_by_season: dict[int, list[Game]] = {}
    for g in games:
        games_by_season.setdefault(g.season, []).append(g)
    for season in sorted(games_by_season):
        by_season[season] = fetch_espn_enrichment(season)
        official_tv[season] = fetch_official_tv_networks(season, games_by_season[season])

    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    scoreboard_end = today + timedelta(days=ESPN_SCOREBOARD_LOOKAHEAD_DAYS)
    scoreboard_cache: dict[str, dict] = {}
    enriched_games: list[Game] = []
    for g in games:
        info = by_season.get(g.season, {}).get(g.date, {})
        game_date = datetime.strptime(g.date, "%Y-%m-%d").date()
        if today <= game_date <= scoreboard_end:
            if g.date not in scoreboard_cache:
                scoreboard_cache[g.date] = fetch_espn_scoreboard_date(g.date)
            info = merge_espn_info(info, scoreboard_cache[g.date])
        official_result = g.result if g.result and g.result != "-" else ""
        enriched_games.append(replace(
            g,
            result=official_result or info.get("result", ""),
            boise_rank=info.get("boise_rank"),
            opponent_rank=info.get("opponent_rank"),
            betting_line=info.get("betting_line", ""),
            tv_network=official_tv.get(g.season, {}).get(g.date) or info.get("tv_network", ""),
        ))
    return enriched_games


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> list[str]:
    out, cur, n = [], "", 0
    for ch in line:
        b = len(ch.encode())
        if cur and n + b > 73:
            out.append(cur)
            cur, n = " " + ch, 1 + b
        else:
            cur, n = cur + ch, n + b
    out.append(cur)
    return out


def ranked_name(name: str, rank: int | None) -> str:
    if name.lstrip().startswith("#"):
        return name
    return f"#{rank} {name}" if rank else name


def matchup_title(g: Game) -> str:
    boise = ranked_name(TEAM, g.boise_rank)
    opponent = ranked_name(g.opponent, g.opponent_rank)
    return f"{boise} at {opponent}" if g.site.lower() == "away" else f"{boise} vs {opponent}"


def title(g: Game) -> str:
    matchup = matchup_title(g)
    if g.result and g.result != "-":
        outcome = g.result.strip().upper()[:1]
        emoji = "🟢" if outcome == "W" else "🔴" if outcome == "L" else "🏈"
        return f"{emoji} {g.result} · {matchup}"
    parts = [f"🏈 {matchup}"]
    if g.tv_network:
        parts.append(f"📺 {g.tv_network}")
    if g.betting_line:
        parts.append(f"🎲 {g.betting_line}")
    return " · ".join(parts)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"events": {}}


def update_state(games: list[Game]) -> dict:
    old = load_state().get("events", {})
    new = {}
    for g in games:
        prior = old.get(g.uid, {})
        seq = int(prior.get("sequence", 0))
        if prior and prior.get("fingerprint") != g.fingerprint:
            seq += 1
        new[g.uid] = {"fingerprint": g.fingerprint, "sequence": seq}
    state = {"events": new}
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


def render(games: list[Game], state: dict) -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "PRODID:-//Boise State Football Calendar//GitHub//EN",
        "X-WR-CALNAME:Boise State Football", "X-WR-TIMEZONE:America/Denver",
        "REFRESH-INTERVAL;VALUE=DURATION:PT3H", "X-PUBLISHED-TTL:PT3H",
        "BEGIN:VTIMEZONE", "TZID:America/Denver", "X-LIC-LOCATION:America/Denver",
        "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0700", "TZOFFSETTO:-0600", "TZNAME:MDT",
        "DTSTART:20070311T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
        "BEGIN:STANDARD", "TZOFFSETFROM:-0600", "TZOFFSETTO:-0700", "TZNAME:MST",
        "DTSTART:20071104T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
        "END:VTIMEZONE",
    ]
    tz = ZoneInfo(TIMEZONE)
    for g in games:
        d = datetime.strptime(g.date, "%Y-%m-%d")
        desc = []
        if g.time is None:
            desc.append("Kickoff time TBA")
        if g.tournament:
            desc.append(g.tournament)
        if g.result and g.result != "-":
            desc.append(f"Final: {g.result}")
        else:
            if g.boise_rank:
                desc.append(f"Boise State rank: #{g.boise_rank}")
            if g.opponent_rank:
                desc.append(f"Opponent rank: #{g.opponent_rank}")
            if g.tv_network:
                desc.append(f"TV: {g.tv_network}")
            if g.betting_line:
                desc.append(f"Betting line: {g.betting_line}")
        if "championship" in g.opponent.lower():
            desc.append("Appearance is conditional on qualification")
        desc += [f"Season: {g.season}", "Schedule source: Boise State Athletics", g.source_url]
        if g.boise_rank or g.opponent_rank or g.betting_line:
            desc.append("Rankings/odds source: ESPN")
        if g.tv_network:
            desc.append("TV source: Boise State Athletics / ESPN fallback")
        lines += [
            "BEGIN:VEVENT", f"UID:{g.uid}", f"SEQUENCE:{state['events'][g.uid]['sequence']}",
            f"DTSTAMP:{d.strftime('%Y%m%d')}T000000Z", f"SUMMARY:{esc(title(g))}",
        ]
        if g.time is None:
            lines += [
                f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            ]
        else:
            hh, mm = map(int, g.time.split(":"))
            start = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            end = start + timedelta(hours=4)
            lines += [
                f"DTSTART;TZID={TIMEZONE}:{start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={TIMEZONE}:{end.strftime('%Y%m%dT%H%M%S')}",
            ]
        if g.location and g.location.upper() != "TBD":
            lines.append(f"LOCATION:{esc(g.location)}")
        lines += [
            f"DESCRIPTION:{esc(' | '.join(desc))}",
            f"URL:{g.source_url}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in fold(line)) + "\r\n"


def main() -> None:
    current_year = datetime.now(ZoneInfo(TIMEZONE)).year
    seasons = (current_year - 1, current_year, current_year + 1)
    games_by_season: dict[int, list[Game]] = {}
    for season in seasons:
        games_by_season[season] = fetch_schedule(season, allow_missing=(season == current_year + 1))
    games = sorted(
        (game for season_games in games_by_season.values() for game in season_games),
        key=lambda g: (g.date, g.opponent),
    )
    if not games:
        raise RuntimeError(f"No games found for rolling seasons {seasons}")
    games = enrich_games(games)
    state = update_state(games)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(games, state), encoding="utf-8", newline="")
    counts = ", ".join(f"{season}: {len(games_by_season[season])}" for season in seasons)
    print(f"Published {len(games)} games across rolling seasons ({counts})")


if __name__ == "__main__":
    main()
