# Boise State Football Calendar

A self-updating iCalendar feed generated from Boise State Athletics' official football schedule.

- Source: `https://broncosports.com/sports/football/schedule/text`
- Boise State publishes listed kickoff times in Mountain Time.
- GitHub Actions checks every three hours.
- TBA games are published as all-day placeholders until kickoff is announced.
- Stable event IDs allow flex/TBA updates to replace existing calendar events instead of duplicating them.

## Subscribe

Use this URL in Apple Calendar's **Add Subscription Calendar** flow:

`https://raw.githubusercontent.com/davidpacold/boise-state-football-calendar/main/docs/boise-state-football.ics`

The feed is regenerated automatically whenever Boise State changes the official schedule.
