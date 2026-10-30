import hashlib
import json
from pathlib import Path
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_manual_slot_review as manual


def _dump(path: Path, value) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _fixture(root: Path, *, review_id="DN-fixture", bvid="BVfixture", number=1,
             slot="mechanical_action", action="guard", targets=None, result=None,
             note="", raw_slots=True, board="s21_mechanical_wolf_seer",
             typed_action="unknown", terminal_round=None) -> tuple[dict, dict, Path]:
    roles = ["平民"] * 12
    roles[6], roles[8] = ("通灵师" if board == "s21_mechanical_wolf_seer" else "平民"), "机械狼"
    roles[11] = "平民" if board == "s21_mechanical_wolf_seer" else "预言家"
    seats = [{"seat": n, "name": f"玩家{n}", "role": roles[n - 1]} for n in range(1, 13)]
    before = {"action": "unknown", "actor": None, "targets": [], "result": None}
    changes = {"action": action}
    if targets is not None:
        changes["targets"] = targets
    if result is not None:
        changes["result"] = result
    question = {"id": review_id, "round": number, "phase": "night",
                "slots": [{"code": slot, "before": before}]}
    game_id = f"bili-{bvid}-p01-cid123"
    rounds = [{"number": n, "night": [], "day": []} for n in range(1, number + 1)]
    typed_event = {"slot": slot, **before, "action": typed_action}
    rounds[number - 1]["night"] = [typed_event]
    if review_id == "DN-084":
        rounds[0]["night"] = [{"slot": slot, "action": "learn", "actor": 9,
                               "targets": [10], "result": "mechanical_guard"}]
    dossier = {"slug": game_id, "board": board, "seats": seats, "rounds": rounds}
    dossier_rel = Path("data/games/S21") / bvid / "dossier.json"
    dossier_path = root / dossier_rel
    dossier_sha = hashlib.sha256(_dump(dossier_path, dossier)).hexdigest()
    review = {"id": review_id, "round": number, "phase": "night", "note": note,
              "slots": ([{"slot": slot, "before": before, "changes": changes}] if raw_slots else [])}
    source_game = {"bvid": bvid, "id": game_id, "season": "S21", "date": "2026-03-03",
                   "game_number": 1, "dossier_sha256": dossier_sha, "seats": seats,
                   "reviews": [review]}
    page_game = {key: source_game[key] for key in
                 ("bvid", "id", "season", "date", "game_number", "dossier_sha256", "seats")}
    page_game["questions"] = [question]
    payload = {"format": manual.FORMAT, "games": [page_game]}
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    page = {**payload, "source_fingerprint": fingerprint}
    page_path = root / manual.PAGE
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text('<script id="review-data" type="application/json">'
                         + json.dumps(page, ensure_ascii=False, separators=(",", ":"))
                         + "</script>", encoding="utf-8")
    source = {"format": manual.FORMAT, "source_fingerprint": fingerprint,
              "exported_at": "2026-10-30T00:00:00Z", "games": [source_game]}
    _dump(root / manual.INPUT, source)
    terminal = ({"round": terminal_round if terminal_round is not None else number, "phase": "night"}
                if review_id in manual.TERMINAL_BEFORE_ACTION else None)
    _dump(dossier_path.parent / "rule_derivations.json", {"terminal": terminal})
    return source, dossier, root / manual.INPUT


def test_normal_review_uses_input_changes_and_page_bound_actor():
    with tempfile.TemporaryDirectory(prefix=".manual-slot-normal-", dir=ROOT) as temporary:
        root = Path(temporary)
        _fixture(root, slot="seer_check", action="check", targets=[9], result="狼人",
                 board="s21_masquerade")

        plan, _, _ = manual.build_plan(root=root)
        review = plan[0]["sidecar"]["reviews"][0]

        assert review["classification"] == "confirmed"
        assert review["typed"] == {"action": "check", "actor": 12, "targets": [9], "result": "werewolf"}
        assert review["note"] == ""
        assert review["raw_review"]["slots"][0]["changes"]["result"] == "狼人"


def test_changed_before_is_rejected_against_page_and_typed_dossier():
    with tempfile.TemporaryDirectory(prefix=".manual-slot-before-", dir=ROOT) as temporary:
        root = Path(temporary)
        _, _, input_path = _fixture(root)
        source = json.loads(input_path.read_text(encoding="utf-8"))
        source["games"][0]["reviews"][0]["slots"][0]["before"]["action"] = "pass"
        _dump(input_path, source)

        with pytest.raises(manual.ReviewError, match="slot/before与原人工复核页不匹配"):
            manual.build_plan(root=root)


def test_page_before_is_rejected_when_current_typed_slot_differs():
    with tempfile.TemporaryDirectory(prefix=".manual-slot-typed-before-", dir=ROOT) as temporary:
        root = Path(temporary)
        _fixture(root, typed_action="pass")

        with pytest.raises(manual.ReviewError, match="before与当前typed值不匹配"):
            manual.build_plan(root=root)


def test_stale_typed_dossier_hash_is_rejected_for_a_new_application():
    with tempfile.TemporaryDirectory(prefix=".manual-slot-stale-", dir=ROOT) as temporary:
        root = Path(temporary)
        source, _, _ = _fixture(root)
        dossier_path, _ = manual._current_dossier(root, source["games"][0]["id"])
        dossier_path.write_bytes(dossier_path.read_bytes() + b" ")

        with pytest.raises(manual.ReviewError, match="dossier_sha256与当前typed档案不匹配"):
            manual.build_plan(root=root)


def test_terminal_classification_is_bound_to_raw_sha_and_terminal_round(monkeypatch):
    with tempfile.TemporaryDirectory(prefix=".manual-slot-terminal-", dir=ROOT) as temporary:
        root = Path(temporary)
        source, _, input_path = _fixture(root, review_id="DN-087", bvid="BV1UMPqzjEvH",
                                          number=4, slot="seer_check", action="pass",
                                          note="这一夜机械狼带刀，游戏结束，没有查验环节了",
                                          raw_slots=False)
        raw = input_path.read_bytes()
        monkeypatch.setattr(manual, "AUTHORIZED_RAW_SHA256", hashlib.sha256(raw).hexdigest())
        plan, _, _ = manual.build_plan(root=root)
        review = plan[0]["sidecar"]["reviews"][0]
        assert review["classification"] == "game_ended_before_action"
        assert review["typed"] == {"action": "unavailable", "actor": 7, "targets": [], "result": None}
        assert review["raw_review"]["slots"] == []
        assert review["note"] == source["games"][0]["reviews"][0]["note"]

        monkeypatch.setattr(manual, "AUTHORIZED_RAW_SHA256", "0" * 64)
        with pytest.raises(manual.ReviewError, match="特例仅适用于已授权的原始JSON SHA"):
            manual.build_plan(root=root)

        monkeypatch.setattr(manual, "AUTHORIZED_RAW_SHA256", hashlib.sha256(raw).hexdigest())
        _dump(root / "data/games/S21" / source["games"][0]["bvid"] / "rule_derivations.json",
              {"terminal": {"round": 3, "phase": "night"}})
        with pytest.raises(manual.ReviewError, match="terminal不同轮"):
            manual.build_plan(root=root)


def test_reapplying_same_raw_hash_survives_page_and_dossier_rebuild():
    with tempfile.TemporaryDirectory(prefix=".manual-slot-replay-", dir=ROOT) as temporary:
        root = Path(temporary)
        source, _, input_path = _fixture(root)
        plan, summary, raw = manual.build_plan(root=root)
        manual.apply_plan(plan, summary, raw, root=root)
        saved_sidecar = (root / plan[0]["sidecar_path"]).read_bytes()
        dossier_path, _ = manual._current_dossier(root, source["games"][0]["id"])
        dossier_path.write_bytes(dossier_path.read_bytes() + b" rebuilt")
        (root / manual.PAGE).write_text("regenerated page", encoding="utf-8")

        replay, replay_summary, replay_raw = manual.build_plan(root=root)
        manual.apply_plan(replay, replay_summary, replay_raw, root=root)

        assert replay[0]["status"] == "already_applied"
        assert (root / replay[0]["sidecar_path"]).read_bytes() == saved_sidecar
        assert (root / replay_summary["archive_path"]).read_bytes() == raw


def test_dn084_withdrawal_keeps_first_night_learning_and_does_not_overlay_round_two(monkeypatch):
    with tempfile.TemporaryDirectory(prefix=".manual-slot-withdrawn-", dir=ROOT) as temporary:
        root = Path(temporary)
        source, dossier, input_path = _fixture(root, review_id="DN-084", bvid="BV1UMPqzjEvH",
                                                number=2, slot="mechanical_action", action="learn",
                                                targets=[10], result="机械守卫")
        raw = input_path.read_bytes()
        monkeypatch.setattr(manual, "AUTHORIZED_RAW_SHA256", hashlib.sha256(raw).hexdigest())
        plan, summary, raw = manual.build_plan(root=root)
        withdrawn = plan[0]["sidecar"]["reviews"][0]
        assert withdrawn["classification"] == "withdrawn_by_user_correction"
        assert withdrawn["typed"] is None
        assert withdrawn["raw_review"]["slots"][0]["changes"]["action"] == "learn"

        manual.apply_plan(plan, summary, raw, root=root)
        sidecar = manual.apply_manual_slot_review(
            source["games"][0]["bvid"], dossier["rounds"], root=root)

        assert sidecar is not None
        assert dossier["rounds"][0]["night"][0]["action"] == "learn"
        assert dossier["rounds"][1]["night"][0]["action"] == "unknown"


def test_replay_applies_confirmed_overlay_but_skips_withdrawn_slot():
    bvid = "BVfixture"
    archive_bytes = b'{"fixture":true}\n'
    source_sha = hashlib.sha256(archive_bytes).hexdigest()
    archive_rel = (manual.ARCHIVE_DIR / f"{source_sha}.json").as_posix()
    sidecar = {"schema": manual.SIDECAR_SCHEMA, "bvid": bvid, "source_sha256": source_sha,
               "archive_path": archive_rel, "reviews": [
                   {"id": "DN-fixture", "round": 1, "phase": "night", "slot": "mechanical_action",
                    "classification": "confirmed", "typed": {"action": "guard", "actor": 9,
                    "targets": [9], "result": None}},
                   {"id": "DN-084", "round": 2, "phase": "night", "slot": "mechanical_action",
                    "classification": "withdrawn_by_user_correction", "typed": None}]}
    rounds = [{"number": n, "night": [{"slot": "mechanical_action", "action": "unknown",
               "actor": None, "targets": [], "result": None}], "day": []} for n in (1, 2)]

    with tempfile.TemporaryDirectory(prefix=".manual-slot-hook-", dir=ROOT) as temporary:
        root = Path(temporary)
        archive = root / archive_rel
        archive.parent.mkdir(parents=True)
        archive.write_bytes(archive_bytes)
        sidecar_path = root / manual.REVIEW_DIR / bvid / "slot.reviewed.json"
        _dump(sidecar_path, sidecar)
        manual.apply_manual_slot_review(bvid, rounds, root=root)
        replay = [{"number": n, "night": [{"slot": "mechanical_action", "action": "unknown",
                  "actor": None, "targets": [], "result": None}], "day": []} for n in (1, 2)]
        manual.apply_manual_slot_review(bvid, replay, root=root)

    assert rounds[0]["night"][0]["action"] == replay[0]["night"][0]["action"] == "guard"
    assert rounds[1]["night"][0]["action"] == replay[1]["night"][0]["action"] == "unknown"
    manual.validate_terminal_reviews(
        {"reviews": [{"id": "DN-terminal", "classification": "game_ended_before_action", "round": 1}]},
        {"terminal": {"round": 1, "phase": "night"}}, bvid)
    with pytest.raises(manual.ReviewError, match="terminal必须是同轮night"):
        manual.validate_terminal_reviews(
            {"reviews": [{"id": "DN-terminal", "classification": "game_ended_before_action", "round": 1}]},
            {"terminal": {"round": 2, "phase": "night"}}, bvid)


def test_later_export_supersedes_withdrawal_and_preserves_other_reviews(monkeypatch):
    with tempfile.TemporaryDirectory(prefix=".manual-slot-followup-", dir=ROOT) as temporary:
        root = Path(temporary)
        _, _, input_path = _fixture(root, review_id="DN-084", bvid="BV1UMPqzjEvH",
                                    number=2, action="learn", targets=[10], result="机械守卫")
        monkeypatch.setattr(manual, "AUTHORIZED_RAW_SHA256", hashlib.sha256(input_path.read_bytes()).hexdigest())
        plan, summary, raw = manual.build_plan(root=root)
        prior = plan[0]["sidecar"]
        prior["reviews"].append({"id": "DN-prior", "round": 3, "phase": "night", "slot": "seer_check",
                                  "classification": "confirmed", "typed": None})
        manual.apply_plan(plan, summary, raw, root=root)
        source = json.loads(input_path.read_text(encoding="utf-8"))
        source["games"][0]["reviews"][0]["slots"][0]["changes"] = {"action": "guard", "targets": [9]}
        raw = _dump(input_path, source)
        monkeypatch.setattr(manual, "FOLLOWUP_RAW_SHA256", hashlib.sha256(raw).hexdigest())

        plan, summary, raw = manual.build_plan(root=root)
        sidecar = plan[0]["sidecar"]

        assert sidecar["previous_review"] == prior
        assert [r["id"] for r in sidecar["reviews"]] == ["DN-prior", "DN-084"]
        assert sidecar["reviews"][-1]["typed"] == {"action": "guard", "actor": 9, "targets": [9], "result": None}
        manual.apply_plan(plan, summary, raw, root=root)
        assert manual.build_plan(root=root)[1]["idempotent_replay"]


def test_guard_owner_and_mechanical_learning_form():
    seats = [{"seat": 4, "role": "守卫"}, {"seat": 9, "role": "机械狼"}]
    assert manual._actor(seats, "guard", {}, "DN-test") == 4
    assert manual._actor(seats, "wolf_attack", {}, "DN-test") is None
    assert manual._result({"board": "s21_mechanical_wolf_seer"}, "mechanical_action", "通灵师", action="learn") == "机械通灵师"
    assert manual._result({"board": "s21_mechanical_wolf_seer"}, "mechanical_action", "通灵师", action="check") == "通灵师"


@pytest.mark.parametrize(("review_id", "slot", "number", "phase", "classification"), [
    ("DN-099", "mechanical_action", 3, "night", "game_ended_before_action"),
    ("DN-102", "mechanical_day_skill", 4, "day", "mechanical_form_has_no_day_skill"),
])
def test_followup_notes_do_not_become_voluntary_pass(monkeypatch, review_id, slot, number, phase, classification):
    with tempfile.TemporaryDirectory(prefix=".manual-slot-note-", dir=ROOT) as temporary:
        root = Path(temporary)
        source, dossier, input_path = _fixture(root, review_id=review_id, bvid=(
            "BV1w3AVzPE3R" if review_id == "DN-099" else "BV1roX7BQEau"),
            number=number, slot=slot, action="pass", note="用户明确说明终局/不适用")
        if phase == "day":
            dossier["rounds"][-1]["day"] = dossier["rounds"][-1].pop("night")
            dossier["rounds"][-1]["night"] = []
            source["games"][0]["reviews"][0]["phase"] = phase
        path, _ = manual._current_dossier(root, source["games"][0]["id"])
        source["games"][0]["dossier_sha256"] = hashlib.sha256(_dump(path, dossier)).hexdigest()
        page = manual._read_page(root)
        page["games"][0]["dossier_sha256"] = source["games"][0]["dossier_sha256"]
        page["games"][0]["questions"][0]["phase"] = phase
        payload = {k: v for k, v in page.items() if k != "source_fingerprint"}
        page["source_fingerprint"] = source["source_fingerprint"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        (root / manual.PAGE).write_text('<script id="review-data" type="application/json">'
                                       + json.dumps(page) + '</script>', encoding="utf-8")
        raw = _dump(input_path, source)
        _dump(path.parent / "rule_derivations.json", {"terminal": {"round": number, "phase": phase}})
        monkeypatch.setattr(manual, "FOLLOWUP_RAW_SHA256", hashlib.sha256(raw).hexdigest())

        plan, _, _ = manual.build_plan(root=root)
        review = plan[0]["sidecar"]["reviews"][0]
        assert review["classification"] == classification
        assert review["typed"]["action"] == "unavailable"
        assert review["raw_review"]["slots"][0]["changes"]["action"] == "pass"


@pytest.mark.parametrize("fox_takeover", [False, True])
def test_s23_followup_checks_selected_slots_and_preserves_fox_takeover(monkeypatch, fox_takeover):
    with tempfile.TemporaryDirectory(prefix=".manual-slot-s23-", dir=ROOT) as temporary:
        root = Path(temporary)
        source, dossier, input_path = _fixture(root, review_id="DN-224" if fox_takeover else "DN-fixture",
            bvid="BV1saaT6jEyK" if fox_takeover else "BVfixture", number=3,
            slot="wolf_attack", action="attack", targets=[1], board="qingqiu_night")
        game = source["games"][0]
        game["season"] = "S23"
        page = manual._read_page(root)
        page["games"][0]["season"] = "S23"
        payload = {k: v for k, v in page.items() if k != "source_fingerprint"}
        page["source_fingerprint"] = source["source_fingerprint"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        (root / manual.PAGE).write_text('<script id="review-data" type="application/json">'
                                       + json.dumps(page) + '</script>', encoding="utf-8")
        current_path = root / "data/games/S23" / game["bvid"] / "dossier.json"
        dossier["unrelated_previously_confirmed_change"] = True
        if fox_takeover:
            dossier["rounds"][-1]["night"][0]["action"] = "unavailable"
            dossier["rounds"][-1]["night"].append({"slot": "nine_tail_kill", "action": "kill",
                "actor": 9, "targets": [1], "result": "1号守卫出局"})
        _dump(current_path, dossier)
        raw = _dump(input_path, source)
        monkeypatch.setattr(manual, "FOLLOWUP_RAW_SHA256", hashlib.sha256(raw).hexdigest())

        plan, summary, raw = manual.build_plan(root=root)
        review = plan[0]["sidecar"]["reviews"][0]
        assert plan[0]["sidecar_path"].startswith("data/extractions/S23/")
        assert review["slot"] == ("nine_tail_kill" if fox_takeover else "wolf_attack")
        manual.apply_plan(plan, summary, raw, root=root)
        manual.apply_manual_slot_review(game["bvid"], dossier["rounds"], root=root, season="S23")
        assert dossier["rounds"][-1]["night"][0]["action"] == ("unavailable" if fox_takeover else "attack")

        if fox_takeover:
            dossier["rounds"][-1]["night"][-1]["targets"] = [2]
        else:
            dossier["rounds"][-1]["night"][0]["action"] = "forbidden"
        _dump(current_path, dossier)
        (root / plan[0]["sidecar_path"]).unlink()
        with pytest.raises(manual.ReviewError, match="不匹配"):
            manual.build_plan(root=root)
