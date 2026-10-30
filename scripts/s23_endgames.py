"""Source-bound S23 endgame candidates; no database import entry point."""
from __future__ import annotations

import json
from pathlib import Path

from endgame_records import validate
from prepare_s23_review import segments
from season_naming import digest

ROOT = Path(__file__).resolve().parents[1]

# Reviewed ending announcements/recaps. A target set does not imply knife order.
# Ordinary night attacks and speculative discussion are deliberately excluded.
CASES = {
    16: (4, None, [3], 'werewolf_win', [[3422580,3430600],[3491370,3497130]], '第四天白天拍最后一神3号猎人。'),
    19: (2, None, [4,11], 'werewolf_win', [[5228169,5234430],[5291580,5299429]], '第二天8号自爆后拍4、11两名平民。'),
    24: (4, 4, [12], 'werewolf_win', [[4562720,4582320]], '三次自爆各自入夜后为第四天；复盘口误称第三天。猎杀结算后九尾狐拍12号。'),
    26: (4, 8, [1], 'werewolf_win', [[6980290,6987550]], '最后一狼8号拍1号混血儿；按当局裁判屠民结算保留。'),
    29: (4, 2, [7], 'werewolf_win', [[3537910,3544290]], '第四天12号被放逐后，最后一狼2号拍7号。'),
    31: (3, 11, [6], 'werewolf_win', [[5130170,5137400]], '第三天9号被放逐后，11号机械猎人拍最后一神6号。'),
    37: (4, None, [1,6], 'werewolf_win', [[5900830,5905430],[5976650,5984259]], '第四天2号自爆后拍1号平民与6号猎人。'),
    45: (3, None, [10], 'werewolf_win', [[5539280,5549150]], '第三天两轮平票形成平安日后，拍最后一神10号。'),
    47: (2, None, [2,3,5], 'werewolf_win', [[4434680,4446050]], '第二天白神翻牌出局后，裁判报三刀目标2、3、5。'),
    51: (2, None, [1,8], 'werewolf_win', [[4278940,4281540],[4322480,4331400]], '第二天拍1号白神与8号猎人。'),
    52: (1, None, [1,7,8], 'werewolf_win', [[3802480,3821310],[3866860,3881510]], '第一天魔术师被放逐后，拍1号定序王子、8号预言家与7号平民。'),
    61: (2, None, [10,11], 'good_win', [[6073950,6083760],[6150319,6159030]], '第二天2号自爆后拍10号女巫与11号混血儿失败，好人获胜。'),
    63: (2, None, [1,5], 'werewolf_win', [[5428220,5453990],[5500389,5509650]], '第二天首轮平票后，PK发言期间拍刀；没有PK复投。'),
    69: (3, 7, [2,9], 'werewolf_win', [[2990300,2993580],[3060319,3069100]], '第三天5号自爆后，机械双刀狼拍2号女巫与9号猎人。'),
    72: (2, None, [3,5], 'werewolf_win', [[5511660,5511660],[5582250,5590520]], '第二天12号自爆后，拍5号女巫与3号猎人。'),
    77: (3, None, [1,8], 'werewolf_win', [[5960609,5965849],[6008600,6022330]], '第三天猎人被放逐并开枪后，剩余狼人拍1、8号。'),
    78: (2, None, [2,3], 'werewolf_win', [[6610540,6626949]], '第二天8号被放逐后拍2、3号；裁判说明先刀魔术师，技能即使换死狼人仍有后续刀。'),
    80: (1, None, [7,9,10], 'good_win', [[2930810,2941680]], '第一天11号狼人被放逐后拍10、9、7号失败，好人获胜。'),
    87: (4, 12, [7], 'werewolf_win', [[4664460,4668360],[4725320,4745560]], '第三天2号自爆入夜、通灵师死亡后进入第四天；复盘重复说第三天。3号自爆后机械狼拍7号猎人。'),
}


def endgame_for(entry, dossier, *, rows=None, root=ROOT):
    path = root / entry['source_path']
    if digest(path) != entry['source_sha256']:
        raise ValueError('拍刀复核来源已变化：' + entry['bvid'])
    phases = []
    spec = CASES.get(entry['index'])
    if spec:
        binding=json.loads((root/'data/extractions/S23/endgame_reviewed_sources.json').read_text(encoding='utf-8'))['items'][str(entry['index'])]
        if (binding['bvid']!=entry['bvid'] or binding['source_path']!=entry['source_path'] or
                binding['source_sha256']!=entry['source_sha256']):
            raise ValueError('拍刀裁定与冻结来源不匹配：'+entry['bvid'])
        day, actor, targets, result, spans, note = spec
        rows = segments(path) if rows is None else rows
        proof = []
        for lo, hi in spans:
            selected = [r for r in rows if r['end_ms'] >= lo and r['start_ms'] <= hi]
            if not selected:
                raise ValueError('拍刀证据窗口为空：' + entry['bvid'])
            proof.append({'path':entry['source_path'],'source_path':entry['source_path'],
                          'start_ms':min(r['start_ms'] for r in selected),
                          'end_ms':max(r['end_ms'] for r in selected),
                          'quote':'\n'.join(r['text'] for r in selected)})
        phases.append({'kind':'wolf_rush','day':day,'actor':actor,'declared_targets':sorted(targets),
                       'result':result,'note':note,'evidence':proof})
        if dossier.get('winner') and result != dossier['winner'] + '_win':
            raise ValueError('拍刀与候选胜方冲突：' + entry['bvid'])
    sidecar = {'schema_version':1,'game_slug':dossier['slug'],'phases':phases,
               'source_sha256':entry['source_sha256'],'review_status':'ai_candidate_awaiting_user'}
    validate(sidecar)
    return sidecar
