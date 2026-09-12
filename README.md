# Boise State Football Calendar

A self-updating iCalendar feed generated from Boise State Athletics' official football schedules.

- Sources: `https://broncosports.com/sports/football/schedule/text/{year}`
- The feed always follows a rolling three-season window: previous year, current year, and next year.
- The year window is calculated automatically at runtime, so no annual code change is required.
- Future seasons include every game Boise State has published so far, even when only part of the schedule is known.
- Boise State publishes listed kickoff times in Mountain Time.
- Completed games update their calendar titles with the final W/L score.
- Upcoming games are enriched with available Top 25 rankings and betting lines from ESPN.
- Rankings and betting lines are supplemental; if ESPN does not publish them yet or is temporarily unavailable, the official Boise State schedule still publishes normally.
- GitHub Actions checks every three hours.
- TBA games are published as all-day placeholders until kickoff is announced.
- Stable event IDs allow schedule, ranking, odds, and result updates to replace existing calendar events instead of duplicating them.

## Subscribe

GitHub Pages:

`https://davidpacold.github.io/boise-state-football-calendar/boise-state-football.ics`

Raw GitHub fallback:

`https://raw.githubusercontent.com/davidpacold/boise-state-football-calendar/main/docs/boise-state-football.ics`

The feed is regenerated automatically as schedule details, results, rankings, and available betting lines change.
