import re, time
from playwright.sync_api import sync_playwright, TimeoutError

with sync_playwright() as p:
    b=p.chromium.launch(headless=True)
    page=b.new_page(viewport={'width':1400,'height':1000})
    page.goto('http://localhost:8511')
    page.wait_for_timeout(1500)
    pw=page.locator("input[type='password']")
    if pw.count()>0:
        pw.first.fill('7777')
        page.get_by_role('button', name='ログイン').first.click()
    start=time.time()
    while time.time()-start<180:
        vis_pw = page.locator("input[type='password']").first.is_visible() if page.locator("input[type='password']").count()>0 else False
        has_info = page.get_by_text('情報入力').count()>0
        has_shutuba = page.get_by_text('出走予定馬一覧').count()>0
        has_warn = page.get_by_text('出馬表はまだ公開されていません').count()>0
        print(f"t={int(time.time()-start)} pw={vis_pw} info={has_info} shutuba={has_shutuba} warn={has_warn}")
        if has_info or has_shutuba or has_warn:
            break
        page.wait_for_timeout(3000)

    print('final body len', len(page.inner_text('body')))
    print('tabs count', page.get_by_role('tab').count())
    print('text 情報入力 count', page.get_by_text('情報入力').count())
    page.screenshot(path='tmp/debug_wait_login.png', full_page=True)
    b.close()
