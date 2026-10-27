"""Validate independent S23 speech/frame reviews without inferring claims by keywords."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from website.api.bluffs import physical_wolf


class AuditError(ValueError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(root: Path, value: str) -> Path:
    path=(root/value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise AuditError('复核证据文件不存在或越出项目目录')
    return path


def normalized(value: str) -> str:
    return re.sub(r'[^0-9A-Za-z\u3400-\u9fff]','',value).lower()


def evidence_errors(root: Path, evidence: dict, bvid: str) -> list[str]:
    errors=[]
    try:
        path=_path(root,evidence.get('source_path',''))
    except (AuditError,TypeError):
        return ['证据文件不存在']
    if bvid not in path.as_posix():
        errors.append('证据文件不属于该视频')
    if digest(path)!=evidence.get('source_sha256'):
        errors.append('证据文件哈希不匹配')
    if evidence.get('kind')=='video_frame':
        when=evidence.get('frame_time_ms',evidence.get('start_ms'))
        if path.suffix.lower()!='.png' or type(when) is not int:
            errors.append('画面证据缺少PNG或时间戳')
        named=re.search(r'_(\d+\.\d{3})\.png$',path.name)
        if named and type(when) is int and abs(round(float(named[1])*1000)-when)>2:
            errors.append('画面时间戳与原始截帧文件不一致')
        return errors
    if evidence.get('kind')!='transcript':
        return errors+['不支持的证据种类']
    start,end=evidence.get('start_ms'),evidence.get('end_ms')
    if type(start) is not int or type(end) is not int or start<0 or end<start:
        return errors+['转写证据时间窗无效']
    raw=json.loads(path.read_text(encoding='utf-8-sig'))
    rows=raw.get('body',raw.get('segments',[]))
    joined=''.join(row.get('content',row.get('text','')) for row in rows
                   if row.get('end_ms',round(row.get('to',0)*1000))>=start-1000
                   and row.get('start_ms',round(row.get('from',0)*1000))<=end+1000)
    text=normalized(joined)
    fragments=[normalized(x) for x in re.split(r'…+|\.{3,}',evidence.get('text',''))]
    offset=0
    for fragment in fragments:
        if not fragment:
            continue
        index=text.find(fragment,offset)
        if index<0:
            errors.append('转写摘录不在指定时间窗内')
            break
        offset=index+len(fragment)
    if not any(fragments):
        errors.append('证据摘录为空')
    return errors


def load_audits(root: Path, games: list[dict], *, require_complete: bool=True) -> dict[str,dict]:
    paths=sorted((root/'data/extractions/S23/bluff_review/parts').glob('audit_*.json'))
    if not paths:
        return {}
    game_index={g['id']:g for g in games}
    audits={}
    problems=[]
    for path in paths:
        payload=json.loads(path.read_text(encoding='utf-8-sig'))
        for audit in payload.get('games',[]):
            key=audit.get('game_id')
            if key not in game_index or key in audits:
                raise AuditError('复核对局超出正式范围或重复')
            game=game_index[key]
            bvid=game['source']['bvid']
            if audit.get('bvid')!=bvid:
                raise AuditError('复核BVID不匹配')
            source=_path(root,audit.get('source_path',''))
            if digest(source)!=audit.get('source_sha256'):
                raise AuditError('复核全文来源哈希过期')
            expected={s['seat']:s for s in game['seats'] if physical_wolf(game,s)}
            indexed={a.get('seat'):a for a in audit.get('assessments',[])}
            if len(indexed)!=len(audit.get('assessments',[])) or set(indexed)!=set(expected):
                raise AuditError(f'{bvid} 物理狼位缺失、重复或混入非狼人')
            for number,assessment in indexed.items():
                seat=expected[number]
                if assessment.get('name')!=seat['name'] or assessment.get('physical_role')!=seat['role']:
                    raise AuditError(f'{bvid}:{number} 底牌或姓名与正式数据不符')
                if assessment.get('decision') not in {'yes','no','uncertain'}:
                    raise AuditError('复核判断值无效')
                if assessment.get('verification_status')=='user_confirmed' and (bvid,number)!=('BV1U3p86dEJY',6):
                    raise AuditError('助手复核不能擅自标为用户确认')
                if assessment['decision']=='yes' and assessment.get('claimed_role') not in {'预言家','通灵师'}:
                    raise AuditError(f'{bvid}:{number} 悍跳身份未明确')
                claim_day=assessment.get('claim_day')
                if not (claim_day is None or type(claim_day) is int and claim_day in (1,2) or claim_day=='later'):
                    raise AuditError(f'{bvid}:{number} 起跳天数无效')
                actual_day=assessment.get('actual_claim_day')
                if actual_day is not None and (claim_day!='later' or type(actual_day) is not int or actual_day<3):
                    raise AuditError(f'{bvid}:{number} 后日起跳天数无效')
                if not assessment.get('decision_note'):
                    raise AuditError('缺少复核推理说明')
                if not assessment.get('evidence'):
                    raise AuditError(f'{bvid}:{number} 缺少实际复核证据')
                for evidence in assessment['evidence']:
                    for error in evidence_errors(root,evidence,bvid):
                        problems.append(f'{bvid}:{number} {error}')
            result_review=audit.get('result_review')
            if result_review is not None:
                if (not isinstance(result_review,dict) or result_review.get('badge')!='lost'
                        or not result_review.get('note') or not result_review.get('evidence')):
                    raise AuditError('补充警徽结果必须明确流失并提供复核证据')
                for evidence in result_review['evidence']:
                    for error in evidence_errors(root,evidence,bvid):
                        problems.append(f'{bvid} 补充警徽结果 {error}')
            frame=audit.get('frame_selection') or {}
            if frame.get('frame_path'):
                image=_path(root,frame['frame_path'])
                if digest(image)!=frame.get('frame_sha256'):
                    problems.append(f'{bvid} 警上截图哈希不匹配')
                if frame.get('visual_reviewed') is not True or frame.get('phase_verified') is not True:
                    problems.append(f'{bvid} 警上截图尚未目视确认阶段')
                window=audit.get('first_day_window') or {}
                when=frame.get('timestamp_ms')
                if type(when) is not int or not window.get('start_ms',0)<=when<=window.get('end_ms',-1):
                    problems.append(f'{bvid} 警上截图不在已核首日窗口')
            audits[key]=audit
    if require_complete and set(audits)!=set(game_index):
        raise AuditError(f'独立复核尚未覆盖全部正式对局：{len(audits)}/{len(game_index)}')
    if problems:
        raise AuditError('；'.join(problems[:20])+f'（共{len(problems)}项）')
    return audits
