import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    # Very tall viewport to capture all content
    page = browser.new_page(viewport={"width": 1400, "height": 4000})
    page.goto("http://localhost:8501", timeout=30000)
    time.sleep(5)
    
    pwd = page.query_selector("input[type='password']")
    if pwd:
        pwd.fill("7777")
        page.get_by_text("ログイン").click()
        time.sleep(4)
    
    # Tab 1: 勝率シミュレーター
    tabs = page.locator("button[role='tab']").all()
    tabs[1].click()
    time.sleep(4)
    page.screenshot(path="c:/WORK/keiba/design_v3_sim_tall.png")
    
    browser.close()
    print("Done")
