"""Local, read-only preview of the 23 reviewed games, without publishing."""
from copy import deepcopy
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from website.api import publisher
from scripts.game_timeline import build_game_timeline

api = importlib.import_module('website.api.app')
OUT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'outputs/board_display_audit_20261102/manifest.json').read_text(encoding='utf-8'))
GAMES = {}
for row in MANIFEST['games']:
    entries, _, _ = publisher.load_release(publisher.DEFAULT_SOURCE_ROOT, [row['season']], sample=row['id'].split('-')[1])
    entry = entries[0]
    people = {seat['name']: seat['name'] for seat in entry['dossier']['seats']}
    game = publisher._public_game(entry['dossier'], entry['voting'], entry['endgame'], entry['audit'],
                                  entry['board'], people, source_voting=entry.get('source_voting'),
                                  derivations=entry.get('derivations'))
    game = api._resolved_snapshot(game)
    game['release_id'] = 'local-preview-20261102-unpublished'
    before = deepcopy(game)
    game['timeline'] = build_game_timeline(game)
    assert {k: v for k, v in game.items() if k != 'timeline'} == before
    GAMES[game['id']] = game
    folder = OUT / 'source_preview'
    folder.mkdir(exist_ok=True)
    (folder / (game['id'] + '.json')).write_text(json.dumps(game, ensure_ascii=False, indent=2), encoding='utf-8')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            links = ''.join(f'<li><a href="http://127.0.0.1:3042/games/{escape(g["id"])}">'
                            f'{escape(g["season"])} {escape(g["date"])} 第{g["game_number"] or "待核"}局 '
                            f'{escape(g["board"]["name"])}</a></li>' for g in GAMES.values())
            body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                    '<title>23局修改预览</title><h1>23局修改预览</h1>'
                    '<p>使用当前本地源档案，尚未切换活动发布版本。</p><ul>' + links + '</ul></html>')
            payload, content_type = body.encode(), 'text/html; charset=utf-8'
        else:
            game_id = unquote(self.path.removeprefix('/api/v1/games/'))
            if not self.path.startswith('/api/v1/games/') or game_id not in GAMES:
                self.send_error(404)
                return
            payload = json.dumps(GAMES[game_id], ensure_ascii=False).encode()
            content_type = 'application/json; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == '__main__':
    print('Read-only preview API/index: http://127.0.0.1:8042', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8042), Handler).serve_forever()
