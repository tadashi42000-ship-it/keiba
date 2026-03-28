import re
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page(viewport={'width':1600,'height':1200})
    page.goto('http://localhost:8511')
    page.wait_for_timeout(2000)
    pw=page.locator("input[type='password']")
    if pw.count()>0:
        pw.first.fill('7777')
        btn=page.get_by_role('button', name='ログイン')
        if btn.count():
            btn.first.click()
    page.wait_for_timeout(8000)

    print('text=情報入力 count', page.get_by_text('情報入力').count())
    print('text=Web 一括検索 count', page.get_by_text('Web 一括検索').count())
    print('text=Web一括検索 count', page.get_by_text('Web一括検索').count())
    print('button texts visible-ish:')
    btns = page.locator('button')
    n=btns.count()
    for i in range(min(n,40)):
        t=btns.nth(i).inner_text().strip()
        if t:
            print(i, t.encode('unicode_escape').decode())

    # dump containing lines
    html = page.content()
    for kw in ['情報入力', 'Web 一括検索', 'Web一括検索', 'combined_search']:
        print('kw', kw, 'found', kw in html)

    page.screenshot(path='tmp/debug_buttons.png', full_page=True)
    b.close()
