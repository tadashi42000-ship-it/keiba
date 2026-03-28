from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", timeout=30000)
    time.sleep(4)
    
    # Handle password if present
    pwd_input = page.query_selector("input[type='password']")
    if pwd_input:
        pwd_input.fill("7777")
        page.keyboard.press("Enter")
        time.sleep(3)
    
    # Tab 0: 出馬表
    page.screenshot(path="c:/WORK/keiba/design_after_tab0.png", full_page=True)
    
    # Tab 1: 勝率シミュレーター
    tabs = page.locator("button[role='tab']").all()
    if len(tabs) > 1:
        tabs[1].click()
        time.sleep(2)
        page.screenshot(path="c:/WORK/keiba/design_after_tab1.png", full_page=True)
    
    # Tab 2: 情報入力
    if len(tabs) > 2:
        tabs[2].click()
        time.sleep(2)
        page.screenshot(path="c:/WORK/keiba/design_after_tab2.png", full_page=True)
    
    browser.close()
    print("Done")
