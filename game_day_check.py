#!/usr/bin/env python3
"""Decide whether the published calendar has a game awaiting a final score."""
from datetime import datetime, timedelta
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def needs_update(text: str, now: datetime) -> bool:
    zone = ZoneInfo("America/Denver")
    now = now.astimezone(zone)
    # Only inspect fields written by this repository; no external ICS inputs.
    unfolded = text.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
    for block in unfolded.split("BEGIN:VEVENT\n")[1:]:
        lines = block.split("END:VEVENT", 1)[0].splitlines()
        if any(line.startswith("DESCRIPTION:") and "Final: " in line for line in lines):
            continue
        start = next((line for line in lines if line.startswith("DTSTART")), "")
        if not start:
            continue
        value = start.split(":", 1)[1]
        if ";VALUE=DATE:" in start:
            # A TBA game may finish late, so include the following morning.
            kickoff = datetime.strptime(value, "%Y%m%d").replace(tzinfo=zone)
            end = kickoff + timedelta(hours=36)
        else:
            kickoff = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone)
            end = kickoff + timedelta(hours=12)
        if kickoff <= now <= end:
            return True
    return False


def main() -> None:
    active = needs_update(Path("docs/boise-state-football.ics").read_text(),
                          datetime.now(ZoneInfo("America/Denver")))
    value = str(active).lower()
    print(f"Game awaiting final result: {value}")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"active={value}\n")


if __name__ == "__main__":
    main()
