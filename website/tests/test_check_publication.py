import pytest

from website.api.app import GameDetail
from website.check_publication import projection, require_match


def test_snapshot_bindings_are_not_part_of_the_public_response_comparison():
    public = GameDetail(
        id="fixture", season="S21", date="2026-03-24", phase="regular", game_number=1,
        board={"code": "mixed_blood", "name": "预女猎白混"}, winner="good",
        players=[], ballot_count=0, round_count=0, release_id="fixture-release",
        commentators=[], referee=None, seats=[], rounds=[], voting={}, endgame={},
        source={"bvid": "BVfixture"}, data_notes=[],
    ).model_dump()
    snapshot = {**public, "bluff_evidence_sources": {"a" * 64: "b" * 64},
                "bluff_source_binding": {"source_fingerprint": "c" * 64}}
    response = GameDetail.model_validate(snapshot).model_dump()
    require_match(projection(snapshot), projection(response), "public detail")
    with pytest.raises(RuntimeError, match="winner"):
        require_match(projection(snapshot), projection({**response, "winner": "werewolf"}), "public detail")
