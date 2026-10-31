"""Build the scoped manual form for the 2026-10-30 remaining review list."""
import csv
import hashlib
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from board_config import load_template
from game_derivations import apply_precomputed

read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
REPORT = ROOT / 'data/reports/shared'
MANUAL_REVIEW = ROOT / 'data/manual_review'
rows = list(csv.DictReader((MANUAL_REVIEW / '日夜深度复核剩余待核_20261030.csv').open(encoding='utf-8-sig', newline='')))
items = {i['编号']: i for i in read(REPORT / '日夜深度复核交付_20261030.json')['items']}
mapping = {
    '狼王枪口': ['wolf_king_shot'], '猎人枪口': ['hunter_shot'],
    '夜间出局': ['night_deaths'], '查验': ['seer_check'],
    '机械狼夜间技能': ['mechanical_action'], '守护': ['guard'],
    '机械狼白天技能': ['mechanical_day_skill'], '狼刀': ['wolf_attack'],
    '女巫用药': ['witch_save', 'witch_poison'], '傀儡效果': ['puppet_skill_effect'],
    '毒药': ['witch_poison'], '魔术师交换': ['magician_exchange'],
    '狼王开枪资格': ['wolf_king_state'], '猎人开枪资格': ['hunter_state'],
    '傀儡猎人资格': ['puppet_hunter_eligibility'], '放逐结果': ['exile_result'],
}
labels = {
    'check': '查验', 'learn': '学习', 'attack': '刀人', 'guard': '守护',
    'save': '使用解药', 'poison': '使用毒药', 'shoot': '开枪', 'die': '有人出局',
    'peaceful': '平安夜', 'exile': '放逐', 'none': '无人放逐', 'exchange': '交换',
    'can_shoot': '可以开枪', 'cannot_shoot': '不能开枪',
    'no_effect': '没有效果', 'reverse_check': '查验反转', 'skill_disabled': '技能被禁用',
    'pass': '空过 / 未使用', 'unavailable': '不能发动 / 不适用',
    'forbidden': '本阶段禁止', 'unknown': '仍不能确认',
}
games = OrderedDict()
for row in sorted(rows, key=lambda r: (r['日期'], int(r['局次']), int(r['轮次']), r['阶段'], r['编号'])):
    item = items[row['编号']]
    dossier_path = ROOT / item['档案文件']
    folder = dossier_path.parent
    if row['BVID'] not in games:
        original = read(dossier_path)
        normalized = apply_precomputed(original, read(folder / 'voting.json'), read(folder / 'rule_derivations.json'))['dossier']
        template = load_template(original['board'])
        seats = sorted(original['seats'], key=lambda s: s['seat'])
        assert [s['seat'] for s in seats] == list(range(1, 13)), row['BVID']
        games[row['BVID']] = {
            'bvid': row['BVID'], 'id': original['slug'], 'season': row['赛季'], 'date': row['日期'],
            'game_number': int(row['局次']),
            'board': template['name'].removeprefix(row['赛季'] + ' ').replace('（核实归档）', '').strip(),
            'video': f"https://www.bilibili.com/video/{row['BVID']}/?p=1",
            'seats': [{k: s.get(k) for k in ('seat', 'name', 'role')} for s in seats],
            'dossier_sha256': hashlib.sha256(dossier_path.read_bytes()).hexdigest(),
            'questions': [], '_dossier': normalized, '_template': template,
        }
    game = games[row['BVID']]
    phase = 'night' if row['阶段'] == '夜' else 'day'
    number = int(row['轮次'])
    round_ = next(r for r in game['_dossier']['rounds'] if r['number'] == number)
    slots = []
    for code in mapping[row['字段']]:
        event = next(e for e in round_[phase] if e['slot'] == code)
        definition = next(s for s in game['_template'][phase + '_slots'] if s['code'] == code)
        if row['字段'] == '女巫用药' and event['action'] != 'unknown':
            continue
        display_label = definition['label']
        if not any('\u4e00' <= c <= '\u9fff' for c in display_label):
            display_label = row['字段']
        slots.append({'code': code, 'label': display_label, 'actions': definition['actions'],
                      'before': {k: event.get(k) for k in ('action', 'actor', 'targets', 'result')}})
    assert slots, row['编号']
    game['questions'].append({'id': row['编号'], 'round': number, 'phase': phase,
                             'label': f"第{number}{row['阶段']} · " + ' / '.join(s['label'] for s in slots),
                             'video': row['视频'],
                             'position': row['复盘位置'] if ':' in row['复盘位置'] else '', 'slots': slots})

for game in games.values():
    del game['_dossier'], game['_template']
payload = {'format': 'masters-pending-slot-review-v1', 'games': list(games.values()), 'labels': labels}
payload['source_fingerprint'] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
assert sum(len(g['questions']) for g in games.values()) == len(rows)
data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')

html = (ROOT / 'scripts/templates/pending_slot_review.html').read_text(encoding='utf-8')
if any(game['board'] == '唯邻是从' for game in payload['games']):
    note = ('<details id="neighbor-puppet-rule-note" class="board-rule-note"><summary>唯邻是从 · 复核与发布规则</summary>'
            '<p>傀儡个人胜利阵营跟狼人，物理底牌不变，且不带刀。傀儡平民不显示独立技能事项；傀儡神职只在实际发动技能时于对应技能事项说明影响。'
            '按正常出局条件结算，傀儡仍存活时不能判好人胜；狼方屠边不将傀儡计入其原底牌所属的神职边或平民边。傀儡为神职时，击杀其余3神或5民任一边清空即狼人胜；傀儡为平民时，击杀4神或其余4民任一边清空即狼人胜。</p>'
            '<p>默认夜间阅读排列为守卫守护→狼队击杀→首夜指定傀儡→女巫用药→预言家查验；实际已核时点优先，此排列不证明完整叫醒顺序。'
            '首日按上警名单→警长票（含PK）→警长结果→夜间出局→实际死亡技能/警徽处理及白天事件阅读。确认空守写“本夜空守”，未知不按空守处理。'
            '已确认交牌须在发生阶段单列“狼人交牌”，随后说明胜方并停止后续流程；交牌人未知不填座位。平安夜后交牌时，先保留平安夜，再显示交牌。交牌认输按已确认终局处理，不倒推原狼或傀儡已被击杀/放逐。</p>'
            '<p>S22 2026-08-07第2局：首夜12号大卫空守，第二天白天公布平安夜后狼人交牌；这是单局确认，不泛化其他局。拍刀目标和实际结算保留，导入器英文占位备注不显示。'
            '页内已有的首夜傀儡效果待核题保留为本局时序核对项，不代表逐局或发布流程要显示独立傀儡技能行；本说明不推定具体夜序或技能先后。</p></details>')
    marker = '<section id="json-panel" hidden>'
    if html.count(marker) != 1:
        raise ValueError('待核槽位页缺少唯一规则旁注插入位置')
    html = html.replace(marker, note + '\n' + marker, 1)
output = MANUAL_REVIEW / '日夜待核槽位人工复核_20261030.html'
migration = None
if output.is_file():
    previous_html = output.read_text(encoding='utf-8')
    previous_match = re.search(r'<script id="review-data" type="application/json">(.*?)</script>', previous_html, re.S)
    previous = json.loads(previous_match.group(1)) if previous_match else None
    old_migration = re.search(r'<script id="draft-migration" type="application/json">(.*?)</script>', previous_html, re.S)
    previous_migration = json.loads(old_migration.group(1)) if old_migration else None
    if previous and previous.get('source_fingerprint') != payload['source_fingerprint']:
        old_games = {game['bvid']: game for game in previous['games']}
        compatible = []
        for game in payload['games']:
            old = old_games.get(game['bvid'])
            if old and old['seats'] == game['seats']:
                old_questions = {q['id']: q for q in old['questions']}
                compatible.extend(q['id'] for q in game['questions'] if old_questions.get(q['id']) == q)
        migration = {'source_fingerprint': previous['source_fingerprint'], 'question_ids': compatible}
        if previous_migration:
            migration['previous'] = previous_migration
    elif previous:
        migration = previous_migration
migration_data = json.dumps(migration, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
output.parent.mkdir(parents=True, exist_ok=True)
with output.open('w', encoding='utf-8', newline='\n') as f:
    f.write(html.replace('__DATA__', data).replace('__DRAFT_MIGRATION__', migration_data))
print(json.dumps({'page': str(output), 'games': len(games), 'questions': len(rows),
                  'slots': sum(len(q['slots']) for g in games.values() for q in g['questions']),
                  'dates': len({g['date'] for g in games.values()})}, ensure_ascii=False))
