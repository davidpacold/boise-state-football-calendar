import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icalendar import Calendar

import add_structured_locations as locations
import generate_calendar as generator


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.game = generator.Game(2026, "2026-11-21", "19:30", "H",
                                   "San Diego State", "Boise, Idaho (Albertsons Stadium)", "", "")
        self.state = {"events": {self.game.uid: {
            "fingerprint": self.game.fingerprint, "sequence": 4}}}

    def render(self, venues=None):
        return locations.enrich_calendar(generator.render([self.game], self.state),
                                         venues or {}, self.state)

    def test_home_location_parses_as_one_address_and_matches_title(self):
        text = self.render()
        event = Calendar.from_ical(text).walk("VEVENT")[0]
        venue = locations.ALBERTSONS
        structured = event["X-APPLE-STRUCTURED-LOCATION"]
        self.assertEqual(structured.params["X-ADDRESS"], venue["address"])
        self.assertEqual(structured.params["X-TITLE"], venue["title"])
        self.assertEqual(str(event["LOCATION"]), venue["title"] + "\n" + venue["address"])
        self.assertEqual(str(structured), "geo:43.602800,-116.195800")
        self.assertEqual(event["GEO"].to_ical(), "43.6028;-116.1958")
        self.assertEqual(int(event["SEQUENCE"]), 5)
        self.assertIn("LAST-MODIFIED", event)
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))

    def test_repeated_generation_preserves_location_state_and_sequence(self):
        first = self.render()
        self.assertEqual(locations.enrich_calendar(first, {}, self.state), first)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(self.state))
            with patch.object(generator, "STATE_PATH", path):
                self.state = generator.update_state([self.game])
        self.assertEqual(self.render(), first)

    def test_away_and_changed_coordinates_update_once(self):
        self.game = generator.replace(self.game, location="Fort Collins, Colo.")
        first = self.render()
        venue = copy.deepcopy(locations.VENUE_BY_LOCATION["Fort Collins, Colo."])
        venue["latitude"] += 0.001
        second = self.render({self.game.date: venue})
        self.assertNotEqual(first, second)
        event = Calendar.from_ical(second).walk("VEVENT")[0]
        self.assertEqual(int(event["SEQUENCE"]), 6)
        self.assertEqual(self.render({self.game.date: venue}), second)

    def test_unknown_location_stays_text_without_invented_coordinates(self):
        self.game = generator.replace(self.game, location="TBD")
        event = Calendar.from_ical(self.render()).walk("VEVENT")[0]
        self.assertNotIn("LOCATION", event)
        self.assertNotIn("X-APPLE-STRUCTURED-LOCATION", event)
        self.assertEqual(int(event["SEQUENCE"]), 4)

    def test_parameter_punctuation_and_unicode_round_trip(self):
        venue = dict(locations.ALBERTSONS, title='Stade "A"; Gate: ^',
                     address="1 Rue du Caf\u00e9, Paris; France")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT",
                 *locations.location_lines(venue), "END:VEVENT", "END:VCALENDAR"]
        text = "\r\n".join(part for line in lines for part in locations.fold(line)) + "\r\n"
        event = Calendar.from_ical(text).walk("VEVENT")[0]
        params = event["X-APPLE-STRUCTURED-LOCATION"].params
        self.assertEqual(params["X-TITLE"], venue["title"])
        self.assertEqual(params["X-ADDRESS"], venue["address"])


if __name__ == "__main__":
    unittest.main()
