import argparse
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from website import check_publication as publication


class PublicationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id": "bili-BV1AAAAA-p01-g01", "season": "S01", "ballot_count": 0,
             "round_count": 0,
             "players": [{"id": "person-1", "name": "甲", "seat": 1}]},
            {"id": "bili-BV2BBBBB-p01-g01", "season": "S02", "ballot_count": 0,
             "round_count": 0,
             "players": [{"id": "person-2", "name": "乙", "seat": 1}]},
        ]
        self.details = {
            item["id"]: {
                "id": item["id"], "season": item["season"], "release_id": "release-1",
                "players": item["players"], "seats": [{"seat": item["players"][0]["seat"],
                                                          "person_id": item["players"][0]["id"],
                                                          "name": item["players"][0]["name"]}],
                "rounds": [], "voting": {"ballots": []}, "round_count": 0, "ballot_count": 0,
                "presentation": {}, "analytics_version": 1,
            }
            for item in self.items
        }
        self.overview = {
            "release": {"id": "release-1", "game_count": 2, "source_hash": "source"},
            "totals": {"games": 2, "ballots": 0, "votes": 0},
            "seasons": [{"id": "S01", "games": 1}, {"id": "S02", "games": 1}],
        }

    def run_mocked(self, args):
        def get_json(path):
            if path == "/api/v1/overview":
                return self.overview
            season = "S01" if "season=S01" in path else "S02"
            return {"release_id": "release-1", "season": season, "game_count": 1, "items": []}

        with (
            patch.object(publication, "season_codes", return_value=["S01", "S02"]),
            patch.object(publication, "get_json", side_effect=get_json),
            patch.object(publication, "all_api_games", return_value=(self.items, "release-1")),
            patch.object(publication, "load_source", return_value=({}, {}, "source", "rules")) as load_source,
            patch.object(publication, "game_details", side_effect=lambda items: {
                item["id"]: self.details[item["id"]] for item in items
            }) as game_details,
            patch.object(publication, "check_release", return_value={
                "release_id": "release-1", "overview_seasons": self.overview["seasons"],
            }) as check_release,
            patch.object(publication, "check_affected_players", return_value=({}, [])),
            patch.object(publication, "check_stats", return_value={}),
            patch.object(publication, "check_bluffs", return_value={}),
            patch.object(publication, "check_photos", return_value={}),
        ):
            report = publication.run(args)
        return report, load_source, game_details, check_release

    def args(self, **changes):
        values = {"seasons": None, "bvid": None, "baseline": None, "api_only": True,
                  "browser_channel": "chromium", "screenshots": None}
        values.update(changes)
        return argparse.Namespace(**values)

    def test_season_filter_limits_details_and_reports_partial_acceptance(self):
        report, load_source, game_details, check_release = self.run_mocked(self.args(seasons=["S02"]))

        self.assertEqual(load_source.call_args.args, (["S02"], None))
        self.assertEqual([item["id"] for item in game_details.call_args.args[0]], [self.items[1]["id"]])
        self.assertFalse(check_release.call_args.kwargs["full_mode"])
        self.assertEqual(report["mode"], "partial")
        self.assertFalse(report["complete_release_accepted"])
        self.assertFalse(report["acceptance_scope"]["release_vote_total_checked"])
        self.assertEqual(report["requests"]["detail_requests"], 1)
        self.assertEqual(report["requests"]["accepted_games"], 1)
        self.assertGreaterEqual(report["timing_seconds"]["total_seconds"], 0)

    def test_bvid_limits_source_and_detail_scope_to_the_changed_game(self):
        report, load_source, game_details, check_release = self.run_mocked(self.args(bvid=["BV2BBBBB"]))

        self.assertEqual(load_source.call_args.args, (["S02"], {"S02": ["BV2BBBBB"]}))
        self.assertEqual([item["id"] for item in game_details.call_args.args[0]], [self.items[1]["id"]])
        self.assertEqual(check_release.call_args.kwargs["requested_ids"], {self.items[1]["id"]})
        self.assertEqual(report["source"]["scope"], "target_and_affected_player_games")
        self.assertEqual(report["mode"], "partial")

    def test_full_scope_remains_full_without_bvid(self):
        report, _, game_details, check_release = self.run_mocked(self.args())

        self.assertEqual(len(game_details.call_args.args[0]), 2)
        self.assertTrue(check_release.call_args.kwargs["full_mode"])
        self.assertEqual(report["mode"], "full")
        self.assertTrue(report["complete_release_accepted"])

    def test_partial_release_check_uses_global_summary_and_scoped_details(self):
        selected = self.details[self.items[1]["id"]]
        expected = {**selected, "players": [{key: value for key, value in selected["players"][0].items()
                                               if key != "id"}],
                    "seats": [{key: value for key, value in selected["seats"][0].items()
                               if key != "person_id"}]}
        result = publication.check_release(
            {**self.overview, "totals": {**self.overview["totals"], "votes": 900}},
            self.items, [self.items[1]], {selected["id"]: selected}, "release-1",
            ["S01", "S02"], ["S02"], {selected["id"]: expected},
            {"S02": publication.counts([selected])}, "partial-source", "rules",
            full_mode=False, requested_ids={selected["id"]},
        )

        self.assertEqual(result["paginated_games"], 2)
        self.assertEqual(result["details_checked"], 1)
        self.assertEqual(result["source_games_matched"], 1)

    def test_bvid_must_resolve_to_one_game(self):
        duplicate = {**self.items[1], "id": "another-BV2BBBBB-game"}
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            publication.select_bvid_items([self.items[1], duplicate], ["BV2BBBBB"])

    def test_partial_cli_preserves_the_full_acceptance_report(self):
        from tempfile import TemporaryDirectory
        import json
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as directory:
            root = Path(directory)
            full = root / 'website/artifacts/publication-acceptance.json'
            full.parent.mkdir(parents=True)
            full.write_text('full acceptance', encoding='utf-8')
            report = {'state': 'passed', 'mode': 'partial',
                      'api': {'release_id': 'release-1', 'paginated_games': 2, 'source_games_matched': 1},
                      'requests': {'accepted_games': 1, 'detail_requests': 1},
                      'timing_seconds': {'total_seconds': 0.1}, 'browser': {'skipped': True}}
            with patch.object(publication, 'ROOT', root), patch.object(publication, 'run', return_value=report):
                self.assertEqual(publication.main(['--bvid', 'BVfixture', '--api-only']), 0)
            self.assertEqual(full.read_text(encoding='utf-8'), 'full acceptance')
            partial = json.loads((full.parent / 'publication-acceptance-partial.json').read_text(encoding='utf-8'))
            self.assertEqual(partial['mode'], 'partial')

    def test_bvid_source_scope_includes_only_direct_player_games(self):
        related = {"id": "bili-BV3CCCCC-p01-g01", "season": "S02",
                   "players": [{"id": "person-2", "name": "乙", "seat": 4}]}

        bvids = publication.affected_player_source_bvids(
            [*self.items, related], [self.items[1]],
        )

        self.assertEqual(bvids, {"S02": ["BV2BBBBB", "BV3CCCCC"]})

    def test_bvid_source_loader_uses_publisher_single_game_sample(self):
        entry = {"dossier": {"seats": [{"name": "乙"}]}, "voting": {}, "endgame": {},
                 "audit": None, "board": {}, "source_voting": {}, "derivations": None}
        game = {"id": self.items[1]["id"], "season": "S02", "seats": [{"seat": 1}],
                "rounds": [], "voting": {"ballots": []}}
        with (
            patch.object(publication.publisher, "load_release", return_value=([entry], "one-game", "rules"))
            as load_release,
            patch.object(publication.publisher, "_public_game", return_value=game),
            patch.object(publication, "_resolved_snapshot", side_effect=lambda snapshot: snapshot),
        ):
            games, season_counts, source_hash, rules_hash = publication.load_source(
                ["S02"], {"S02": ["BV2BBBBB"]},
            )

        self.assertEqual(load_release.call_args.args[1], ["S02"])
        self.assertEqual(load_release.call_args.kwargs["sample"], "BV2BBBBB")
        self.assertEqual(list(games), [self.items[1]["id"]])
        self.assertEqual(season_counts["S02"]["games"], 1)
        self.assertEqual(source_hash, publication.hashlib.sha256(b"one-game").hexdigest())
        self.assertTrue(rules_hash)

    def test_affected_player_stats_are_checked_against_active_game_summaries(self):
        item = self.items[1]
        player = item["players"][0]
        actual = {
            "release_id": "release-1", "name": player["name"], "appearances": 1,
            "stats": {"appearances": 1, "attendance": {"numerator": 1, "denominator": 1, "rate": 1.0},
                      "scope_games": 1}, "scope": {"seasons": ["S02"], "games": 1},
            "available_seasons": ["S01", "S02"], "games": [item],
        }
        stat_keys = (
            "appearances", "wins", "losses", "pending_games", "points", "points_complete",
            "total_win_rate", "werewolf_win_rate", "good_win_rate", "sheriff_registration_rate",
            "seer_follow_rate", "sheriff_seer_vote_rate", "wolf_vote_rate", "exile_abstentions",
            "werewolf_appearances", "werewolf_draw_rate", "werewolf_self_explosion_rate",
            "werewolf_sheriff_registration_rate", "roles", "boards", "ledger",
        )
        expected_stats = {key: [] if key in {"roles", "boards", "ledger"} else None for key in stat_keys}
        expected_stats.update({"appearances": 1, "wins": 1, "points": 1.0})
        actual["stats"].update(expected_stats)
        with (patch.object(publication, "get_json", return_value=actual) as get_json,
              patch.object(publication, "compute_player_stats", return_value=expected_stats)):
            checked, pages = publication.check_affected_players(
                self.items, {item["id"]: self.details[item["id"]]},
                {item["id"]: self.details[item["id"]]}, ["S01", "S02"], "release-1",
            )

        self.assertIn("S02:person-2", checked)
        self.assertEqual(pages, [("person-2", "S02")])
        self.assertIn("/api/v1/players/person-2?season_start=S02&season_end=S02", get_json.call_args.args[0])

        stale_source = {**self.details[item['id']], 'seats': [
            {**self.details[item['id']]['seats'][0], 'name': '另一位选手'}]}
        with (patch.object(publication, 'get_json', return_value=actual),
              patch.object(publication, 'compute_player_stats', return_value=expected_stats)):
            with self.assertRaisesRegex(RuntimeError, 'player identity differs'):
                publication.check_affected_players(
                    self.items, {item['id']: self.details[item['id']]},
                    {item['id']: stale_source}, ['S01', 'S02'], 'release-1')


if __name__ == "__main__":
    unittest.main()
