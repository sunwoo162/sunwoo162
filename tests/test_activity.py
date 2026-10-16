"""Offline tests for KST bucketing, PR lifecycle deduplication, and missing-data states."""
import datetime as dt
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import update_activity as app


class ActivityTests(unittest.TestCase):
    def test_utc_day_boundary_kst(self):
        self.assertEqual(app.timestamp("2026-10-14T15:00:00Z").date(), dt.date(2026, 10, 15))
        self.assertEqual(app.timestamp("2026-10-15T14:59:59Z").date(), dt.date(2026, 10, 15))
        self.assertEqual(app.timestamp("2026-10-15T15:00:00Z").date(), dt.date(2026, 10, 16))
        self.assertEqual(app.utc_days_for_kst(dt.date(2026, 10, 15)), "2026-10-14..2026-10-15")

    def test_pr_opened_merged_same_date_one_row(self):
        item = {
            "title": "feat: versioned downloads",
            "repository_url": "https://api.github.com/repos/sunwoo162/RD",
            "html_url": "https://github.com/sunwoo162/RD/pull/8",
            "number": 8, "state": "closed",
            "created_at": "2026-10-15T02:00:00Z",
            "closed_at": "2026-10-15T04:00:00Z",
            "pull_request": {"merged_at": "2026-10-15T04:00:00Z"},
        }
        commit = {
            "repository": {"full_name": "sunwoo162/RD", "private": False},
            "sha": "abc123456",
            "html_url": "https://github.com/sunwoo162/RD/commit/abc123456",
            "commit": {"committer": {"date": "2026-10-15T03:00:00Z"}, "message": "fix: something"},
        }
        def fake_search(query, endpoint):
            if endpoint == "commits":
                return [commit], {"limited": False}
            if "type:pr" in query:
                return [item], {"limited": False}
            return [], {"limited": False}
        with patch.object(app, "search", side_effect=fake_search), patch.object(app, "api", return_value={"private": False}):
            rows, coverage = app.day_records(dt.date(2026, 10, 15))
        self.assertEqual(coverage["state"], "indexed")
        self.assertEqual(len(rows), 2)
        pr = next(x for x in rows if x["kind"] == "pr")
        self.assertEqual(set(pr["events"]), {"opened", "merged"})
        self.assertEqual(pr["status"], "merged")
        self.assertEqual(pr["time"], "13:00")

    def test_empty_day_is_checked_not_missing(self):
        with patch.object(app, "search", return_value=([], {"limited": False})):
            rows, coverage = app.day_records(dt.date(2026, 10, 15))
        self.assertEqual(rows, [])
        self.assertEqual(coverage["state"], "indexed")

    def test_search_truncation_is_reported(self):
        responses = [{"total_count": 1500, "incomplete_results": True, "items": []}]
        with patch.object(app, "api", side_effect=responses):
            items, coverage = app.search("test", "commits")
        self.assertEqual(items, [])
        self.assertTrue(coverage["limited"])

    def test_private_repo_is_excluded(self):
        with patch.object(app, "api") as spy:
            self.assertFalse(app.visible_repo("sunwoo162/private", {}, True))
            spy.assert_not_called()

    def test_readme_no_grass(self):
        output = app.readme({}, {"2026-10-16": {"state": "not_collected"}})
        self.assertNotIn("grass.svg", output)
        self.assertIn("View all activity", output)


if __name__ == "__main__":
    unittest.main()
