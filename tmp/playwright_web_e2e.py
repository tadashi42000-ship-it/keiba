import re
import time
import json
from playwright.sync_api import sync_playwright

BASE_URL = 'http://localhost:8511'
TOP_TAB_NAMES = {
    '📋 出馬表', '📥 情報入力', '🏇 総合予想（馬別）', '🏟️ レース特徴・傾向', 'YOUTUBEから情報入手'
}


def wait_for_main_or_login(page, timeout_sec=120):
    start = time.time()
    while time.time() - start < timeout_sec:
        if page.get_by_role('tab', name=re.compile('情報入力')).count() > 0:
            return 'main'
        if page.locator("input[type='password']").count() > 0:
            return 'login'
        page.wait_for_timeout(500)
    return 'timeout'


def wait_until_main(page, timeout_sec=240):
    start = time.time()
    while time.time() - start < timeout_sec:
        if page.get_by_role('tab', name=re.compile('情報入力')).count() > 0:
            return True
        page.wait_for_timeout(1000)
    return False


def collect_shutuba_horses(page):
    horses = []
    rows = page.locator('table tbody tr')
    n = rows.count()
    for i in range(n):
        cells = rows.nth(i).locator('td')
        if cells.count() >= 3:
            name = cells.nth(2).inner_text().strip()
            if name and name not in {'不明', '---', 'ー'}:
                horses.append(name)
    seen = set()
    uniq = []
    for h in horses:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def parse_int(pattern, text):
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


result = {
    'base_url': BASE_URL,
    'login': None,
    'race_horses_from_shutuba': [],
    'web_button_clicked': False,
    'web_article_count': None,
    'warning_count': 0,
    'warning_lines': [],
    'aggregated_horse_count': None,
    'horse_tabs': [],
    'horse_source_counts': {},
    'summary': {},
    'errors': [],
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.set_viewport_size({'width': 1600, 'height': 1200})
    page.set_default_timeout(120000)

    try:
        page.goto(BASE_URL, wait_until='domcontentloaded')

        state = wait_for_main_or_login(page, timeout_sec=150)
        if state == 'login':
            pw = page.locator("input[type='password']")
            pw.first.fill('7777')
            page.get_by_role('button', name='ログイン').first.click()
            result['login'] = 'submitted'
        elif state == 'main':
            result['login'] = 'already_authenticated'
        else:
            raise RuntimeError('初期画面判定に失敗しました')

        if not wait_until_main(page, timeout_sec=240):
            raise RuntimeError('ログイン後にメイン画面へ遷移しませんでした')

        # 出馬表タブで馬名収集
        page.get_by_role('tab', name=re.compile('出馬表')).first.click()
        page.wait_for_timeout(1500)
        result['race_horses_from_shutuba'] = collect_shutuba_horses(page)

        # 情報入力タブへ
        page.get_by_role('tab', name=re.compile('情報入力')).first.click()
        page.wait_for_timeout(1200)

        # Web一括検索
        web_btn = page.get_by_role('button', name=re.compile('Web\s*一括検索'))
        if web_btn.count() == 0:
            raise RuntimeError('Web一括検索ボタンが見つかりません')
        web_btn.first.click()
        result['web_button_clicked'] = True

        # 処理完了待ち
        start = time.time()
        while time.time() - start < 360:
            body = page.inner_text('body')
            if '検索・解析が完了しました' in body:
                break
            page.wait_for_timeout(2500)

        body_after = page.inner_text('body')
        result['web_article_count'] = parse_int(r'Web記事\s*(\d+)件取得', body_after)
        warnings = [ln.strip() for ln in body_after.splitlines() if 'Web記事の解析をスキップしました' in ln]
        result['warning_count'] = len(warnings)
        result['warning_lines'] = warnings[:20]

        # 総合予想（馬別）タブへ
        page.get_by_role('tab', name=re.compile('総合予想')).first.click()
        page.wait_for_timeout(1500)
        body_tab3 = page.inner_text('body')
        result['aggregated_horse_count'] = parse_int(r'集計完了:\s*(\d+)頭分', body_tab3)

        # 馬タブ名取得
        all_tabs = [t.strip() for t in page.get_by_role('tab').all_inner_texts()]
        horse_tabs = [t for t in all_tabs if t and t not in TOP_TAB_NAMES]
        result['horse_tabs'] = horse_tabs

        # 各馬情報源数
        for h in horse_tabs:
            tab = page.get_by_role('tab', name=h)
            if tab.count() == 0:
                continue
            tab.first.click()
            page.wait_for_timeout(800)
            txt = page.inner_text('body')
            sc = parse_int(r'情報源数\s*(\d+)件', txt)
            result['horse_source_counts'][h] = sc

        sc_values = [v for v in result['horse_source_counts'].values() if isinstance(v, int)]
        result['summary'] = {
            'horses_in_shutuba': len(result['race_horses_from_shutuba']),
            'horses_in_result_tabs': len(result['horse_tabs']),
            'horses_with_source_count_ge_1': sum(1 for v in sc_values if v >= 1),
            'horses_with_source_count_eq_0': sum(1 for v in sc_values if v == 0),
        }

        page.screenshot(path='tmp/playwright_web_e2e_result.png', full_page=True)

    except Exception as e:
        result['errors'].append(f'{type(e).__name__}: {e}')
        page.screenshot(path='tmp/playwright_web_e2e_error.png', full_page=True)
    finally:
        context.close()
        browser.close()

print(json.dumps(result, ensure_ascii=False, indent=2))
