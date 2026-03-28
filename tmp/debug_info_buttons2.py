import re
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page(viewport={'width':1500,'height':1100})
    page.goto('http://localhost:8511')
    page.wait_for_timeout(2000)
    pw=page.locator("input[type='password']")
    if pw.count()>0:
        pw.first.fill('7777')
        page.get_by_role('button', name='ログイン').first.click()
    page.wait_for_selector('text=情報入力', timeout=120000)
    page.wait_for_timeout(1000)

    print('tabs:', [t.encode('unicode_escape').decode() for t in page.get_by_role('tab').all_inner_texts()])
    # click info tab
    page.get_by_role('tab', name=re.compile('情報入力')).first.click()
    page.wait_for_timeout(1000)
    btns = page.locator('button')
    n=btns.count()
    arr=[]
    for i in range(n):
        txt=btns.nth(i).inner_text().strip()
        if txt:
            arr.append((i,txt))
    print('button count',n)
    for i,t in arr[:120]:
        print(i, t.encode('unicode_escape').decode())

    print('search text count 1', page.get_by_text('Web 一括検索').count())
    print('search text count 2', page.get_by_text('Web一括検索').count())
    print('btn role match', page.get_by_role('button', name=re.compile('Web')).count())
    page.screenshot(path='tmp/debug_info_tab_buttons.png', full_page=True)
    b.close()
