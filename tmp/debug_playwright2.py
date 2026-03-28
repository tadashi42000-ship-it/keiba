import re
from playwright.sync_api import sync_playwright

def u(s):
    return s.encode('unicode_escape').decode()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={'width': 1400, 'height': 1000})
    page.goto('http://localhost:8511')
    page.wait_for_timeout(2000)

    body0 = page.inner_text('body')
    print('before_login_body=', u(body0))
    print('before_buttons=', [u(x) for x in page.get_by_role('button').all_inner_texts()])

    pw = page.locator("input[type='password']")
    print('pw_count=', pw.count())
    if pw.count() > 0:
        pw.first.fill('7777')
        btn = page.get_by_role('button', name=re.compile('ログイン'))
        print('login_btn_count=', btn.count())
        if btn.count() > 0:
            btn.first.click()
        else:
            pw.first.press('Enter')

    page.wait_for_timeout(5000)
    body1 = page.inner_text('body')
    print('after_login_body=', u(body1))
    print('after_buttons=', [u(x) for x in page.get_by_role('button').all_inner_texts()])
    print('tabs=', [u(x) for x in page.get_by_role('tab').all_inner_texts()])

    page.screenshot(path='tmp/debug_playwright_page2.png', full_page=True)
    b.close()
