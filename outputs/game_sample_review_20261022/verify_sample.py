"""Verify the current fixed-slot game record and database import."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
from database import connect
from game_records import import_game, validate
value=json.loads((ROOT/"data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8"))
validate(value)
checks={"fixed_slots_and_roles":"passed"}
with connect() as conn:
    def counts():
        return {name:conn.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"] for name in ["people","game_details","game_seats","game_staff","game_files","game_rounds","game_event_records","game_event_targets","game_event_votes","game_event_effects","game_revisions","extraction_runs","transcription_runs","transcript_segments","evidence_links","reviews"]}
    before=counts()
receipt=import_game(value)
with connect() as conn:
    after=counts()
    assert before==after,(before,after)
    checks["repeat_import_keeps_counts_stable"]="passed"
    counts_by_phase=conn.execute("SELECT round_number,phase,count(*) AS n FROM game_event_records WHERE game_id=%s GROUP BY round_number,phase ORDER BY round_number,phase",(receipt["game_id"],)).fetchall()
    assert len(counts_by_phase)==6
    assert all(r["n"]==({"night":8,"day":11}[r["phase"]]) for r in counts_by_phase)
    checks["database_has_eight_night_eleven_day_slots_per_round"]="passed"
    staff=conn.execute("SELECT p.name,s.duty FROM game_staff s JOIN people p ON p.id=s.person_id WHERE s.game_id=%s ORDER BY s.duty,s.position",(receipt["game_id"],)).fetchall()
    assert {(r["name"],r["duty"]) for r in staff}=={("其人","commentator"),("桃子","commentator"),("豆儿啵","referee")}
    aliases=conn.execute("SELECT p.name,a.alias FROM person_aliases a JOIN people p ON p.id=a.person_id WHERE p.name IN ('其人','桃子','豆儿啵','辉少') ORDER BY p.name,a.alias").fetchall()
    checks["shared_people_and_canonical_staff_names"]="passed"
    row=conn.execute("SELECT d.winning_faction,count(s.seat_number) AS seats,count(s.person_id) AS named_seats FROM game_details d JOIN game_seats s ON s.game_id=d.game_id WHERE d.game_id=%s GROUP BY d.winning_faction",(receipt["game_id"],)).fetchone()
    assert row["seats"]==12 and row["named_seats"]==12 and row["winning_faction"]=="good"
    orders=conn.execute("SELECT round_number,action,random_point,speech_scope,start_seat FROM game_event_records WHERE game_id=%s AND slot_code='speech_order' ORDER BY round_number",(receipt["game_id"],)).fetchall()
    assert [(r["action"],r["random_point"],r["start_seat"]) for r in orders]==[("order",3,4),("not_held",None,None),("order",11,11)]
    checks["random_point_and_no_second_day_speech"]="passed"
    hunter_states=conn.execute("SELECT action FROM game_event_records WHERE game_id=%s AND slot_code='hunter_state' ORDER BY round_number",(receipt["game_id"],)).fetchall()
    assert [r["action"] for r in hunter_states]==["can_shoot"]*3
    checks["three_nights_unpoisoned_hunter_can_shoot"]="passed"
    mechanical_states=conn.execute("SELECT round_number,phase,action,availability FROM game_event_records WHERE game_id=%s AND slot_code IN ('mechanical_action','mechanical_day_skill') ORDER BY round_number,phase",(receipt["game_id"],)).fetchall()
    assert [(r["action"],r["availability"]) for r in mechanical_states if r["phase"]=="night"]==[("learn","learning"),("unavailable","wolves_alive"),("unavailable","wolves_alive")]
    assert all((r["action"],r["availability"])==("unavailable","wrong_phase") for r in mechanical_states if r["phase"]=="day")
    checks["mechanical_double_knife_requires_takeover_and_day_slot_is_reserved"]="passed"
    knife_confirmations=conn.execute("SELECT action FROM game_event_records WHERE game_id=%s AND slot_code='mechanical_knife_status' ORDER BY round_number",(receipt["game_id"],)).fetchall()
    assert [r["action"] for r in knife_confirmations]==["not_carrying"]*3
    checks["god_view_nightly_knife_confirmations"]="passed"
    names=conn.execute("SELECT s.seat_number,p.name FROM game_seats s JOIN people p ON p.id=s.person_id WHERE s.game_id=%s",(receipt["game_id"],)).fetchall()
    assert {r["seat_number"]:r["name"] for r in names if r["seat_number"] in {7,9,11,12}}=={7:"JY",9:"翼风",11:"申屠",12:"陈俊洁"}
    checks["confirmed_seats_and_fixed_jy_seat"]="passed"
    checks["import_adds_no_review_evidence_or_full_transcript_rows"]="passed"
report={"slug":value["slug"],"checks":checks,"sample":receipt,"seat_summary":row,"staff":staff,"aliases":aliases,"counts_by_phase":counts_by_phase,"mechanical_states":mechanical_states}
(Path(__file__).parent/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
