import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
    
    # Wait for app to load
    page.wait_for_selector('[data-testid="stApp"]', timeout=20000)
    time.sleep(3)
    
    # Enter password
    pw_input = page.locator('input[type="password"]')
    if pw_input.count() > 0:
        pw_input.fill("7777")
        page.locator("button", has_text="ログイン").click()
        print("Password entered, waiting for app to load...")
        time.sleep(5)
    
    # Wait for tabs to appear
    page.wait_for_selector('[data-testid="stTabs"]', timeout=20000)
    time.sleep(3)
    
    # Screenshot tab 0
    page.screenshot(path="c:/WORK/keiba/design_before_tab0.png", full_page=True)
    print("Tab 0 screenshot saved")
    
    # Find and click each tab
    tabs = page.locator("button[role='tab']").all()
    print(f"Found {len(tabs)} tabs")
    for i, tab in enumerate(tabs):
        print(f"  Tab {i}: {tab.inner_text()}")
    
    for i, tab in enumerate(tabs[1:], 1):
        tab.click()
        time.sleep(2)
        page.screenshot(path=f"c:/WORK/keiba/design_before_tab{i}.png", full_page=True)
        print(f"Tab {i} screenshot saved")
    
    browser.close()
    print("All screenshots done")
