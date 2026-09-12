#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://broncosports.com/sports/football/schedule/text"
OUTPUT_PATH = Path("docs/boise-state-football.ics")
STATE_PATH = Path("state.json")
TIMEZONE = "America/Denver"
TEAM = "Boise State"
MONTHS = {m: i for i, m in enumerate(("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"), 1)}

@dataclass(frozen=True)
class Game:
    date: str
    time: str | None
    site: str
    opponent: str
    location: str
    tournament: str
    result: str

    @property
    def uid(self) -> str:
        return f"boisestate-football-{self.date}@boise-state-football-calendar"

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def clean(s: str) -> str:
    return " ".join(s.split()).strip()


def fetch_schedule() -> tuple[int, list[Game]]:
    r = requests.get(SOURCE_URL, timeout=30, headers={"User-Agent": "BoiseStateFootballCalendar/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    m = re.search(r"\b(20\d{2})\s+Football Schedule\b", page_text, re.I)
    if not m:
        raise RuntimeError("Could not determine season")
    season = int(m.group(1))
    table = soup.find("table")
    if table is None:
        raise RuntimeError("Could not find schedule table")

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
        d = datetime(season, MONTHS[dm.group(1)], int(dm.group(2)))

        time_raw = get("time", 1)
        t = None
        if time_raw and time_raw.upper() not in {"TBA", "TBD", "-"}:
            normalized = clean(time_raw.lower().replace("a.m.", "am").replace("p.m.", "pm"))
            for fmt in ("%I:%M %p", "%I %p"):
                try:
                    t = datetime.strptime(normalized.upper(), fmt).strftime("%H:%M")
                    break
                except ValueError:
                    pass
            if t is None:
                raise RuntimeError(f"Could not parse kickoff time: {time_raw}")

        games.append(Game(
            date=d.strftime("%Y-%m-%d"),
            time=t,
            site=get("at", 2) or "Neutral",
            opponent=get("opponent", 3),
            location=get("location", 4),
            tournament=get("tournament", 5),
            result=get("result", 6),
        ))

    if len(games) < 8:
        raise RuntimeError(f"Parsed only {len(games)} games; refusing to publish")
    return season, sorted(games, key=lambda g: g.date)


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


def title(g: Game) -> str:
    return f"{TEAM} at {g.opponent}" if g.site.lower() == "away" else f"{TEAM} vs {g.opponent}"


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


def render(season: int, games: list[Game], state: dict) -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "PRODID:-//Boise State Football Calendar//GitHub//EN",
        f"X-WR-CALNAME:Boise State Football {season}",
        "X-WR-TIMEZONE:America/Denver",
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
        if g.time is None: desc.append("Kickoff time TBA")
        if g.tournament: desc.append(g.tournament)
        if g.result and g.result != "-": desc.append(f"Result: {g.result}")
        if "championship" in g.opponent.lower(): desc.append("Appearance is conditional on qualification")
        desc += ["Source: Boise State Athletics", SOURCE_URL]
        lines += [
            "BEGIN:VEVENT", f"UID:{g.uid}", f"SEQUENCE:{state['events'][g.uid]['sequence']}",
            f"DTSTAMP:{d.strftime('%Y%m%d')}T000000Z", f"SUMMARY:{esc(title(g))}",
        ]
        if g.time is None:
            lines += [f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(d+timedelta(days=1)).strftime('%Y%m%d')}"]
        else:
            hh, mm = map(int, g.time.split(":"))
            start = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            end = start + timedelta(hours=4)
            lines += [f"DTSTART;TZID={TIMEZONE}:{start.strftime('%Y%m%dT%H%M%S')}", f"DTEND;TZID={TIMEZONE}:{end.strftime('%Y%m%dT%H%M%S')}"]
        if g.location and g.location.upper() != "TBD":
            lines.append(f"LOCATION:{esc(g.location)}")
        lines += [f"DESCRIPTION:{esc(' | '.join(desc))}", f"URL:{SOURCE_URL}", "TRANSP:TRANSPARENT", "END:VEVENT"]

    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in fold(line)) + "\r\n"


def main() -> None:
    season, games = fetch_schedule()
    state = update_state(games)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(season, games, state), encoding="utf-8", newline="")
    print(f"Published {len(games)} games for {season}")

if __name__ == "__main__":
    main()
