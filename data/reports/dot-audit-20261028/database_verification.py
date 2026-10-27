"""Read-only comparison of all S22/S23 formal facts with the configured JCMS database."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from database import connect
from import_s23_formal import build_batch, db_season_fingerprint

REPORT = ROOT / "data/reports/dot-audit-20261028"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(name, value):
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def sources():
    s22 = []
    for path in sorted((ROOT / "data/games/S22").glob("*/dossier.json")):
        s22.append({"dossier": read(path), "voting": read(path.with_name("voting.json")),
                    "endgame": read(path.with_name("endgame.json")), "folder": path.parent})
    return s22


def compare(conn, games, *, endgames=False):
    errors = []
    for game in games:
        d, v = game["dossier"], game["voting"]
        slug = d["slug"]
        row = conn.execute("SELECT id FROM games WHERE slug=%s", (slug,)).fetchone()
        if not row:
            errors.append({"slug": slug, "section": "game_missing"})
            continue
        gid = row["id"]

        def require(section, actual, expected):
            # Normalize date values and tuple/list containers without discarding fields.
            a = json.loads(json.dumps(actual, default=str))
            e = json.loads(json.dumps(expected, default=str))
            if a != e:
                errors.append({"slug": slug, "section": section, "actual": a, "expected": e})

        details = conn.execute("""SELECT board_code,event_date::text AS date,phase,episode,
            day_in_episode,game_number,winning_faction AS winner FROM game_details WHERE game_id=%s""", (gid,)).fetchone()
        require("details", details, {"board_code": d["board"], **{k: d.get(k) for k in
                ("date", "phase", "episode", "day_in_episode", "game_number", "winner")}})
        seats = conn.execute("""SELECT seat_number AS seat,p.name,s.role,s.faction,
            learning_target_seat AS learning_target,learned_role FROM game_seats s
            LEFT JOIN people p ON p.id=s.person_id WHERE game_id=%s ORDER BY seat_number""", (gid,)).fetchall()
        require("seats", seats, [{k: s.get(k) for k in ("seat", "name", "role", "faction", "learning_target", "learned_role")}
                                 for s in sorted(d["seats"], key=lambda s: s["seat"])])
        staff = conn.execute("""SELECT duty,position,p.name FROM game_staff s JOIN people p ON p.id=s.person_id
            WHERE game_id=%s ORDER BY duty,position""", (gid,)).fetchall()
        expected_staff = [{"duty": "commentator", "position": n, "name": name}
                          for n, name in enumerate(d["commentators"], 1)]
        if d.get("referee"):
            expected_staff.append({"duty": "referee", "position": 1, "name": d["referee"]})
        require("staff", staff, expected_staff)
        events = conn.execute("""SELECT round_number,phase,slot_code AS slot,action,actor_seat AS actor,
            result_code AS result,start_seat,direction,random_point,speech_scope,availability,
            COALESCE((SELECT jsonb_agg(t.seat_number ORDER BY position) FROM game_event_targets t WHERE t.event_id=e.id),'[]'::jsonb) AS targets,
            COALESCE((SELECT jsonb_agg(jsonb_build_object('kind',f.kind,'intended_target',f.intended_target,
                'dead_seat',f.dead_seat,'shield_actor',f.shield_actor) ORDER BY position)
                FROM game_event_effects f WHERE f.event_id=e.id),'[]'::jsonb) AS effects,
            COALESCE((SELECT jsonb_agg(jsonb_build_object('round',v.ballot_round,'voter',v.voter_seat,
                'target',v.target_seat,'abstained',v.abstained) ORDER BY v.ballot_round,v.voter_seat)
                FROM game_event_votes v WHERE v.event_id=e.id),'[]'::jsonb) AS votes
            FROM game_event_records e WHERE game_id=%s ORDER BY round_number,phase,slot_code""", (gid,)).fetchall()
        expected_events = []
        keys = ("slot", "action", "actor", "result", "start_seat", "direction", "random_point",
                "speech_scope", "availability", "targets", "effects", "votes")
        for r in d["rounds"]:
            for phase in ("day", "night"):
                for event in r[phase]:
                    item = {"round_number": r["number"], "phase": phase, **{k: event.get(k) for k in keys}}
                    item["votes"] = sorted(item["votes"], key=lambda v: (v["round"], v["voter"]))
                    expected_events.append(item)
        expected_events.sort(key=lambda e: (e["round_number"], e["phase"], e["slot"]))
        require("events", events, expected_events)
        ballots = conn.execute("""SELECT ballot_key AS id,day_number AS day,kind,ballot_number AS number,
            stage,status,candidates,eligible_voters,tied_candidates,winner_seat AS winner,
            COALESCE((SELECT jsonb_agg(jsonb_build_object('voter',c.voter_seat,'target',c.target_seat,'state',c.state)
              ORDER BY c.voter_seat) FROM game_ballot_choices c WHERE c.ballot_id=b.id),'[]'::jsonb) AS votes
            FROM game_ballots b WHERE game_id=%s ORDER BY ballot_key""", (gid,)).fetchall()
        expected_ballots = []
        for b in sorted(v["ballots"], key=lambda b: b["id"]):
            expected = {k: b[k] for k in ("id", "day", "kind", "number", "stage", "status", "candidates",
                                         "eligible_voters", "tied_candidates", "winner")}
            expected["votes"] = sorted([{k: vote[k] for k in ("voter", "target", "state")}
                                        for vote in b["votes"]], key=lambda vote: vote["voter"])
            expected_ballots.append(expected)
        require("ballots", ballots, expected_ballots)
        registrations = conn.execute("""SELECT registration_key AS id,day_number AS day,seat_number AS seat,registered
            FROM game_sheriff_registrations WHERE game_id=%s ORDER BY registration_key,seat_number""", (gid,)).fetchall()
        expected_registrations = [{"id": r["id"], "day": r["day"], "seat": seat, "registered": state}
                                  for r in v["registrations"] for state, key in ((True, "on_police"), (False, "off_police"))
                                  for seat in r[key]]
        expected_registrations.sort(key=lambda r: (r["id"], r["seat"]))
        require("registrations", registrations, expected_registrations)
        days = conn.execute("""SELECT day_number AS day,sheriff_status AS sheriff,exile_status AS exile
            FROM game_voting_days WHERE game_id=%s ORDER BY day_number""", (gid,)).fetchall()
        require("voting_days", days, [{k: day[k] for k in ("day", "sheriff", "exile")}
                                      for day in sorted(v["days"], key=lambda day: day["day"])])
        if endgames:
            actual_endgame = conn.execute("""SELECT kind,day_number AS day,actor_seat AS actor,declared_targets,result
                FROM game_endgame_phases WHERE game_id=%s ORDER BY phase_number""", (gid,)).fetchall()
            expected_endgame = [{k: p[k] for k in ("kind", "day", "actor", "declared_targets", "result")}
                                for p in game["endgame"]["phases"]]
            for p in expected_endgame:
                p["declared_targets"] = sorted(p["declared_targets"])
            require("endgame", actual_endgame, expected_endgame)
    return errors


def verify_all():
    s22 = sources()
    batch = build_batch()
    s23 = [{"dossier": game["db_dossier"], "voting": game["voting"]} for game in batch["games"]]
    with connect() as conn:
        errors = compare(conn, s22, endgames=True) + compare(conn, s23)
        report = {"checked_games": len(s22) + len(s23), "equal": not errors, "mismatches": errors,
                  "fingerprints": {code: db_season_fingerprint(conn, code) for code in ("S22", "S23")}}
    write("formal-database-comparison.json", report)
    print(json.dumps({"checked_games": report["checked_games"], "equal": not errors,
                      "mismatch_count": len(errors), "examples": [
                          {"slug": e["slug"], "section": e["section"]} for e in errors[:10]]}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    verify_all()
