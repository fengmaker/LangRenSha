"""Run browser checks for an exported game review HTML page.

Usage: python tests/check_game_review_page.py PAGE.html --output-dir QA_DIR
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright


FORMAT = 'masters-incremental-review-v2'
LEGACY_FORMAT = 'masters-incremental-review-v1'
CARD_RE = re.compile(r'<main class="game-card" data-review-id="[^"]+" hidden>.*?</main>', re.DOTALL)
DATA_RE = re.compile(r'(<script id="review-data" type="application/json">)(.*?)(</script>)', re.DOTALL)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def single_and_multi_fixtures(source: str, temp: Path) -> tuple[Path, Path]:
    cards = CARD_RE.findall(source)
    match = DATA_RE.search(source)
    require(bool(cards) and match is not None, 'HTML 缺少对局卡片或 review-data')
    data = json.loads(match.group(2))
    require(len(cards) == len(data.get('games', [])), '卡片数量与 review-data 对局数量不一致')

    single = source.replace(''.join(CARD_RE.findall(source)), cards[0], 1)
    single_data = {**data, 'games': data['games'][:1]}
    single = DATA_RE.sub(lambda m: m.group(1) + json.dumps(single_data, ensure_ascii=False) + m.group(3), single, count=1)

    first_card = cards[0]
    first_game = data['games'][0]
    second_id = first_game['review_id'] + ':qa-second'
    second_card = first_card.replace(f'data-review-id="{first_game["review_id"]}"',
                                     f'data-review-id="{second_id}"', 1)
    second_game = {**first_game, 'review_id': second_id, 'bvid': first_game['bvid'] + 'QA',
                   'cid': first_game['cid'] + 1, 'page': first_game['page'] + 1,
                   'candidate_sha256': first_game['candidate_sha256'] + '-qa-second',
                   'source_sha256': first_game['source_sha256'] + '-qa-second',
                   'label': first_game['label'] + '（QA 第二局）'}
    multi = single.replace(cards[0], cards[0] + second_card, 1)
    multi_data = {**data, 'games': [first_game, second_game]}
    multi = DATA_RE.sub(lambda m: m.group(1) + json.dumps(multi_data, ensure_ascii=False) + m.group(3), multi, count=1)

    single_path, multi_path = temp / 'single.html', temp / 'multi.html'
    single_path.write_text(single, encoding='utf-8')
    multi_path.write_text(multi, encoding='utf-8')
    return single_path, multi_path


def identity(game: dict) -> dict:
    return {key: game[key] for key in ('review_id', 'bvid', 'cid', 'page', 'candidate_sha256', 'source_sha256')}


def complete_bluffs(yes: tuple[int, str] | None = None, no: tuple[int, str] | None = None,
                    uncertain: tuple[int, str] | None = None) -> list[dict]:
    rows = []
    choices = {seat: (decision, success) for seat, decision, success in (
        (yes[0], 'yes', yes[1]) if yes else (0, '', ''),
        (no[0], 'no', '') if no else (0, '', ''),
        (uncertain[0], 'uncertain', '') if uncertain else (0, '', ''),
    ) if seat}
    for seat in range(1, 13):
        decision, success = choices.get(seat, ('', ''))
        rows.append({'seat': seat, 'decision': decision, 'success': success})
    return rows


def write_payload(path: Path, *, format_name: str, season: str, game: dict,
                  note: str, reviewed: bool, bluffs: list[dict] | None) -> None:
    item = {**identity(game), 'note': note, 'reviewed': reviewed}
    if bluffs is not None:
        item['bluffs'] = bluffs
    path.write_text(json.dumps({'format': format_name, 'season': season, 'games': [item]},
                               ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def page_metadata(page) -> dict:
    return page.evaluate("""() => JSON.parse(document.querySelector('#review-data').textContent)""")


def current_ui(page) -> dict:
    return page.evaluate("""() => {
      const card = document.querySelector('[data-review-id]:not([hidden])');
      return {
        note: card.querySelector('[data-note]').value,
        reviewed: card.querySelector('[data-reviewed]').checked,
        rows: Array.from(card.querySelectorAll('[data-bluff-row]')).map(row => ({
          seat: row.querySelector('[data-bluff-person]').value,
          success: row.querySelector('[data-bluff-success]').value,
          disabled: row.querySelector('[data-bluff-success]').disabled
        })),
        decisions: card.querySelector('[data-other-bluff-decisions]').textContent,
        saved: Object.keys(localStorage).sort().map(key => [key, localStorage.getItem(key)])
      };
    }""")


def export_json(page, path: Path) -> dict:
    with page.expect_download() as info:
        page.locator('#export').click()
    info.value.save_as(path)
    return json.loads(path.read_text(encoding='utf-8'))


def import_json(page, path: Path) -> None:
    page.locator('#import-file').set_input_files(path)


def check_page_behavior(browser, source_path: Path, output_dir: Path, checks: list[str]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(source_path.resolve().as_uri(), wait_until='load')
    metadata = page_metadata(page)
    require(metadata.get('games'), '页面没有对局')
    game = metadata['games'][0]
    card = page.locator(f'[data-review-id="{game["review_id"]}"]')
    person_selects = card.locator('[data-bluff-person]')
    success_selects = card.locator('[data-bluff-success]')

    require(person_selects.count() == 1, '默认悍跳人空白行数量不是 1')
    require(person_selects.first.input_value() == '', '默认悍跳人未保持空白')
    require(person_selects.first.locator('option').count() == 13, '默认悍跳候选不是 12 席加空白项')
    require([person_selects.first.locator('option').nth(i).get_attribute('value') for i in range(1, 13)] ==
            [str(seat) for seat in range(1, 13)], '候选席位不是 1 至 12 号')
    require(success_selects.count() == 1 and success_selects.first.is_disabled(), '默认成功选择没有禁用')
    checks.append('默认一条空白悍跳行、12 个候选席位、成功选择禁用')

    person_selects.first.select_option('1')
    require(not success_selects.first.is_disabled(), '选择悍跳人后成功选择仍禁用')
    success_selects.first.select_option('success')
    person_selects.first.select_option('4')
    require(success_selects.first.input_value() == '' and not success_selects.first.is_disabled(),
            '更换悍跳人后成功选择没有清空或重新启用')
    success_selects.first.select_option('failure')
    person_selects.first.select_option('')
    require(success_selects.first.is_disabled() and success_selects.first.input_value() == '',
            '清空悍跳人后成功选择没有清空并禁用')
    checks.append('选择、更换和清空悍跳人时正确联动成功选择')

    person_selects.first.select_option('1')
    card.locator('[data-add-bluff]').click()
    require(person_selects.count() == 2, '添加按钮没有添加第二行')
    second_person = person_selects.nth(1)
    require(second_person.locator('option[value="1"]').evaluate('(option) => option.disabled'),
            '已选席位仍可在其他行重复选择')
    require(second_person.input_value() == '', '新增行默认应保持空白')
    second_person.select_option('2')
    require(person_selects.count() == 2 and person_selects.nth(0).input_value() == '1' and
            person_selects.nth(1).input_value() == '2', '多行选择没有保留两名不同悍跳人')
    card.locator('[data-bluff-row]').nth(1).locator('[data-remove-bluff]').click()
    require(person_selects.count() == 1 and person_selects.first.input_value() == '1',
            '删除第二行后没有保留第一行')
    checks.append('支持添加多人、阻止重复席位并删除指定行')

    card.locator('[data-note]').fill('QA 浏览器验证草稿')
    card.locator('[data-reviewed]').check()
    success_selects.first.select_option('success')
    exported_path = output_dir / 'game_review_export.json'
    exported = export_json(page, exported_path)
    require(exported.get('format') == FORMAT and len(exported.get('games', [])) == len(metadata['games']),
            'JSON 导出格式或对局数量不正确')
    exported_first = next(row for row in exported['games'] if row['review_id'] == game['review_id'])
    require(len(exported_first.get('bluffs', [])) == 12 and
            {row['seat'] for row in exported_first['bluffs']} == set(range(1, 13)),
            'JSON 导出没有完整包含 12 席悍跳决定')
    require(exported_first['note'] == 'QA 浏览器验证草稿' and exported_first['reviewed'] is True,
            'JSON 导出没有保留 note/reviewed')
    require(exported_first['bluffs'][0] == {'seat': 1, 'decision': 'yes', 'success': 'success'},
            'JSON 导出的悍跳人或成功状态不正确')
    for row in exported['games'][1:]:
        require(len(row.get('bluffs', [])) == 12, 'JSON 导出中其他对局没有完整 12 席')
    checks.append('JSON 导出保留完整 12 席及 note/reviewed')

    page.reload(wait_until='load')
    card = page.locator(f'[data-review-id="{game["review_id"]}"]')
    require(card.locator('[data-note]').input_value() == 'QA 浏览器验证草稿' and
            card.locator('[data-reviewed]').is_checked(), '刷新后 note 或 reviewed 未恢复')
    require(card.locator('[data-bluff-person]').count() == 1 and
            card.locator('[data-bluff-person]').first.input_value() == '1' and
            card.locator('[data-bluff-success]').first.input_value() == 'success',
            '刷新后悍跳选择未恢复')
    checks.append('刷新后草稿、复核状态和成功选择恢复')

    v2 = output_dir / 'fixture_v2.json'
    write_payload(v2, format_name=FORMAT, season=metadata['season'], game=game,
                  note='v2 导入草稿', reviewed=True,
                  bluffs=complete_bluffs(yes=(5, 'failure'), no=(2, ''), uncertain=(3, '')))
    import_json(page, v2)
    page.wait_for_function("document.querySelector('#status').textContent.includes('已导入1局')")
    card = page.locator(f'[data-review-id="{game["review_id"]}"]')
    require(card.locator('[data-bluff-person]').count() == 1 and
            card.locator('[data-bluff-person]').first.input_value() == '5' and
            card.locator('[data-bluff-success]').first.input_value() == 'failure',
            'v2 导入后 yes 悍跳未恢复')
    require('2号：未悍跳' in card.locator('[data-other-bluff-decisions]').inner_text() and
            '3号：悍跳待定' in card.locator('[data-other-bluff-decisions]').inner_text(),
            'v2 导入没有保留 no/uncertain 悍跳决定')
    v2_export = export_json(page, output_dir / 'game_review_v2_import_roundtrip.json')
    v2_rows = next(row for row in v2_export['games'] if row['review_id'] == game['review_id'])['bluffs']
    require(v2_rows[1]['decision'] == 'no' and v2_rows[2]['decision'] == 'uncertain' and
            v2_rows[4] == {'seat': 5, 'decision': 'yes', 'success': 'failure'},
            'v2 导入/导出往返改变了 no、uncertain 或 yes 决定')
    checks.append('v2 导入恢复 yes 并保留 no/uncertain 决定')

    card.locator('[data-bluff-person]').first.select_option('4')
    card.locator('[data-bluff-success]').first.select_option('failure')
    v1 = output_dir / 'fixture_v1.json'
    write_payload(v1, format_name=LEGACY_FORMAT, season=metadata['season'], game=game,
                  note='v1 兼容导入', reviewed=False, bluffs=None)
    import_json(page, v1)
    page.wait_for_function("document.querySelector('#status').textContent.includes('已导入1局')")
    require(card.locator('[data-bluff-person]').first.input_value() == '4' and
            card.locator('[data-bluff-success]').first.input_value() == 'failure',
            'v1 导入清除了已有 yes 悍跳选择')
    checks.append('v1 导入保留已有悍跳选择')

    before_bad_import = current_ui(page)
    invalid = output_dir / 'fixture_bad_version.json'
    write_payload(invalid, format_name='unsupported-review-v99', season=metadata['season'], game=game,
                  note='不应导入', reviewed=True, bluffs=complete_bluffs())
    import_json(page, invalid)
    page.wait_for_function("document.querySelector('#status').textContent.includes('导入未完成')")
    require('格式或赛季不匹配' in page.locator('#status').inner_text(), '错误版本没有明确拒绝')
    require(current_ui(page) == before_bad_import, '错误版本导入改变了当前草稿')
    checks.append('拒绝错误版本且当前草稿保持不变')

    image_button = card.locator('[data-enlarge]').first
    require(image_button.count() == 1, '身份截图放大按钮不存在')
    image_button.click()
    require(page.locator('#image-dialog').evaluate('(dialog) => dialog.open'), '点击身份截图没有打开放大对话框')
    require(page.locator('#large-image').get_attribute('src') == card.locator('[data-enlarge] img').first.get_attribute('src'),
            '放大对话框没有显示对应身份截图')
    page.locator('#close-image').click()
    require(not page.locator('#image-dialog').evaluate('(dialog) => dialog.open'), '身份截图对话框没有关闭')
    checks.append('身份截图可放大并关闭')

    if len(metadata['games']) > 1:
        picker = page.locator('#game-picker')
        require(not page.locator('#game-navigation').is_hidden() and picker.locator('option').count() == len(metadata['games']),
                '实际多局页面没有显示全部对局导航选项')
        page.locator('#next-game').click()
        require(page.locator(f'[data-review-id="{metadata["games"][1]["review_id"]}"]').is_visible(),
                '实际多局页面的下一局没有切换到第二局')
        picker.select_option(value=game['review_id'])
        require(card.is_visible(), '实际多局页面的下拉框没有切回第一局')
        checks.append('实际多局页面支持下一局和下拉切换')
    else:
        require(page.locator('#game-navigation').is_hidden(), '实际单局页面错误显示对局导航')
        checks.append('实际单局页面不显示对局导航')

    context.close()
    return metadata, errors


def check_navigation(browser, single_path: Path, multi_path: Path, checks: list[str]) -> list[str]:
    errors: list[str] = []
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(single_path.as_uri(), wait_until='load')
    require(page.locator('[data-review-id]').count() == 1 and page.locator('#game-navigation').is_hidden(),
            '单局页面导航显示异常')
    checks.append('单局页面不显示对局切换控件')

    page.goto(multi_path.as_uri(), wait_until='load')
    navigation = page.locator('#game-navigation')
    picker = page.locator('#game-picker')
    require(page.locator('[data-review-id]').count() == 2 and not navigation.is_hidden() and picker.locator('option').count() == 2,
            '多局页面没有显示两个对局切换选项')
    cards = page.locator('[data-review-id]')
    require(not cards.nth(0).is_hidden() and cards.nth(1).is_hidden(), '多局页面默认显示对局不正确')
    page.locator('#next-game').click()
    require(cards.nth(0).is_hidden() and not cards.nth(1).is_hidden() and picker.input_value().endswith(':qa-second'),
            '下一局没有切换到第二局')
    page.locator('#previous-game').click()
    require(not cards.nth(0).is_hidden() and cards.nth(1).is_hidden(), '上一局没有切回第一局')
    picker.select_option(label=picker.locator('option').nth(1).inner_text())
    require(cards.nth(1).is_visible(), '对局下拉框没有切换到指定对局')
    checks.append('多局页面支持上一局、下一局和下拉切换')
    context.close()
    return errors


def capture_screenshots(browser, source_path: Path, output_dir: Path, checks: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(source_path.resolve().as_uri(), wait_until='load')
    page.screenshot(path=str(output_dir / 'game_review_desktop_1440.png'), full_page=True)
    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '1440px 桌面页面出现横向溢出')
    page.set_viewport_size({'width': 390, 'height': 844})
    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '390px 手机页面出现横向溢出')
    page.screenshot(path=str(output_dir / 'game_review_mobile_390.png'), full_page=True)
    checks.append('1440px 桌面与 390px 手机页面无横向溢出并已截图')
    context.close()
    return ['game_review_desktop_1440.png', 'game_review_mobile_390.png'], errors


def run(page_path: Path, output_dir: Path) -> dict:
    page_path = page_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    require(page_path.is_file(), f'HTML 文件不存在：{page_path}')
    source = page_path.read_text(encoding='utf-8')
    checks: list[str] = []
    browser_errors: list[str] = []
    with TemporaryDirectory(prefix='game-review-page-qa-') as temp_dir, sync_playwright() as playwright:
        single_path, multi_path = single_and_multi_fixtures(source, Path(temp_dir))
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        try:
            metadata, page_errors = check_page_behavior(browser, page_path, output_dir, checks)
            browser_errors.extend(page_errors)
            browser_errors.extend(check_navigation(browser, single_path, multi_path, checks))
            screenshots, screenshot_errors = capture_screenshots(browser, page_path, output_dir, checks)
            browser_errors.extend(screenshot_errors)
        finally:
            browser.close()
    require(not browser_errors, '浏览器 JavaScript 错误：' + ' | '.join(browser_errors))
    report = {
        'status': 'passed',
        'source_html': page_path.as_posix(),
        'season': metadata['season'],
        'games_in_source': len(metadata['games']),
        'checks': checks,
        'browser_errors': browser_errors,
        'screenshots': screenshots,
        'exports': ['game_review_export.json', 'game_review_v2_import_roundtrip.json'],
        'single_and_multi_navigation': True,
        'desktop_1440_mobile_390_no_overflow': True,
    }
    (output_dir / 'game_review_page_qa.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', type=Path, help='render_review_page 生成的实际 HTML 页面')
    parser.add_argument('--output-dir', type=Path, required=True, help='截图、JSON 导出和验收报告目录')
    args = parser.parse_args()
    print(json.dumps(run(args.html, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
