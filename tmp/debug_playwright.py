import re
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={'width': 1400, 'height': 1000})
    page.goto('http://localhost:8511')
    page.wait_for_timeout(2000)

    pw = page.locator("input[type='password']")
    if pw.count() > 0:
        pw.first.fill('7777')
        btn = page.get_by_role('button', name=re.compile('ログイン'))
        if btn.count() > 0:
            btn.first.click()
        else:
            pw.first.press('Enter')

    page.wait_for_timeout(4000)
    tabs = page.get_by_role('tab').all_inner_texts()
    print('tabs=', tabs)

    t = page.get_by_role('tab', name=re.compile('情報入力'))
    print('info_tab_count=', t.count())
    if t.count() > 0:
        t.first.click()
        page.wait_for_timeout(2000)

    body = page.inner_text('body')
    print('body_len=', len(body))
    print(body[:5000])

    buttons = page.get_by_role('button').all_inner_texts()
    print('buttons=', buttons[:80])

    page.screenshot(path='tmp/debug_playwright_page.png', full_page=True)
    b.close()
