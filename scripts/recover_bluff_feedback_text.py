"""Recover selected values and comments from a copied offline review page."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re


DECISIONS = {"确认是悍跳": "yes", "确认不是悍跳": "no", "仍无法确定": "uncertain",
             "仅后续天数起跳，请再核查": "later", "有其他意见": "comment", "尚未填写": ""}
DAYS = {"第一天": 1, "第二天（含延期竞选）": 2, "后续天数，请见意见": "later", "尚未确定": None}
ROLES = {"预言家": "预言家", "通灵师": "通灵师", "待定／不适用": None}
SUCCESSES = {"确认成功": True, "确认失败": False, "保留待定": None, "尚未复核": None}
PLACEHOLDER = "可填写正确座位、首日时间点、所跳身份或不同意见。"


def recover_feedback(text: str, items: list[dict]) -> dict:
    indexed = {row["review_id"]: row for row in items}
    blocks = re.split(r"(?m)^(?=20\d\d-\d\d-\d\d 第)", text)[1:]
    timestamp = datetime.now(timezone.utc).isoformat()
    records, seen = [], set()
    for block in blocks:
        ids = re.findall(r"反馈编号：([^\s]+)", block)
        if len(ids) != 1 or ids[0] not in indexed or ids[0] in seen:
            raise ValueError("记录编号未知、缺失或重复，不能自动应用粘贴内容")
        review_id = ids[0]
        seen.add(review_id)
        row = indexed[review_id]
        if not re.search(rf"·\s*{row['seat']}号\s+{re.escape(row['name'])}\s*·", block.splitlines()[0]):
            raise ValueError(f"记录姓名或座位不匹配：{review_id}")
        form = re.search(r"填写本条复核意见\s*复核结论\s*([^\n]+)\s*发生天数\s*([^\n]+)\s*所跳身份\s*([^\n]+)\s*(?:悍跳成功结论\s*([^\n]+)\s*)?其他意见\s*([\s\S]*?)\s*本条草稿已保存\s*$", block)
        if not form:
            raise ValueError(f"填写内容不完整：{review_id}")
        decision, day, role, success, notes = (value.strip() if value else "" for value in form.groups())
        if decision not in DECISIONS or day not in DAYS or role not in ROLES:
            raise ValueError(f"不能识别填写选项：{review_id}")
        if success and success not in SUCCESSES:
            raise ValueError(f"不能识别成功结论选项：{review_id}")
        notes = "" if notes == PLACEHOLDER else notes
        record = {key: row.get(key) for key in ("review_id", "game_id", "bvid", "seat", "name", "physical_role",
                                                "source_fingerprint", "claim_fingerprint", "success_fingerprint")}
        record.update(decision=DECISIONS[decision], claim_day=DAYS[day], claimed_role=ROLES[role], notes=notes,
                      updated_at=timestamp, input_values={"decision": decision, "claim_day": day,
                                                         "claimed_role": role, "manual_success": success,
                                                         "notes": notes},
                      feedback_origin={"kind": "pasted_form_text", "review_id": review_id})
        if success and success != "尚未复核":
            record["manual_success"] = SUCCESSES[success]
        records.append(record)
    declared = re.search(r"本页已填写\s*(\d+)\s*/", text)
    if not records or (declared and int(declared.group(1)) != len(records)):
        raise ValueError("粘贴记录数与页面已填写数量不符，可能未复制完整")
    return {"kind": "s22_bluff_feedback", "schema_version": 1, "season": "S22", "exported_at": timestamp,
            "recovered_from": {"kind": "pasted_form_text", "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
            "records": records}
