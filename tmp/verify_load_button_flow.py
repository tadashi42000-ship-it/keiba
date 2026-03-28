import re, json, time
from playwright.sync_api import sync_playwright

out = {}
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width':1400,'height':1000})
    page = ctx.new_page()
    page.goto('http://localhost:8511', wait_until='domcontentloaded')
    page.wait_for_timeout(1500)

    if page.locator("input[type='password']").count()>0:
        page.locator("input[type='password']").first.fill('7777')
        page.get_by_role('button', name='ログイン').first.click()

    page.wait_for_timeout(3000)
    body = page.inner_text('body')
    out['has_load_hint_before'] = ('このレースを読み込む' in body)
    out['tab_count_before'] = page.get_by_role('tab').count()

    btn = page.get_by_role('button', name=re.compile('このレースを読み込む'))
    out['load_btn_count'] = btn.count()
    if btn.count()>0:
        btn.first.click()
        start=time.time()
        while time.time()-start<120:
            if page.get_by_role('tab').count()>=5:
                break
            page.wait_for_timeout(1000)

    out['tab_count_after'] = page.get_by_role('tab').count()
    body2 = page.inner_text('body')
    out['has_shutuba_after'] = ('出走予定馬一覧' in body2)

    page.screenshot(path='tmp/verify_load_button_flow.png', full_page=True)
    ctx.close(); b.close()

print(json.dumps(out, ensure_ascii=False, indent=2))
