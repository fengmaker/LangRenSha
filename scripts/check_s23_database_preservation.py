"""Compare S22 source database content before and after an S23 import."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website.api.publisher import _connect


def snapshot():
    with _connect('jcms') as conn:
        tables = [r['table_name'] for r in conn.execute(
            "SELECT table_name FROM information_schema.columns WHERE table_schema='jcms' AND column_name='game_id' ORDER BY table_name")]
        tables = [name for name in tables if conn.execute(
            "SELECT table_type FROM information_schema.tables WHERE table_schema='jcms' AND table_name=%s", (name,)).fetchone()['table_type'] == 'BASE TABLE']
        result = {}
        predicate = "t.game_id IN (SELECT g.id FROM games g JOIN seasons s ON s.id=g.season_id WHERE s.code='S22')"
        for name, condition in [('games', "t.season_id=(SELECT id FROM seasons WHERE code='S22')"),
                                 *[(name, predicate) for name in tables],
                                 ('game_ballot_choices', "t.ballot_id IN (SELECT b.id FROM game_ballots b JOIN games g ON g.id=b.game_id JOIN seasons s ON s.id=g.season_id WHERE s.code='S22')")]:
            rows = conn.execute(sql.SQL('SELECT row_to_json(t)::text AS value FROM {} t WHERE '+condition+' ORDER BY row_to_json(t)::text').format(sql.Identifier(name))).fetchall()
            raw = json.dumps([r['value'] for r in rows], ensure_ascii=False).encode('utf-8')
            result[name] = {'rows':len(rows), 'sha256':hashlib.sha256(raw).hexdigest()}
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--save', action='store_true')
    args=parser.parse_args()
    current=snapshot()
    if args.save:
        if args.baseline.exists(): raise RuntimeError('基线已存在，不覆盖')
        args.baseline.write_text(json.dumps(current, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'baseline_saved':True,'tables':len(current)}))
    else:
        baseline=json.loads(args.baseline.read_text(encoding='utf-8'))
        changed=[name for name,value in baseline.items() if current.get(name)!=value]
        print(json.dumps({'S22_database_content_unchanged':not changed,'tables_checked':len(baseline),'changed':changed}))
        if changed: raise SystemExit(2)


if __name__=='__main__': main()
