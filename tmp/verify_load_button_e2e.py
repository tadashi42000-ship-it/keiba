import re, json, time
from playwright.sync_api import sync_playwright

res = {}
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width':1500,'height':1000})
    page = ctx.new_page()
    page.goto('http://localhost:8511', wait_until='domcontentloaded')

    # wait either login or tabs
    for _ in range(60):
        if page.locator("input[type='password']").count() > 0 or page.get_by_role('tab').count() > 0:
            break
        page.wait_for_timeout(500)

    if page.locator("input[type='password']").count() > 0:
        page.locator("input[type='password']").first.fill('7777')
        lb = page.get_by_role('button', name='ログイン')
        if lb.count() > 0:
            lb.first.click()

    page.wait_for_timeout(3500)
    tabs_before = page.get_by_role('tab').count()
    res['tabs_before_load_click'] = tabs_before

    load_btn = page.get_by_role('button', name=re.compile('このレースを読み込む'))
    res['load_button_count'] = load_btn.count()
    if load_btn.count() > 0:
        load_btn.first.click()

    for _ in range(180):
        if page.get_by_role('tab').count() >= 5:
            break
        page.wait_for_timeout(1000)

    tabs_after = page.get_by_role('tab').count()
    res['tabs_after_load_click'] = tabs_after
    body = page.inner_text('body')
    res['has_shutuba_list'] = '出走予定馬一覧' in body

    page.screenshot(path='tmp/verify_load_button_e2e.png', full_page=True)
    ctx.close(); b.close()

print(json.dumps(res, ensure_ascii=False, indent=2))
