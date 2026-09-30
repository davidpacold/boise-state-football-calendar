import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from icalendar import Calendar

import game_day_check
import generate_calendar as calendar
import generate_with_odds as odds


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.game = calendar.Game(2026, "2026-10-03", "20:30", "H", "Opponent",
                                  "Boise, Idaho (Albertsons Stadium)", "", "",
                                  betting_line="BOIS -7.5")
        self.state = {"events": {self.game.uid: {"sequence": 3}}}

    def text(self, game=None):
        return calendar.render([game or self.game], self.state)

    def now(self, raw):
        return datetime.fromisoformat(raw).replace(tzinfo=ZoneInfo(calendar.TIMEZONE))

    def test_gate_checks_game_and_overnight_until_final(self):
        text = self.text()
        self.assertFalse(game_day_check.needs_update(text, self.now("2026-10-03T20:29")))
        self.assertTrue(game_day_check.needs_update(text, self.now("2026-10-03T20:30")))
        self.assertTrue(game_day_check.needs_update(text, self.now("2026-10-04T02:30")))
        self.assertFalse(game_day_check.needs_update(text, self.now("2026-10-04T09:00")))
        final = self.text(calendar.replace(self.game, result="W 35-17"))
        self.assertFalse(game_day_check.needs_update(final, self.now("2026-10-04T02:30")))

    def test_gate_tba_and_unrelated_dates(self):
        text = self.text(calendar.replace(self.game, time=None))
        self.assertTrue(game_day_check.needs_update(text, self.now("2026-10-04T09:00")))
        self.assertFalse(game_day_check.needs_update(text, self.now("2026-10-05T09:00")))
        self.assertFalse(game_day_check.needs_update(text, self.now("2026-10-02T09:00")))

    def enrich(self, now, fresh, prior=None):
        with (patch.object(odds, "datetime") as clock,
              patch.object(calendar, "fetch_espn_enrichment", return_value={}),
              patch.object(calendar, "fetch_official_tv_networks", return_value={}),
              patch.object(odds, "fetch_ap_rankings", return_value={}),
              patch.object(odds, "previous_betting_lines", return_value={self.game.uid: "BOIS -7.5"}),
              patch.object(odds, "previous_final_results", return_value=prior or {}),
              patch.object(calendar, "fetch_espn_scoreboard_date", return_value=fresh) as scoreboard,
              patch.object(odds, "core_date_odds") as betting,
              patch.object(odds, "core_date_result", return_value="") as core):
            clock.now.return_value = self.now(now)
            clock.strptime.side_effect = datetime.strptime
            clock.side_effect = datetime
            game = odds.hardened_enrich_games([self.game])[0]
            scoreboard.assert_called_once_with(self.game.date)
            betting.assert_not_called()
            return game, core.call_count

    def test_scoreboard_final_after_midnight_keeps_pregame_line(self):
        game, _ = self.enrich("2026-10-04T01:00", {"result": "W 35-17", "betting_line": "BOIS -10"})
        self.assertEqual(game.result, "W 35-17")
        self.assertEqual(game.betting_line, "BOIS -7.5")
        event = Calendar.from_ical(self.text(game)).walk("VEVENT")[0]
        self.assertEqual(str(event["UID"]), self.game.uid)
        self.assertIn("W 35-17", str(event["SUMMARY"]))
        self.assertIn("Final: W 35-17", str(event["DESCRIPTION"]))

    def test_no_final_from_in_progress_score(self):
        self.assertEqual(calendar.score_from_espn({"score": "21"}, {"score": "17"}, False), "")
        game, core_calls = self.enrich("2026-10-03T21:30", {})
        self.assertEqual(game.result, "")
        self.assertEqual(core_calls, 1)

    def test_published_final_survives_source_outage(self):
        game, core_calls = self.enrich("2026-10-04T01:00", {}, {self.game.uid: "W 35-17"})
        self.assertEqual(game.result, "W 35-17")
        self.assertEqual(core_calls, 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.ics"
            path.write_text(self.text(game))
            with patch.object(calendar, "OUTPUT_PATH", path):
                self.assertEqual(odds.previous_final_results(), {self.game.uid: "W 35-17"})

    def test_core_final_with_referenced_status_and_scores(self):
        listing = {"items": [{"$ref": "https://test/event"}]}
        event = {"date": "2026-10-04T02:30Z", "competitions": [{"$ref": "https://test/competition"}]}
        competition = {"status": {"$ref": "https://test/status"}, "competitors": [
            {"id": "68", "score": {"$ref": "https://test/boise"}},
            {"id": "99", "score": {"$ref": "https://test/opponent"}}]}
        replies = [listing, event, competition, {"type": {"completed": True}},
                   {"value": 35}, {"value": 17}]
        with patch.object(odds, "espn_get", side_effect=[Mock(json=Mock(return_value=p)) for p in replies]):
            self.assertEqual(odds.core_date_result(self.game.date), "W 35-17")

    def test_core_in_progress_does_not_fetch_or_publish_scores(self):
        replies = [
            {"items": [{"date": "2026-10-04T02:30Z", "competitions": [
                {"status": {"type": {"completed": False}}, "competitors": [
                    {"id": "68", "score": {"$ref": "https://test/score"}}]}]}]},
        ]
        with patch.object(odds, "espn_get", side_effect=[Mock(json=Mock(return_value=p)) for p in replies]) as get:
            self.assertEqual(odds.core_date_result(self.game.date), "")
            self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
