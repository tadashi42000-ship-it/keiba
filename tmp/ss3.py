import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", timeout=30000)
    time.sleep(4)
    
    pwd = page.query_selector("input[type='password']")
    if pwd:
        pwd.fill("7777")
        time.sleep(0.5)
        login_btn = page.get_by_text("ログイン")
        if login_btn:
            login_btn.click()
        time.sleep(4)
    
    # Tab 0: 出馬表 - take viewport screenshot of visible part only (top)
    page.screenshot(path="c:/WORK/keiba/design_v3_tab0_top.png")
    
    # Scroll to show bottom of 出馬表 
    page.evaluate("window.scrollTo(0, 600)")
    time.sleep(0.5)
    page.screenshot(path="c:/WORK/keiba/design_v3_tab0_mid.png")
    
    # Tab 1: 勝率シミュレーター
    tabs = page.locator("button[role='tab']").all()
    tabs[1].click()
    time.sleep(2)
    # scroll to bottom
    page.evaluate("window.scrollTo(0, 99999)")
    time.sleep(1)
    # take viewport screenshot (just what's on screen at bottom)
    page.screenshot(path="c:/WORK/keiba/design_v3_tab1_bottom.png")
    
    browser.close()
    print("Done")
