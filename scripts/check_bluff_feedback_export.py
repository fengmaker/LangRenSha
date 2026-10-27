"""Exercise the real S22 feedback forms in a disposable offline browser page."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PAGE = ROOT / "data/exports/S22_悍跳推断与复核.html"
TEMPLATE = ROOT / "scripts/templates/bluff_review_form.html"
RUNTIME = ROOT / "website/web/src/lib/bluff-feedback-runtime.js"
REVIEW_ID = "BV119TJ6pEtC:10"


def build_fixture(path: Path) -> int:
    source = SOURCE_PAGE.read_text(encoding="utf-8")
    cards = re.findall(r"<article\b.*?</article>", source, flags=re.DOTALL)
    if len(cards) != 586:
        raise AssertionError(f"Expected the published 586 review cards; found {len(cards)}")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__SUMMARY__", "Browser regression fixture; source cards are unchanged.")
    html = html.replace("__NOTES__", "")
    html = html.replace("__CARDS__", "\n".join(cards))
    html = html.replace("__RUNTIME__", RUNTIME.read_text(encoding="utf-8"))
    html = html.replace("__OPTIONS__", json.dumps({"season": "S22", "inference_version": "browser-regression"}))
    if "__CARDS__" in html or "__RUNTIME__" in html or "__OPTIONS__" in html:
        raise AssertionError("Offline feedback fixture has unresolved template markers")
    path.write_text(html, encoding="utf-8")
    return len(cards)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="bluff-feedback-browser-") as folder:
        page_path = Path(folder) / "review.html"
        card_count = build_fixture(page_path)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            errors: list[str] = []
            downloads = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("download", lambda download: downloads.append(download))
            page.goto(page_path.as_uri(), wait_until="load")
            target = page.locator(f'form[data-review-id="{REVIEW_ID}"]')
            if target.count() != 1:
                raise AssertionError(f"The pasted review entry {REVIEW_ID} was not found in the offline page")

            # The attached review shows an explicit yes conclusion with its role/day still undetermined.
            target.locator('select[name="decision"]').select_option("yes")
            target.locator('select[name="claim_day"]').select_option("")
            target.locator('select[name="claimed_role"]').select_option("")
            target.locator('textarea[name="notes"]').fill("这局10号荣耀悍跳")

            visible_forms = page.locator("article:visible form.bluff-feedback-form").all()
            other_forms = [form for form in visible_forms if form.get_attribute("data-review-id") != REVIEW_ID]
            if len(other_forms) < 3:
                raise AssertionError("The review page needs three visible forms for independent preservation checks")
            role_missing, day_missing, notes_only = other_forms[:3]
            role_missing_id = role_missing.get_attribute("data-review-id")
            role_missing.locator('select[name="decision"]').select_option("yes")
            role_missing.locator('select[name="claim_day"]').select_option("1")
            role_missing.locator('select[name="claimed_role"]').select_option("")
            role_missing.locator('textarea[name="notes"]').fill("回归测试：只有所跳身份待补。")
            day_missing_id = day_missing.get_attribute("data-review-id")
            day_missing.locator('select[name="decision"]').select_option("yes")
            day_missing.locator('select[name="claim_day"]').select_option("")
            day_missing.locator('select[name="claimed_role"]').select_option("预言家")
            day_missing.locator('textarea[name="notes"]').fill("回归测试：只有发生天数待补。")
            notes_only_id = notes_only.get_attribute("data-review-id")
            notes_only.locator('textarea[name="notes"]').fill("回归测试：保留这条未完成意见。")

            page.locator("[data-feedback-export]").click()
            page.wait_for_timeout(250)
            if not downloads:
                status = page.locator("[data-feedback-status]").inner_text()
                raise AssertionError(
                    "Export should produce a feedback JSON containing incomplete but explicit opinions; "
                    f"browser started no download. Status: {status}"
                )
            exported = json.loads(Path(downloads[-1].path()).read_text(encoding="utf-8"))
            rows = {row["review_id"]: row for row in exported["records"]}
            expected_ids = {REVIEW_ID, role_missing_id, day_missing_id, notes_only_id}
            if not expected_ids.issubset(rows):
                raise AssertionError("Export omitted a filled review opinion")
            yes_row = rows[REVIEW_ID]
            if (yes_row["decision"], yes_row["claimed_role"], yes_row["claim_day"]) != ("yes", None, None):
                raise AssertionError("Export changed the explicit conclusion or auto-filled unknown metadata")
            if (rows[role_missing_id]["decision"], rows[role_missing_id]["claimed_role"], rows[role_missing_id]["claim_day"]) != ("yes", None, 1):
                raise AssertionError("Export blocked or changed a yes opinion missing only its role")
            if (rows[day_missing_id]["decision"], rows[day_missing_id]["claimed_role"], rows[day_missing_id]["claim_day"]) != ("yes", "预言家", None):
                raise AssertionError("Export blocked or changed a yes opinion missing only its day")
            if rows[notes_only_id]["decision"] != "" or rows[notes_only_id]["notes"] != "回归测试：保留这条未完成意见。":
                raise AssertionError("Export converted an unconfirmed draft into a conclusion or lost its note")
            status = page.locator("[data-feedback-status]").inner_text()
            if "3 条“确认是悍跳”" not in status or "空缺字段保持未确定" not in status or "未填写不代表确认" not in status:
                raise AssertionError("Export did not clearly disclose missing yes-record metadata")
            if "身份或天数待补" not in target.locator("[data-feedback-row-status]").inner_text():
                raise AssertionError("The incomplete yes form did not explain its missing metadata")

            # Also verify a user-visible JSON fallback when the browser rejects Blob downloads.
            page.evaluate("() => { URL.createObjectURL = function() { throw new Error('simulated blocked download'); }; }")
            page.locator("[data-feedback-export]").click()
            fallback = page.locator("[data-feedback-copy-fallback]")
            if fallback.count() != 1 or fallback.is_hidden():
                raise AssertionError("Blob download failure did not reveal a copyable JSON fallback")
            fallback_json = fallback.locator("textarea").input_value()
            if json.loads(fallback_json)["records"] != exported["records"]:
                raise AssertionError("Copy fallback did not contain the complete current feedback JSON")
            if fallback.locator("textarea").get_attribute("readonly") is None:
                raise AssertionError("The fallback JSON must stay intact while the user selects and copies it")
            page.evaluate("() => { document.querySelector('[data-feedback-copy-fallback]').hidden = true; }")
            page.locator("[data-feedback-copy-open]").click()
            if fallback.is_hidden() or json.loads(fallback.locator("textarea").input_value())["records"] != exported["records"]:
                raise AssertionError("The always-visible copy action did not reveal the current complete JSON")
            fallback.locator("[data-feedback-copy]").click()
            if fallback.is_hidden():
                raise AssertionError("The copy action hid the JSON fallback")
            if errors:
                raise AssertionError("Browser reported page errors: " + " | ".join(errors))
            pending_count = page.locator('article[data-pending="1"]').count()
            visible_count = page.locator("article:visible").count()
            expected_visible = pending_count if pending_count else card_count
            if visible_count != expected_visible:
                raise AssertionError(
                    f"Offline default filter should show {expected_visible} cards, found {visible_count}"
                )
            browser.close()
            print(json.dumps({
                "status": "passed",
                "source_review_cards": card_count,
                "default_visible_cards": visible_count,
                "pending_cards": pending_count,
                "reproduced_review_id": REVIEW_ID,
                "exported_records": len(rows),
                "yes_with_missing_role_and_day_preserved": True,
                "yes_with_single_missing_role_or_day_preserved": True,
                "notes_only_draft_preserved_without_confirmation": True,
                "blob_failure_copy_fallback": True,
                "browser_errors": errors,
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
