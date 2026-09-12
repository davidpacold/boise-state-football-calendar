# Boise State Football Calendar

A self-updating iCalendar feed generated from Boise State Athletics' official football schedules.

- Sources: `https://broncosports.com/sports/football/schedule/text/{year}`
- The feed always follows a rolling three-season window: previous year, current year, and next year.
- The year window is calculated automatically at runtime, so no annual code change is required.
- Future seasons include every game Boise State has published so far, even when only part of the schedule is known.
- Boise State publishes listed kickoff times in Mountain Time.
- GitHub Actions checks every three hours.
- TBA games are published as all-day placeholders until kickoff is announced.
- Stable event IDs allow flex/TBA updates to replace existing calendar events instead of duplicating them.

## Subscribe

Use this URL in Apple Calendar's **Add Subscription Calendar** flow:

`https://raw.githubusercontent.com/davidpacold/boise-state-football-calendar/main/docs/boise-state-football.ics`

The feed is regenerated automatically whenever Boise State changes the official schedules.
