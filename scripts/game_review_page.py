"""Generate the approved offline game-review layout; no analysis or publication."""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))

from scripts.board_config import load_canonical_template
from scripts.game_timeline import build_game_timeline
from scripts.role_constraints import puppet_target
from scripts.game_derivations import apply_precomputed
from scripts.incremental_common import load_state, work_dir
from scripts.prepare_s23_review import segments

FORMAT = 'masters-incremental-review-v2'
TEMPLATE = Path(__file__).with_name('templates') / 'game_review.html'
SCRIPT = Path(__file__).with_name('templates') / 'game_review.js'


def esc(value):
    return html.escape(str(value), quote=True)


def clock(milliseconds):
    seconds = int(milliseconds) // 1000
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def local_file(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'复核资料文件不存在或不在项目内：{value}')
    return path


def ballot_html(item: dict, seats: dict) -> str:
    votes = item['ballot']['votes']
    head, cells = [], []
    for vote in votes:
        name = seats[vote['voter']].get('name') or '姓名未知'
        head.append(f'<th scope="col" title="{esc(name)}">{vote["voter"]}号</th>')
        target = ('弃票' if vote['state'] == 'abstained' else '待核' if vote['state'] == 'unknown'
                  else str(vote['target']) + '号')
        cells.append(f'<td>{esc(target)}</td>')
    ballot = item['ballot']
    missing = ballot.get('unrecorded_voters') or []
    gap = '<p class="muted">待核票型：' + '、'.join(f'{n}号' for n in missing) + '。</p>' if missing else ''
    return (f'<article class="flow-ballot" data-slot="{esc(item["slot"])}"><h4>{esc(item["title"])}</h4>'
            f'<div class="table-wrap"><table class="ballot-grid {"wide" if len(votes) > 6 else ""}">'
            f'<thead><tr><th>投票座位</th>{"".join(head)}</tr></thead>'
            f'<tbody><tr><th>投向</th>{"".join(cells)}</tr></tbody></table></div>{gap}</article>')


def timeline_html(dossier: dict, voting: dict) -> str:
    seats = {row['seat']: row for row in dossier['seats']}
    parts = []
    for phase in build_game_timeline(dossier, voting)['phases']:
        items = []
        for item in phase['items']:
            if item['kind'] == 'ballot':
                items.append(ballot_html(item, seats))
            else:
                text = esc(item['text']).replace('\n', '<br>')
                items.append(f'<article class="flow-event" data-slot="{esc(item["slot"])}">'
                             f'<h4>{esc(item["title"])}</h4><p>{text}</p></article>')
        parts.append(f'<section class="timeline-phase {"terminal-phase" if phase["terminal"] else ""}" '
                     f'data-phase="{phase["phase"]}" data-round="{phase["number"]}">'
                     f'<h3>{esc(phase["label"])}</h3>{"".join(items)}</section>')
    return ''.join(parts)


def seat_html(dossier: dict) -> str:
    rows = []
    puppet = puppet_target(dossier)
    for row in sorted(dossier['seats'], key=lambda item: item['seat']):
        number, name = row['seat'], row.get('name') or '姓名未知'
        is_puppet = number == puppet
        side = 'werewolf' if is_puppet else row.get('faction')
        faction = {'good': '好人', 'werewolf': '狼人', 'third_party': '第三方'}.get(side, '未知')
        css = 'wolf' if side == 'werewolf' else 'good'
        identity = esc(row.get('role') or '未知') + ('<small>傀儡 · 不带刀</small>' if is_puppet else '')
        rows.append(f'<tr data-seat="{number}"><td class="seat-number">{number}</td><td>{esc(name)}</td>'
                    f'<td>{identity}</td><td><span class="faction {css}">{faction}</span></td></tr>')
    return ''.join(rows)


def bluff_controls_html(dossier: dict) -> str:
    options = ''.join(f'<option value="{row["seat"]}">{row["seat"]}号 {esc(row.get("name") or "姓名未知")}</option>'
                      for row in sorted(dossier['seats'], key=lambda row: row['seat']))
    return ('<div class="bluff-controls"><div data-bluff-rows></div>'
            '<label class="no-bluff-toggle"><input type="checkbox" data-no-bluff>本局无人悍跳</label>'
            '<button class="button add-bluff" type="button" data-add-bluff>添加悍跳人</button>'
            '<p class="muted">默认每局最多一名狼悍跳，选定后其余狼人记为未悍跳；特殊情况请在备注说明。</p>'
            '<p class="muted" data-other-bluff-decisions hidden></p></div>'
            '<template data-bluff-row-template><div class="bluff-row" data-bluff-row>'
            '<label class="bluff-person">悍跳人<select data-bluff-person aria-label="选择悍跳人">'
            f'<option value="">未选择</option>{options}</select></label>'
            '<label class="bluff-success">是否成功<select data-bluff-success disabled aria-label="悍跳是否成功">'
            '<option value="">未填写</option><option value="success">成功</option>'
            '<option value="failure">失败</option><option value="uncertain">待定</option></select></label>'
            '<button class="button remove-bluff" type="button" data-remove-bluff aria-label="移除此悍跳人">×</button>'
            '</div></template>')


def game_card(game: dict, *, season: str, root: Path, review_id: str) -> str:
    entry, candidate = game['entry'], game['candidate']
    dossier = candidate['dossier']
    board = load_canonical_template(dossier['board'])['name']
    display = game.get('review_display')
    if display is None:
        path = work_dir(root, season, entry) / 'review_display.json'
        if not path.is_file():
            raise ValueError(f'{entry["bvid"]} 请先选择身份截图和连续复盘区间，保存 review_display.json')
        display = json.loads(path.read_text(encoding='utf-8'))
    if not display.get('identity_frames') or not display.get('recap'):
        raise ValueError(f'{entry["bvid"]} 缺少身份截图或复盘区间')
    figures = []
    for frame in display['identity_frames']:
        path = local_file(root, frame['source_path'])
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(path.suffix.lower())
        if not mime:
            raise ValueError('身份截图只支持 PNG、JPEG 或 WebP')
        image = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
        caption = esc(frame.get('caption') or '本局12席姓名与真实身份')
        figures.append(f'<figure><button type="button" class="frame-button" data-enlarge aria-label="放大身份截图">'
                       f'<img src="{image}" alt="{caption}"></button><figcaption>{caption}</figcaption></figure>')
    recap = display['recap']
    if (type(recap.get('start_ms')) is not int or type(recap.get('end_ms')) is not int
            or not 0 <= recap['start_ms'] < recap['end_ms']):
        raise ValueError('复盘区间需要有效的起止毫秒')
    lines = [row for row in segments(local_file(root, recap['source_path']))
             if row['start_ms'] < recap['end_ms'] and row['end_ms'] > recap['start_ms']]
    if not lines:
        raise ValueError('指定复盘区间内没有文字')
    recap_html = ''.join(f'<li><time>{clock(row["start_ms"])}</time><span>{esc(row["text"])}</span></li>' for row in lines)
    date = dossier.get('date') or entry.get('labels', {}).get('event_date_candidate') or '日期未知'
    number = dossier.get('game_number') or entry.get('labels', {}).get('game_number_candidate') or '未知'
    winner = {'good': '好人胜', 'werewolf': '狼人胜', 'draw': '平局'}.get(dossier.get('winner'), '胜方待核')
    video = f'https://www.bilibili.com/video/{entry["bvid"]}/?p={int(entry.get("page", 1))}'
    return f'''<main class="game-card" data-review-id="{esc(review_id)}" hidden>
<section class="card game-heading"><div><p class="eyebrow">{esc(season)} · 逐局复核</p><h1>{esc(date)} 第{esc(number)}局 <span style="white-space:nowrap">· {esc(board)}</span></h1><p class="muted">解说：{esc('、'.join(dossier.get('commentators') or []) or '未知')} · 法官：{esc(dossier.get('referee') or '未知')} · <a href="{esc(video)}" target="_blank" rel="noopener">打开原视频 ↗</a></p></div><span class="winner">{winner}</span></section>
<section class="card"><div class="section-head"><h2>身份截图</h2><span>点击图片可放大</span></div>{''.join(figures)}</section>
<section class="card"><h2>座位身份与悍跳复核</h2><div class="table-wrap"><table class="seats"><thead><tr><th>座位</th><th>选手</th><th>真实身份</th><th>阵营</th></tr></thead><tbody>{seat_html(dossier)}</tbody></table></div>{bluff_controls_html(dossier)}</section>
<section class="card game-flow"><h2>对局流程</h2>{timeline_html(dossier, candidate['voting'])}</section>
<details class="card"><summary>复盘转写<span class="muted">{clock(recap['start_ms'])}—{clock(recap['end_ms'])}</span></summary><ul class="recap">{recap_html}</ul></details>
<section class="card review-controls"><h2>我对本局的复核意见</h2><label class="reviewed"><input type="checkbox" data-reviewed>已复核此局</label><label class="muted">需要修正的座位、身份、日夜或票型，都写在这里。<textarea data-note placeholder="填写本局的修正意见……"></textarea></label><p class="muted">意见和选择会自动保存在此浏览器；填写后可导出交回。</p></section></main>'''


def render_review_page(games: list[dict], output: Path, *, season='S23', root=ROOT) -> dict:
    root, output = Path(root).resolve(), Path(output)
    cards, metadata, seen = [], [], set()
    for game in games:
        entry = game['entry']
        review_id = f'{entry["bvid"]}:{entry["cid"]}:p{int(entry.get("page", 1)):02d}'
        if review_id in seen:
            raise ValueError(f'duplicate game identity: {review_id}')
        seen.add(review_id)
        for field in ('candidate_sha256', 'source_sha256'):
            if not game.get(field):
                raise ValueError(f'{field} is required: {review_id}')
        dossier = game['candidate']['dossier']
        metadata.append({'review_id': review_id, 'bvid': entry['bvid'], 'cid': entry['cid'],
                         'page': int(entry.get('page', 1)), 'candidate_sha256': game['candidate_sha256'],
                         'source_sha256': game['source_sha256'],
                         'seats': sorted(row['seat'] for row in dossier['seats']),
                         'label': f'{dossier.get("date", "日期未知")} 第{dossier.get("game_number", "未知")}局 · {load_canonical_template(dossier["board"])["name"]}'})
        cards.append(game_card(game, season=season, root=root, review_id=review_id))
    data = json.dumps({'season': season, 'games': metadata}, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    page = TEMPLATE.read_text(encoding='utf-8')
    for key, value in {'__SEASON__': esc(season), '__GAME_CARDS__': ''.join(cards),
                       '__REVIEW_DATA__': data, '__SCRIPT__': SCRIPT.read_text(encoding='utf-8')}.items():
        page = page.replace(key, value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    return {'format': FORMAT, 'season': season, 'games': len(games),
            'review_ids': [row['review_id'] for row in metadata], 'output': output.as_posix()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', default='S23')
    parser.add_argument('--bvid', action='append')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    state = load_state(ROOT, args.season)
    selected = set(args.bvid or [])
    games = []
    for item in state.get('items', {}).values():
        entry = item['entry']
        if item.get('analysis') != 'ready' or (entry['bvid'] not in selected if selected else item.get('applied')):
            continue
        folder = work_dir(ROOT, args.season, entry)
        candidate = json.loads((folder / 'candidate.json').read_text(encoding='utf-8'))
        derivations = folder / 'rule_derivations.json'
        if derivations.is_file():
            projected = apply_precomputed(candidate['dossier'], candidate['voting'],
                                          json.loads(derivations.read_text(encoding='utf-8')))
            candidate = {**candidate, **projected}
        games.append({'entry': entry, 'candidate': candidate,
                      'candidate_sha256': item['candidate_sha256'], 'source_sha256': item['source_sha256']})
    if not games:
        raise ValueError('没有选中的已分析对局')
    games.sort(key=lambda game: (game['candidate']['dossier'].get('date') or '',
                                game['candidate']['dossier'].get('game_number') or 0))
    output = args.output or ROOT / f'data/manual_review/{args.season}_新增对局人工复核.html'
    print(json.dumps(render_review_page(games, output, season=args.season), ensure_ascii=False))


if __name__ == '__main__':
    main()
