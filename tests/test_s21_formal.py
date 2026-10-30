import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_s21_formal as formal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("狼人交牌，好人阵营获胜", "good"),
        ("好人获胜", "good"),
        ("狼人阵营屠神获胜", "werewolf"),
        ("狼人阵营拍刀成功并获胜", "werewolf"),
        ("狼人未获胜", None),
        ("不是好人获胜", None),
        ("并非狼人阵营获胜", None),
        ("狼人阵营获胜，好人阵营获胜", None),
        ("狼人阵营拍刀成功，屠神获胜", None),
    ],
)
def test_winner_only_normalizes_explicit_unambiguous_result(text, expected):
    assert formal.normalize_winner(text) == expected


def _write_json(root: Path, relative: str, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _phase_event(event_id, phase, round_number, action, *, actor=None, targets=None,
                 result=None, details=None):
    return {
        "event_id": event_id, "phase": phase, "round": round_number, "action": action,
        "actor": actor, "actor_physical_role": None, "targets": targets or [],
        "actual_targets": None, "state": "performed", "status": "text_explicit",
        "result": result, "details": details or {}, "note": None, "evidence": [],
    }


@pytest.mark.parametrize("action,formal_action", [("investigate", "check"), ("guard", "guard"), ("poison", "poison")])
def test_mechanical_copied_skill_does_not_compete_with_the_original_role_slot(action, formal_action):
    source = _phase_event("copied-skill", "night", 2, action, actor=9, targets=[5])
    source["actor_physical_role"] = "机械狼"
    phase, number, event = formal.map_phase_event(source)
    assert (phase, number, event["slot"], event["action"]) == ("night", 2, "mechanical_action", formal_action)
    source["actor_physical_role"] = {"investigate": "通灵师", "guard": "守卫", "poison": "女巫"}[action]
    assert formal.map_phase_event(source)[2]["slot"] != "mechanical_action"


def test_build_records_keeps_only_expressible_facts_and_separate_ballots(tmp_path):
    (tmp_path / "config").mkdir()
    for name in ("game_rules.json", "seasons.json"):
        (tmp_path / "config" / name).write_bytes((formal.ROOT / "config" / name).read_bytes())

    caption_path = _write_json(tmp_path, "data/fixture/captions.json", {"segments": []})
    caption_hash = formal.digest(tmp_path, "data/fixture/captions.json")
    identity_path = _write_json(tmp_path, "data/fixture/identity.reviewed.json", {"fixture": "identity"})
    phase_path = _write_json(tmp_path, "data/fixture/phase.reviewed.json", {"fixture": "phase"})
    spec_path = _write_json(tmp_path, "data/fixture/phase-spec.json", {"fixture": "spec"})
    entry = {
        "bvid": "BVfixtureS21", "cid": 123456, "page": 1,
        "title": "20260303 正赛 第一期 Day-1 第一局-预女猎白混",
        "date_candidate": "2026-03-03", "phase_candidate": "regular",
        "selected_transcript_origin": "platform_original_chinese_subtitle",
        "selected_source_path": "data/fixture/captions.json",
        "related_sources": {"platform_raw_chinese_subtitle_path": "data/fixture/captions.json"},
        "source_hashes": {"selected_source_sha256": caption_hash},
    }
    identity = {
        "season": "S21", "bvid": entry["bvid"], "cid": entry["cid"], "page": entry["page"],
        "seats": [
            {"seat": n, "name": f"选手{n}",
             "role": "狼人" if n <= 4 else "平民" if n <= 8 else "猎人" if n == 9 else "女巫" if n == 10 else "预言家" if n == 11 else "白神"}
            for n in range(1, 13)
        ],
    }
    voters = [{"voter": n, "target": 3, "state": "cast", "evidence": []} for n in range(1, 13)]
    reviewed = {
        "schema_version": 1, "season": "S21", "bvid": entry["bvid"], "cid": entry["cid"], "page": 1,
        "source": {"selected_path": "data/fixture/captions.json", "selected_sha256": caption_hash,
                   "original_path": "data/fixture/captions.json", "original_sha256": caption_hash},
        "events": [
            _phase_event("n1", "night", 1, "wolf_attack", targets=[5]),
            _phase_event("d1", "night", 1, "night_deaths", targets=[5, 6]),
            _phase_event("d1-announcement", "day", 1, "death_announcement", targets=[5]),
            _phase_event("signup", "day", 1, "sheriff_signup", targets=[1, 2],
                         details={"initial_signup_complete": True}),
            _phase_event("candidates", "day", 1, "sheriff_candidates", targets=[1]),
            _phase_event("elected", "day", 1, "sheriff_elected", actor=1),
            _phase_event("learn-form", "night", 3, "learned_form", actor=6, result="狼人"),
            _phase_event("exile", "day", 1, "exile", targets=[3]),
            _phase_event("end", "endgame", None, "game_end", result="好人阵营获胜"),
        ],
        "ballots": [{
            "ballot_id": "BVfixtureS21-ballot-01", "day": 1, "type": "exile", "stage": "initial",
            "eligible_voters": list(range(1, 13)), "candidate_seats": None, "votes": voters,
            "outcome": {"exiled": 3}, "completeness": "complete_for_proven_eligible_set",
            "evidence": [], "eligibility_evidence": [], "note": None,
        }],
        "coverage": {"gaps": []},
    }
    binding = {"identity": identity_path.relative_to(tmp_path).as_posix(),
               "phase": phase_path.relative_to(tmp_path).as_posix(),
               "spec": spec_path.relative_to(tmp_path).as_posix(), "approval": {"status": "fixture"}}

    item = formal.build_records(entry, identity, reviewed, binding, root=tmp_path)
    dossier = item["dossier"]
    assert dossier["board"] == "s21_seer_witch_hunter_white_mixed"
    assert dossier["game_number"] == 1
    assert dossier["winner"] == "good"
    assert [seat["faction"] for seat in dossier["seats"]] == ["werewolf"] * 4 + ["good"] * 8
    assert all(not event["votes"] for round_ in dossier["rounds"] for part in ("night", "day") for event in round_[part])
    day_deaths = next(event for event in dossier["rounds"][0]["day"] if event["slot"] == "night_deaths")
    assert day_deaths["action"] == "die" and day_deaths["targets"] == [5, 6]
    sheriff_candidates = next(event for event in dossier["rounds"][0]["day"] if event["slot"] == "sheriff_candidates")
    assert sheriff_candidates["targets"] == [1]
    assert item["voting"]["registrations"][0]["on_police"] == [1, 2]
    assert len(dossier["rounds"]) == 1
    assert not any(event["slot"] == "mechanical_action" and event["action"] == "learn"
                   for event in dossier["rounds"][0]["night"])
    assert any(item["action"] == "learned_form" for item in item["supplemental"]["unmapped"])
    assert any("same-night death facts" in entry["reason"] for entry in item["supplemental"]["unmapped"])
    assert item["voting"]["ballots"][0]["status"] == "complete"
    assert len(item["voting"]["ballots"][0]["votes"]) == 12
    assert item["endgame"]["phases"] == []
    assert item["supplemental"]["phase_reviewed"] == reviewed
    assert item["supplemental"]["game_slug"] == dossier["slug"]


def test_unknown_shot_role_stays_in_supplemental():
    event = _phase_event("shoot-unknown", "day", 1, "shoot", actor=4, targets=[7])
    event["actor_physical_role"] = "盗宝大师"
    phase, number, mapped = formal.map_phase_event(event)
    assert phase is None and number is None
    assert "formal slot" in mapped


@pytest.mark.parametrize("role,slot", [("机械狼", "mechanical_action"), ("盗宝大师", "treasure_extra_attack")])
def test_extra_attack_uses_the_actors_own_skill_slot(role, slot):
    event = _phase_event("extra", "night", 3, "extra_attack", actor=8, targets=[1])
    event["actor_physical_role"] = role
    phase, number, mapped = formal.map_phase_event(event)
    assert (phase, number, mapped["slot"], mapped["action"], mapped["targets"]) == ("night", 3, slot, "attack", [1])


@pytest.mark.parametrize("result", ["首夜平安，无夜死", "狼刀5号后女巫开药解救，复盘确认首夜平安", "现场播报昨夜平安；无首夜夜死。"])
@pytest.mark.parametrize("phase", ["night", "day"])
def test_night_death_peaceful_result_maps_without_inventing_targets(result, phase):
    event = _phase_event("peaceful", phase, 1, "night_deaths", result=result)
    phase, number, mapped = formal.map_phase_event(event)
    assert (phase, number) == ("day", 1)
    assert mapped["slot"] == "night_deaths"
    assert mapped["action"] == "peaceful"
    assert mapped["targets"] == []


def test_daytime_shot_departure_is_not_mapped_to_night_deaths():
    event = _phase_event("shot-departure", "day", 1, "death_announcement", targets=[6])
    event["details"] = {"night_death": False, "cause": "hunter_shot"}
    phase, number, reason = formal.map_phase_event(event)
    assert phase is None and number is None
    assert "daytime departure" in reason


@pytest.mark.parametrize("phase", ["night", "day"])
def test_confirmed_poison_death_is_not_erased_by_peaceful_wolf_knife_wording(phase):
    event = _phase_event("poison-death", phase, 2, "night_deaths", targets=[11],
                         result="狼刀被守，形成平安夜；女巫毒杀11号，11号单死")
    _, _, mapped = formal.map_phase_event(event)
    assert mapped["action"] == "die" and mapped["targets"] == [11]


def test_poisoner_whole_skill_pass_only_maps_its_poison_bottle():
    event = _phase_event("poisoner-pass", "night", 2, "skill_resolution", actor=6, result="毒师技能空过")
    event.update(state="pass", actor_physical_role="毒师")
    assert [e["slot"] for _, _, e in formal.map_phase_events(event)] == ["witch_poison"]


def test_witch_skill_resolution_pass_maps_only_the_named_or_both_bottles():
    event = _phase_event("witch-pass", "night", 2, "skill_resolution", actor=9,
                         result="女巫技能空过")
    event.update(actor_physical_role="女巫", state="pass")
    assert [mapped["slot"] for _, _, mapped in formal.map_phase_events(event)] == ["witch_save", "witch_poison"]
    event["result"] = None
    assert [mapped["slot"] for _, _, mapped in formal.map_phase_events(event)] == ["witch_save", "witch_poison"]
    event["details"] = {"skill": "save"}
    assert [mapped["slot"] for _, _, mapped in formal.map_phase_events(event)] == ["witch_save"]


def test_learn_result_and_steal_card_top_level_result_are_preserved():
    learn = _phase_event("learn", "night", 1, "learn", actor=6, targets=[10],
                         details={"learned_form": "狼人"})
    _, _, mapped_learn = formal.map_phase_event(learn)
    assert mapped_learn["result"] == "狼人"
    steal = _phase_event("steal", "night", 1, "steal_card", actor=7, result="女巫")
    _, _, mapped_steal = formal.map_phase_event(steal)
    assert mapped_steal["result"] == "女巫"
    guard = _phase_event("guarded", "night", 1, "guard", actor=4, targets=[8], result="guarded")
    _, _, mapped_guard = formal.map_phase_event(guard)
    assert mapped_guard["result"] == "guarded"
    save = _phase_event("saved", "night", 1, "save", actor=10, targets=[5], result="saved")
    _, _, mapped_save = formal.map_phase_event(save)
    assert mapped_save["result"] == "saved"


def test_learned_form_merges_into_unique_explicit_learn_without_copying_review_round():
    learn = _phase_event("learn", "night", 1, "learn", actor=6, targets=[10])
    phase, number, mapped = formal.map_phase_event(learn)
    placements = {(phase, number, mapped["slot"]): [(learn, mapped)]}
    form = _phase_event("learn-form", "night", 3, "learned_form", actor=6, result="狼人")
    unmapped = []

    formal._merge_learned_forms(placements, [learn, form], unmapped)

    assert list(placements) == [("night", 1, "mechanical_action")]
    assert placements[("night", 1, "mechanical_action")][0][1]["result"] == "狼人"
    assert any("without changing its round" in row["reason"] for row in unmapped)


def test_self_destruct_uses_later_night_as_day_boundary_without_ballot():
    self_destruct = _phase_event("boom", "day", 1, "self_destruct", actor=4)
    self_destruct["actor_physical_role"] = "狼人"
    later_night = _phase_event("night-2", "night", 2, "wolf_attack", targets=[3])
    facts, issues = formal.voting_facts("fixture", {"events": [self_destruct, later_night], "ballots": []})
    assert facts["ballots"] == []
    assert facts["interruptions"] == [{"id": "boom", "day": 1, "actor": 4,
                                        "reason": "self_destruct", "ends_day": True}]
    assert facts["days"][0]["exile"] == "interrupted_self_destruct"
    assert issues == []


def test_endgame_success_uses_direct_game_winner():
    attack = _phase_event("attack", "endgame", 1, "endgame_attack", result="拍刀成功")
    winner = _phase_event("winner", "endgame", None, "game_end", result="狼人阵营获胜")
    reviewed = {"events": [attack, winner], "source": {"original_sha256": "a" * 64}}
    sidecar, issues = formal.endgame_sidecar("fixture", reviewed)
    assert sidecar["phases"][0]["result"] == "werewolf_win"
    assert issues == []


def test_season_scope_rejects_excluded_bvid_without_reading_review_files(tmp_path):
    scope = formal.load_scope("S21", formal.ROOT)
    excluded = scope["excluded_bvids"][0]
    _write_json(tmp_path, formal.INDEX.as_posix(), {"entries": [{"bvid": excluded}]})
    _write_json(tmp_path, formal.SCOPE.as_posix(), {"seasons": {"S21": {"scope": scope}}})
    with pytest.raises(formal.ReviewError, match="排除"):
        formal.selected_entries(root=tmp_path, bvids=[excluded])


def test_unknown_day_status_and_later_night_do_not_create_voting_days():
    lost = _phase_event("badge-unknown", "day", 1, "badge_lost")
    lost["state"] = "unknown"
    night = _phase_event("last-night", "night", 2, "wolf_attack", targets=[4])
    facts, _ = formal.voting_facts("fixture", {"events": [lost, night], "ballots": []})
    assert facts["days"] == []


def test_changed_spec_requires_a_current_primary_approval(tmp_path):
    entry = {"bvid": "BVfixtureS21", "cid": 123456, "page": 1}
    folder = formal.REVIEW_DIR / entry["bvid"]
    _write_json(tmp_path, (folder / "identity.reviewed.json").as_posix(), {
        "season": "S21", **entry, "review": {"status": "ai_visual_checked"},
        "seats": [{"seat": n} for n in range(1, 13)],
    })
    _write_json(tmp_path, (folder / "phase.reviewed.json").as_posix(), {})
    _write_json(tmp_path, (formal.PHASE_DIR / f"{entry['bvid']}.json").as_posix(), {"bvid": entry["bvid"]})
    with pytest.raises(formal.ReviewError, match="approval已过期"):
        formal.approved_identity_and_phase(entry, root=tmp_path,
                                          approvals={entry["bvid"]: {"spec_sha256": "0" * 64}})


def test_prepared_files_are_compared_before_database_import(tmp_path):
    item = {"entry": {"bvid": "BVfixtureS21"}, "folder": "data/games/S21/fixture",
            "dossier": {"winner": None}, "voting": {}, "endgame": {}, "supplemental": {},
            "rule_derivations": {"version": 1}}
    formal.write_prepared([item], root=tmp_path)
    _write_json(tmp_path, item["folder"] + "/dossier.json", {"winner": "werewolf"})
    with pytest.raises(formal.ReviewError, match="当前approved输入不一致"):
        formal.load_prepared([item], root=tmp_path)
