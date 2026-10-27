from pathlib import Path

from scripts import build_bluff_inference
from website.api import bluffs, publisher


ROOT = Path(__file__).resolve().parents[2]


def test_s22_bluff_fingerprints_match_the_published_terminal_projection():
    payload, _, _ = build_bluff_inference.build()
    records = {row["game_id"]: row for row in payload["games"]}
    entries, _, _ = publisher.load_publication(ROOT, "S22")
    for item in entries:
        identities = {seat["name"]: seat["name"] for seat in item["dossier"]["seats"]}
        game = publisher._public_game(item["dossier"], item["voting"], item["endgame"],
                                     item["audit"], item["board"], identities)
        assert records[game["id"]]["source_fingerprint"] == bluffs.source_fingerprint(game), game["id"]
