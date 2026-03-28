import re
import time
import json
from playwright.sync_api import sync_playwright, TimeoutError

BASE_URL = 'http://localhost:8511'
TOP_TABS = {'出馬表', '情報入力', '総合予想（馬別）', 'レース特徴・傾向', 'YOUTUBEから情報入手'}


def click_if_exists(locator):
    if locator.count() > 0:
        locator.first.click()
        return True
    return False


def get_body_text(page):
    try:
        return page.inner_text('body')
    except Exception:
        return ''


def collect_horses_from_table(page):
    horses = []
    rows = page.locator('table tbody tr')
    cnt = rows.count()
    for i in range(cnt):
        cells = rows.nth(i).locator('td')
        if cells.count() >= 3:
            name = cells.nth(2).inner_text().strip()
            if name and name not in {'不明', '---', 'ー'}:
                horses.append(name)
    # unique keep order
    seen = set()
    uniq = []
    for h in horses:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def find_source_count_from_text(text):
    m = re.search(r'情報源数\s*(\d+)件', text)
    if m:
        return int(m.group(1))
    return None


result = {
    'base_url': BASE_URL,
    'login': None,
    'race_horses_from_shutuba': [],
    'warning_count': 0,
    'warning_lines': [],
    'web_article_count': None,
    'aggregated_horse_count': None,
    'horse_source_counts': {},
    'errors': [],
}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1600, 'height': 1200})
    page.set_default_timeout(60000)

    try:
        page.goto(BASE_URL, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)

        pw = page.locator("input[type='password']")
        if pw.count() > 0:
            pw.first.fill('7777')
            if not click_if_exists(page.get_by_role('button', name=re.compile('ログイン'))):
                pw.first.press('Enter')
            page.wait_for_timeout(2500)
            result['login'] = 'submitted'
        else:
            result['login'] = 'already_authenticated'

        # wait app ready
        page.wait_for_selector('text=情報入力', timeout=120000)

        # collect current race horses from active shutuba table
        result['race_horses_from_shutuba'] = collect_horses_from_table(page)

        # open 情報入力 tab
        if not click_if_exists(page.get_by_role('tab', name=re.compile('情報入力'))):
            click_if_exists(page.get_by_text('情報入力'))
        page.wait_for_timeout(1200)

        # click Web一括検索
        if not click_if_exists(page.get_by_role('button', name=re.compile('Web\s*一括検索'))):
            if not click_if_exists(page.get_by_text('Web 一括検索')):
                if not click_if_exists(page.get_by_text('Web一括検索')):
                    raise RuntimeError('Web一括検索ボタンを見つけられませんでした')

        # wait process
        start = time.time()
        while time.time() - start < 210:
            body = get_body_text(page)
            if '検索・解析が完了しました' in body:
                break
            if 'Web記事を検索・解析中...' not in body and ('Web記事' in body or '解析をスキップしました' in body):
                # likely finished (with warnings)
                pass
            page.wait_for_timeout(3000)

        body = get_body_text(page)
        warnings = [ln.strip() for ln in body.splitlines() if 'Web記事の解析をスキップしました' in ln]
        result['warning_count'] = len(warnings)
        result['warning_lines'] = warnings[:15]

        m_web = re.search(r'Web記事\s*(\d+)件取得', body)
        if m_web:
            result['web_article_count'] = int(m_web.group(1))

        # open 総合予想（馬別） tab
        if not click_if_exists(page.get_by_role('tab', name=re.compile('総合予想'))):
            click_if_exists(page.get_by_text('総合予想'))
        page.wait_for_timeout(1500)

        body3 = get_body_text(page)
        m_aggr = re.search(r'集計完了:\s*(\d+)頭分', body3)
        if m_aggr:
            result['aggregated_horse_count'] = int(m_aggr.group(1))

        # collect horse tabs
        tab_names = [t.strip() for t in page.get_by_role('tab').all_inner_texts()]
        horse_tabs = [t for t in tab_names if t and t not in TOP_TABS]

        # if no horse tabs but there is aggregation, fallback parse by lines
        for h in horse_tabs:
            tab = page.get_by_role('tab', name=h)
            if tab.count() == 0:
                continue
            tab.first.click()
            page.wait_for_timeout(600)
            txt = get_body_text(page)
            sc = find_source_count_from_text(txt)
            result['horse_source_counts'][h] = sc

        # screenshot for audit
        page.screenshot(path='tmp/playwright_web_check.png', full_page=True)

    except Exception as e:
        result['errors'].append(f'{type(e).__name__}: {e}')
        try:
            page.screenshot(path='tmp/playwright_web_check_error.png', full_page=True)
        except Exception:
            pass
    finally:
        browser.close()

print(json.dumps(result, ensure_ascii=False, indent=2))
