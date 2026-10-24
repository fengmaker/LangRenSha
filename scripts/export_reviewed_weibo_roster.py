"""Deduplicate human-reviewed schedule photo names with traceable corrections."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


ENTERTAINMENT_DATE = "2026-07-03"
EXCLUSION_REASON = "仅在2026-07-03的6+6娱乐赛出现，合计排班日数为1；按用户要求移出参赛汇总名单"


def clean(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def relative(path: Path, directory: Path) -> str:
    return Path(os.path.relpath(path.resolve(), directory.resolve())).as_posix()


def export(review_file: Path, evidence_file: Path, output_dir: Path) -> dict:
    input_hash = hashlib.sha256(review_file.read_bytes()).hexdigest()
    with review_file.open(encoding="utf-8-sig", newline="") as stream:
        reviews = list(csv.DictReader(stream))
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    pictures = evidence["pictures"]
    reviewed = {row["照片编号"]: row for row in reviews}
    if len(reviewed) != len(reviews) or set(reviewed) != {p["id"] for p in pictures}:
        raise ValueError("Review IDs must be unique and cover exactly the evidence pictures")

    explicit_targets: dict[str, set[str]] = defaultdict(set)
    row_names: dict[str, str] = {}
    approved = set()
    for picture in pictures:
        row = reviewed[picture["id"]]
        if row["图片SHA256"] != picture["sha256"] or row["赛季"] != picture["season"]:
            raise ValueError(f"Review evidence mismatch: {picture['id']}")
        if clean(row["图上名字_候选"]) != picture["name"]:
            raise ValueError(f"Original candidate changed outside correction field: {picture['id']}")
        status = row["人工确认"]
        if status == "已修正":
            name = clean(row["修正名字"])
            if not name:
                raise ValueError(f"Correction missing for {picture['id']}")
            explicit_targets[clean(row["图上名字_候选"])].add(name)
        elif status == "确认无误":
            name = clean(row["图上名字_候选"])
        elif status == "待确认":
            name = clean(row["图上名字_候选"])
        else:
            raise ValueError(f"Unresolved or unknown human status for {picture['id']}: {status}")
        final = clean(row["确认后的名字"])
        if status in {"确认无误", "已修正"}:
            if final != name:
                raise ValueError(f"Final-name fields disagree for {picture['id']}")
            approved.add(name)
        elif final:
            raise ValueError(f"Pending row unexpectedly has a final name: {picture['id']}")
        row_names[picture["id"]] = name
    if any(len(names) != 1 for names in explicit_targets.values()):
        raise ValueError("Conflicting explicit corrections for the same original name")
    aliases = {source: next(iter(targets)) for source, targets in explicit_targets.items()}

    def canonical(name: str) -> str:
        visited = set()
        while name in aliases and aliases[name] != name:
            if name in visited:
                raise ValueError("Alias cycle in human corrections")
            visited.add(name)
            name = aliases[name]
        return name

    approved = {canonical(name) for name in approved}
    groups = defaultdict(list)
    mapping = []
    for picture in pictures:
        row = reviewed[picture["id"]]
        name = canonical(row_names[picture["id"]])
        if name not in approved:
            raise ValueError(f"Name has no human-confirmed evidence: {name}")
        groups[name].append(picture)
        original = clean(row["图上名字_候选"])
        if row["人工确认"] == "待确认":
            basis = "同名已有人工确认记录；此照片原状态保持待确认"
        elif row["人工确认"] == "已修正":
            basis = "采用用户修正"
        elif name != original:
            basis = "应用用户对同一原名的明确修正"
        else:
            basis = "人工确认无误；同名合并"
        mapping.append({"照片编号": picture["id"], "原图名字": original, "复核行名字": row_names[picture["id"]],
            "去重后姓名": name, "原人工确认状态": row["人工确认"], "归并依据": basis,
            "赛季": picture["season"], "图片SHA256": picture["sha256"]})

    ordered = sorted(groups, key=lambda name: min(p["id"] for p in groups[name]))
    people = []
    for number, name in enumerate(ordered, 1):
        photos = groups[name]
        dates = {season: sorted({o["date"] for p in photos if p["season"] == season for o in p["occurrences"]})
                 for season in ["S22", "S23"]}
        all_dates = sorted(set(dates["S22"]) | set(dates["S23"]))
        people.append({"序号": number, "姓名": name, "参与赛季": "、".join(s for s in ["S22", "S23"] if dates[s]),
            "S22排班日数": len(dates["S22"]), "S23排班日数": len(dates["S23"]), "合计排班日数": len(all_dates),
            "首次排班日期": all_dates[0], "最近排班日期": all_dates[-1],
            "原图名字": "、".join(sorted({p["name"] for p in photos})), "不同照片数": len(photos),
            "照片编号": "；".join(p["id"] for p in photos), "排班日期": "；".join(all_dates)})
    before_exclusion_count = len(people)
    excluded_people = [p for p in people if p["合计排班日数"] == 1 and p["排班日期"] == ENTERTAINMENT_DATE]
    excluded_names = {p["姓名"] for p in excluded_people}
    people = [p for p in people if p["姓名"] not in excluded_names]
    for number, person in enumerate(people, 1):
        person["序号"] = number
    ordered = [p["姓名"] for p in people]
    for row in mapping:
        excluded = row["去重后姓名"] in excluded_names
        row["纳入参赛名单"] = "否" if excluded else "是"
        row["排除原因"] = EXCLUSION_REASON if excluded else ""
    sets = {season: [p["姓名"] for p in people if p[f"{season}排班日数"]] for season in ["S22", "S23"]}
    both = [n for n in ordered if n in sets["S22"] and n in sets["S23"]]
    only_s22 = [n for n in ordered if n in sets["S22"] and n not in sets["S23"]]
    only_s23 = [n for n in ordered if n in sets["S23"] and n not in sets["S22"]]
    summary = {"as_of": "2026-10-20", "scope": "已复核的S22/S23大师赛排班照片；剔除仅在7月3日6+6娱乐赛出现一次的人",
        "first_schedule_date": min(p["首次排班日期"] for p in people),
        "last_schedule_date": max(p["最近排班日期"] for p in people),
        "unique_people": len(people), "season_people": {s: len(names) for s, names in sets.items()},
        "unique_people_before_exclusion": before_exclusion_count,
        "excluded_people_count": len(excluded_people), "excluded_people_names": [p["姓名"] for p in excluded_people],
        "exclusion_rule": {"only_schedule_date": ENTERTAINMENT_DATE, "total_schedule_days": 1, "reason": EXCLUSION_REASON},
        "included_photo_rows": sum(row["纳入参赛名单"] == "是" for row in mapping),
        "both_seasons": len(both), "s22_only": len(only_s22), "s23_only": len(only_s23),
        "photo_rows": len(pictures), "image_occurrences": sum(len(p["occurrences"]) for p in pictures),
        "schedule_posts": len({o["url"] for p in pictures for o in p["occurrences"]}),
        "source_human_statuses": dict(Counter(r["人工确认"] for r in reviews)), "explicit_name_merges": aliases,
        "pending_photo_ids_with_confirmed_name": [r["照片编号"] for r in reviews if r["人工确认"] == "待确认"],
        "every_person_has_direct_human_confirmed_evidence": True,
        "review_source": relative(review_file, output_dir), "review_source_sha256": input_hash,
        "picture_evidence_source": relative(evidence_file, output_dir),
        "count_definition": "排班日数为官方排班配图出现的不同日期数，不是实际对局局数或座位统计。"}
    assert len(set(ordered)) == len(ordered)
    assert len(sets["S22"]) + len(sets["S23"]) - len(both) == len(people)
    assert len(both) + len(only_s22) + len(only_s23) == len(people)
    assert hashlib.sha256(review_file.read_bytes()).hexdigest() == input_hash

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_name = "京城大师赛_S22至今_参赛人名总表.csv"
    try:
        write_csv(output_dir / csv_name, list(people[0]), people)
    except PermissionError:
        csv_name = "京城大师赛_S22至今_参赛人名总表_更新.csv"
        write_csv(output_dir / csv_name, list(people[0]), people)
        summary["primary_csv_write_pending"] = True
    summary["csv_file"] = csv_name
    write_csv(output_dir / "人名去重_照片映射.csv", list(mapping[0]), mapping)
    exclusion_rows = [{**p, "排除原因": EXCLUSION_REASON} for p in excluded_people]
    write_csv(output_dir / "已排除_仅7月3日娱乐赛人员.csv", list(people[0]) + ["排除原因"], exclusion_rows)
    for filename, names in [("京城大师赛_S22至今_参赛人名名单.txt", ordered), ("S22_参赛人名名单.txt", sets["S22"]),
                            ("S23_参赛人名名单.txt", sets["S23"])]:
        (output_dir / filename).write_text("\n".join(names) + "\n", encoding="utf-8")
    data = {"schema_version": 1, "summary": summary, "people": people, "excluded_people": exclusion_rows,
            "groups": {"both": both, "s22_only": only_s22, "s23_only": only_s23}, "photo_name_mapping": mapping}
    (output_dir / "参赛人名名单.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = f"""# 京城大师赛 S22 至今参赛人名名单

按用户已复核的排班照片去重，共 **{len(people)} 人**：S22 **{len(sets['S22'])} 人**、S23 **{len(sets['S23'])} 人**，其中两季共有 **{len(both)} 人**。

资料采集窗口截至2026-10-20；本批79份排班公告的实际赛日为 **{summary['first_schedule_date']} 至 {summary['last_schedule_date']}**。范围含S22/S23表演赛、正赛和决赛周的排班照片。名单记录照片中的排班选手；未将正文中仅以解说、法官身份出现且没有选手照片的人加入参赛名单。排班日数不是实际对局局数。

按用户要求，已剔除总排班日数为1且唯一日期为2026-07-03的人，共{len(excluded_people)}人：{'、'.join(p['姓名'] for p in excluded_people)}。该日为6+6娱乐赛。其余选手原有排班日期与日数保持不变。

- [完整人名名单：每人一行](京城大师赛_S22至今_参赛人名名单.txt)
- [人名总表 CSV]({csv_name})：姓名、参与赛季、分季排班日数、首次和最近排班日期、照片编号。
- [S22名单](S22_参赛人名名单.txt)、[S23名单](S23_参赛人名名单.txt)
- [照片对应与归并依据](人名去重_照片映射.csv)、[完整结构化结果](参赛人名名单.json)
- [本次排除人员及原因](已排除_仅7月3日娱乐赛人员.csv)

采用[用户复核CSV]({relative(review_file, output_dir)})，保留原文件不变。按明确修正统一“鲸鱼→董鲸鱼”“龙崽→老崔”，其余按确认后的名字精确去重，保留英文大小写，不推测其他别名。原文件中210张确认无误、4张已修正；另3张（P0199、P0200、P0201）仍为待确认，其名字陈俊洁、鬼鬼、Ted均已有同名人工确认记录。总名单中每个名字都有直接人工确认依据；待确认照片的原状态保留在对应表中。

两季都有（{len(both)}人）：{'、'.join(both)}。

仅在S22照片中出现（{len(only_s22)}人）：{'、'.join(only_s22)}。

仅在S23照片中出现（{len(only_s23)}人）：{'、'.join(only_s23)}。
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=Path("data/weibo/2026-05-26_2026-10-20/人名复核/S22-S23_照片人名_人工复核.csv"))
    parser.add_argument("--evidence", type=Path, default=Path("data/weibo/2026-05-26_2026-10-20/人名复核/照片人名_候选结果.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/weibo/2026-05-26_2026-10-20/参赛名单"))
    args = parser.parse_args()
    print(json.dumps(export(args.review, args.evidence, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
