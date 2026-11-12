"""Small adapters for testing final data and new-candidate projections."""
from copy import deepcopy
import json
from pathlib import Path

from scripts.board_config import load_template

ROOT = Path(__file__).resolve().parents[2]


def final_game(season, bvid):
    path = next((ROOT / 'data/games' / season).glob(f'*{bvid}*/game.json'))
    return json.loads(path.read_text(encoding='utf-8'))


def candidate_item(season, bvid):
    game = final_game(season, bvid)
    dossier = deepcopy(game)
    dossier['slug'] = game['id']
    dossier['board'] = game['board']['code']
    dossier['_publication_context'] = {
        'terminal_observation': game.get('terminal_observation'),
    }
    board = load_template(dossier['board'])
    board['_public_board'] = game['board']
    return {'dossier': dossier, 'voting': game['voting'], 'endgame': game['endgame'],
            'audit': None, 'board': board}
