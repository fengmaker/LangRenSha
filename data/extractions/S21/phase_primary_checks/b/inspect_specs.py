import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
for bvid in sys.argv[1:]:
    spec = json.loads((ROOT / f"data/extractions/S21/phase_specs/{bvid}.json").read_text(encoding="utf-8"))
    tr = json.loads((ROOT / f"data/extractions/S21/media_evidence/{bvid}/transcript.selected.json").read_text(encoding="utf-8"))
    segs = tr["segments"]
    print(f"\n===== {bvid} segments={len(segs)} recap={spec.get('recap_spans')} live={spec.get('live_spans')} =====")
    for n, row in enumerate(spec.get("events", []), 1):
        phase, rnd, action, actor, targets, ids = row[:6]
        print(f"\nEVENT {n} {phase}/{rnd} {action} actor={actor} targets={targets} opts={row[6] if len(row)>6 else {}}")
        for i in ids:
            print(f" {i} [{segs[i]['start_ms']}..{segs[i]['end_ms']}] {segs[i]['text']}")
    for n, ballot in enumerate(spec.get("ballots", []), 1):
        print(f"\nBALLOT {n} day={ballot.get('day')} {ballot.get('type')} {ballot.get('stage')} complete={ballot.get('complete')} eligible={ballot.get('eligible_voters')} candidates={ballot.get('candidate_seats')} outcome={ballot.get('outcome')}")
        for voter, target, ids, *state in ballot.get("votes", []):
            print(f" VOTE {voter}->{target} state={state} ids={ids}")
            for i in ids:
                print(f"  {i} [{segs[i]['start_ms']}..{segs[i]['end_ms']}] {segs[i]['text']}")
        print(" SOURCE:")
        for i in ballot.get("source", []):
            print(f"  {i} [{segs[i]['start_ms']}..{segs[i]['end_ms']}] {segs[i]['text']}")
        if ballot.get("eligibility_source"):
            print(" ELIGIBILITY:")
            for i in ballot["eligibility_source"]:
                print(f"  {i} [{segs[i]['start_ms']}..{segs[i]['end_ms']}] {segs[i]['text']}")
    print("\nGAPS", json.dumps(spec.get("gaps", []), ensure_ascii=False))
    print("\nNOTES", json.dumps(spec.get("notes", []), ensure_ascii=False))
    print("\nTAIL 40 SEGMENTS")
    for i in range(max(0, len(segs)-40), len(segs)):
        print(f" {i} [{segs[i]['start_ms']}..{segs[i]['end_ms']}] {segs[i]['text']}")
