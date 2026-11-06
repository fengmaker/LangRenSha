"""S22 voting batch command and compatibility exports for voting_core."""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
import sys

import batch_s22 as batch
from database import ReviewError, connect, migrate
from voting_core import (
    ABSTAIN, ANNOUNCED_CHOICE, CHOICE, GROUP, NUM, SEAT,
    choices, evidence, extract, find_registration_candidates, import_voting,
    normalized, number, seats, validate,
)

REPORT = batch.REPORT_DIR / "S22_投票补录进度.json"
EXTRACTIONS = batch.ROOT / "data/extractions/S22/voting"


def run(write_database=False):
    state = batch.load_state()
    if write_database:
        migrate()
    items, csv_rows = [], []
    for bvid, entry in state["items"].items():
        folder = batch.ROOT / entry["output_dir"]
        dossier_path = folder / "dossier.json"
        dossier = batch.read_json(dossier_path)
        source = batch.ROOT / entry["source_path"]
        segments = batch.load_segments(source)
        facts, audit = extract(segments, dossier, entry["source_path"])
        audit["source_path"] = entry["source_path"]
        from review_s22_voting import apply_accepted
        apply_accepted(facts, audit, entry)
        from causal_voting_review import apply as apply_causal
        apply_causal(facts, audit, entry)
        if audit.get("causal_review", {}).get("patches"):
            from review_s22_voting import rebuild_days
            rebuild_days(facts)
        from voting_crosscheck import reconcile, day_outcomes
        reconcile(facts, audit, dossier)
        # Apply reviewed S22-only corrections before rule-derived voter
        # eligibility, default abstentions, and outcomes are rebuilt.
        from s22_dot_audit import apply_generated_voting
        dot_audit_applied = apply_generated_voting(facts, audit, entry)
        review_path = folder / "复核记录.json"
        if review_path.is_file():
            audit["day_crosscheck_source"] = {"path": batch.relative(review_path),
                "sha256": batch.digest(review_path), "recap_segments": batch.read_json(review_path).get("recap_segments", [])}
        from game_flow import collect_death_announcements
        audit["night_death_supplements"] = collect_death_announcements(segments, dossier, facts, audit)
        endgame_path = folder / "endgame.json"
        if endgame_path.is_file():
            endgame = batch.read_json(endgame_path)
            if endgame["source_sha256"] != batch.digest(source):
                raise ValueError("拍刀原文已变化，请先重新复核：" + bvid)
            audit["endgame_phases"] = endgame["phases"]
        from voting_rules import apply_rules
        apply_rules(facts, audit, dossier)
        from causal_voting_review import day_outcomes as causal_day_outcomes
        audit["day_outcomes"] = causal_day_outcomes(day_outcomes(facts, audit, dossier), audit)
        validate(facts)
        audit.update(bvid=bvid, source_sha256=batch.digest(source), dossier_sha256=batch.digest(dossier_path),
                     generated_at=batch.now(), facts=facts)
        if dot_audit_applied:
            audit["dot_audit_applied"] = sorted(set(audit.get("dot_audit_applied", [])) | set(dot_audit_applied))
        EXTRACTIONS.mkdir(parents=True, exist_ok=True)
        batch.atomic_json(EXTRACTIONS / (bvid + ".json"), audit)
        batch.atomic_json(folder / "voting.json", facts)
        receipt = import_voting(facts) if write_database else None
        item = {"bvid": bvid, "date": entry["date"], "game_number": entry["game_number"],
                "file": batch.relative(folder / "voting.json"), "registrations": len(facts["registrations"]),
                "ballots": len(facts["ballots"]), "votes": sum(len(b["votes"]) for b in facts["ballots"]),
                "pk_ballots": sum(b["stage"] == "pk" for b in facts["ballots"]),
                "unknown_day_ballots": sum(b["day"] is None for b in facts["ballots"]),
                "unknown_kind_ballots": sum(b["kind"] == "unknown" for b in facts["ballots"]),
                "complete_ballots": sum(b["status"] == "complete" for b in facts["ballots"]),
                "default_abstentions": sum(len(a["voters"]) for a in audit.get("rule_applications", [])),
                "deferred_elections": sum(x["status"] == "deferred" for x in audit.get("election_flow", [])),
                "badge_lost_after_second_self_destruct": sum(x["status"] == "badge_lost" for x in audit.get("election_flow", [])),
                "issues": audit["issues"], "database": receipt}
        items.append(item)
        for b in facts["ballots"]:
            for v in b["votes"]:
                ev = audit["evidence"][b["id"]][0]
                defaulted = any(a["target"] == b["id"] and v["voter"] in a["voters"] for a in audit.get("rule_applications", []))
                confirmed = any(a["target"] == b["id"] and v["voter"] in a["voters"] for a in audit.get("human_confirmations", []))
                basis = "用户人工确认" if confirmed else "按规则默认弃票" if defaulted else "原文明确弃票" if v["state"] == "abstained" else "原文明确投向"
                csv_rows.append([entry["date"], entry["game_number"], bvid, b["day"], b["kind"], b["number"], b["stage"],
                                 v["voter"], v["target"], v["state"], ev["start_ms"], entry["source_path"], basis])
    counts = {key: sum(i[key] for i in items) for key in ("registrations", "ballots", "votes", "pk_ballots", "unknown_day_ballots", "unknown_kind_ballots", "complete_ballots", "default_abstentions", "deferred_elections", "badge_lost_after_second_self_destruct")}
    report = {"generated_at": batch.now(), "games": len(items), "database_written": write_database,
              **counts, "games_with_votes": sum(i["votes"] > 0 for i in items),
              "games_without_registration": sum(i["registrations"] == 0 for i in items),
              "games_without_votes": sum(i["votes"] == 0 for i in items), "items": items}
    batch.atomic_json(REPORT, report)
    export = batch.ROOT / "data/exports/S22_逐人投票.csv"
    with export.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["日期", "局次", "BVID", "游戏日", "投票类型", "本日轮号", "阶段", "投票人", "投给", "票状态", "原文起点毫秒", "转写来源", "录入依据"])
        writer.writerows(csv_rows)
    summary = {k: v for k,v in report.items() if k != "items"}
    page = ["<!doctype html><meta charset='utf-8'><title>S22 投票补录</title><style>body{font:16px/1.7 system-ui;margin:30px;color:#19364a}table{border-collapse:collapse}td,th{padding:7px;border:1px solid #ddd}</style>",
            "<h1>S22 投票补录</h1><p>有票权玩家未明确报出投向时按确认口径默认弃票，原文明确弃票与规则推导分别标注。延期竞选只延至次日，再次自爆则流徽；PK前后分别记录。票权、日序或投票是否举行不明时仍待核。</p>",
            "<p>" + html.escape(json.dumps(summary,ensure_ascii=False)) + "</p>", "<a href='S22_逐人投票.csv'>逐人投票 CSV</a><table><tr><th>日期 / 局次</th><th>BV</th><th>上警名单组</th><th>投票轮</th><th>逐人票</th><th>PK轮</th><th>档案</th></tr>"]
    for i in items:
        folder = batch.ROOT / state["items"][i["bvid"]]["output_dir"]
        target = folder / "投票记录.html"
        facts = batch.read_json(folder / "voting.json")
        detail = render_html(facts, batch.read_json(EXTRACTIONS / (i["bvid"] + ".json")))
        target.write_text(detail, encoding="utf-8")
        url = "../../" + batch.relative(target)
        page.append(f"<tr><td>{i['date']} / {i['game_number']}</td><td>{i['bvid']}</td><td>{i['registrations']}</td><td>{i['ballots']}</td><td>{i['votes']}</td><td>{i['pk_ballots']}</td><td><a href='{html.escape(url)}'>查看逐日票型</a></td></tr>")
    page.append("</table>")
    (export.parent / "S22_投票补录.html").write_text("".join(page),encoding="utf-8")
    from review_s22_voting import build as build_review
    build_review()
    return summary


def render_html(facts, audit):
    out = ["<!doctype html><meta charset='utf-8'><title>逐日投票记录</title><style>body{font:16px/1.7 system-ui;margin:30px;max-width:1100px;color:#19364a}pre{white-space:pre-wrap}section{border:1px solid #ccc;padding:15px;margin:12px 0}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px}</style>",
           "<h1>逐日投票记录</h1><p>有票权玩家没有明确投向时按确认口径默认弃票；原文明确弃票与默认弃票分别标注。票权名单未知时不补造玩家。</p>"]
    def ev(key):
        return "".join(f"<details><summary>原文 {e['start_ms']/1000:.2f}–{e['end_ms']/1000:.2f} 秒</summary><pre>{html.escape(e['quote'])}</pre></details>" for e in audit["evidence"].get(key,[]))
    flow = audit.get("game_flow", {})
    if flow:
        out.append("<h2>存活人数与票权计算</h2><p>按夜间死亡、先前公投及技能出局重放；当次公投之后的开枪不扣减本次票权。</p>")
        for r in flow["rounds"]:
            if r["day"] in flow["days"]:
                living = r["living_before_vote"]
                label = f"{len(living)}人，座位{living}" if living is not None else "死亡或出局信息不足"
                out.append(f"<p>第{r['day']}天放逐投票前：{label}。</p>")
        t = flow.get("terminal")
        if t:
            label = f"第{t['after_day']}天" + {"night": "夜晚", "day": "白天", "endgame": "拍刀结算"}[t["phase"]]
            out.append(f"<p><strong>{label}游戏结束；后续不再生成白天投票缺口。</strong></p>")
    for r in facts["registrations"]:
        out.append(f"<section>第{r['day'] or '待核'}天：上警 {r['on_police']}；警下 {r['off_police']}{ev(r['id'])}</section>")
    for b in facts["ballots"]:
        label = {"sheriff":"警徽票","exile":"放逐票","unknown":"类别待核"}[b["kind"]]
        stage = ballot_stage_label(b, facts["ballots"])
        count = str(len(b['eligible_voters'])) + "张选票" if b['eligible_voters'] is not None else "票权待核"
        out.append(f"<section><h2>第{b['day'] or '待核'}天 · {label}{' · '+stage if stage else ''}</h2><p>候选人：{b['candidates']}；票权名单：{b['eligible_voters']}；{count}；缺票：{b['unrecorded_voters']}；平票：{b['tied_candidates']}；公布结果：{b['winner']}</p><table><tr><th>投票人</th><th>投给</th></tr>")
        for v in b["votes"]:
            defaulted = any(a["target"] == b["id"] and v["voter"] in a["voters"] for a in audit.get("rule_applications", []))
            label = "按规则默认弃票" if defaulted else "原文明确弃票" if v["state"] == "abstained" else str(v["target"])+"号"
            confirmed = any(a["target"] == b["id"] and v["voter"] in a["voters"] for a in audit.get("human_confirmations", []))
            out.append(f"<tr><td>{v['voter']}号</td><td>{label}{'（用户人工确认）' if confirmed else ''}</td></tr>")
        out.append("</table>" + ev(b["id"]) + "</section>")
    out.append("<h2>每日放逐结果与缺口</h2>" + "".join(f"<p>第{x['day']}天：{html.escape(x['exile_note'])}</p>" for x in audit.get("day_outcomes", [])))
    for p in audit.get("endgame_phases", []):
        result = {"werewolf_win": "拍刀成功，狼人阵营获胜", "good_win": "拍刀失败，好人阵营获胜", "unknown": "结算待核"}[p["result"]]
        targets = "、".join(str(n)+"号" for n in p["declared_targets"]) or "未明确播报"
        out.append(f"<section><h2>第{p['day'] or '待核'}天 · 狼人拍刀（独立环节）</h2><p>明确目标：{targets}；{result}</p><p>{html.escape(p['note'])}</p>" + "".join(f"<details><summary>拍刀原文</summary><pre>{html.escape(e['quote'])}</pre></details>" for e in p["evidence"]) + "</section>")
    return "".join(out)


def ballot_stage_label(ballot, ballots):
    count = sum(b["day"] == ballot["day"] and b["kind"] == ballot["kind"] for b in ballots)
    if ballot["stage"] == "initial":
        return ("平票前投票" if any(b["day"] == ballot["day"] and b["kind"] == ballot["kind"] and b["stage"] == "pk" for b in ballots)
                else "技能重投前投票") if count > 1 else ""
    return {"pk": "平票PK后再次投票", "revote": "技能触发重新投票", "unknown": "投票衔接待核"}[ballot["stage"]]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-db", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.import_db), ensure_ascii=False, indent=2))
