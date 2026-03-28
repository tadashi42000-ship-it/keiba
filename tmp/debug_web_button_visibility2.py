import re, time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page(viewport={'width':1600,'height':1200})
    page.goto('http://localhost:8511')
    page.wait_for_timeout(1200)
    if page.locator("input[type='password']").count()>0:
        page.locator("input[type='password']").first.fill('7777')
        page.get_by_role('button', name='ログイン').first.click()

    # wait until tabs visible
    start=time.time()
    while time.time()-start<120:
        if page.get_by_role('tab').count()>=5:
            break
        page.wait_for_timeout(1000)
    print('tabs', page.get_by_role('tab').count())

    tab_info = page.get_by_role('tab', name=re.compile('情報入力'))
    print('info tab count', tab_info.count())
    if tab_info.count()>0:
        tab_info.first.click()
    page.wait_for_timeout(1000)

    loc = page.get_by_role('button', name=re.compile('Web\\s*一括検索'))
    print('role-match count', loc.count())
    for i in range(loc.count()):
        el=loc.nth(i)
        print('i',i,'visible',el.is_visible(),'enabled',el.is_enabled(),'text',el.inner_text().encode('unicode_escape').decode())

    loc2 = page.locator("button:has-text('Web 一括検索')")
    print('css has-text count', loc2.count())
    for i in range(loc2.count()):
        el=loc2.nth(i)
        print('css i',i,'visible',el.is_visible(),'enabled',el.is_enabled(),'text',el.inner_text().encode('unicode_escape').decode())

    page.screenshot(path='tmp/debug_web_button_visibility2.png', full_page=True)
    b.close()
