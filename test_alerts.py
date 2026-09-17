import unittest
from datetime import timedelta

from icalendar import Calendar

import add_structured_locations as locations
import generate_calendar as generator


class AlertTests(unittest.TestCase):
    def event(self, time):
        game = generator.Game(2026, "2026-11-21", time, "H", "San Diego State",
                              "Boise, Idaho (Albertsons Stadium)", "", "")
        state = {"events": {game.uid: {"sequence": 1}}}
        text = locations.enrich_calendar(generator.render([game], state), {}, state)
        return Calendar.from_ical(text).walk("VEVENT")[0]

    def test_timed_game_has_one_alert_before_kickoff_and_no_travel_advisory(self):
        event = self.event("19:30")
        alarms = event.walk("VALARM")
        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0]["ACTION"], "DISPLAY")
        self.assertEqual(alarms[0]["TRIGGER"].dt, timedelta(minutes=-30))
        self.assertEqual(alarms[0]["TRIGGER"].params["RELATED"], "START")
        self.assertEqual(event["X-APPLE-TRAVEL-ADVISORY-BEHAVIOR"], "DISABLED")

    def test_tba_game_has_no_midnight_or_travel_alert(self):
        event = self.event(None)
        self.assertEqual(event.walk("VALARM"), [])
        self.assertEqual(event["X-APPLE-TRAVEL-ADVISORY-BEHAVIOR"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
