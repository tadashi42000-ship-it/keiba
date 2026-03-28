# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", timeout=30000)
    time.sleep(5)
    
    pwd = page.query_selector("input[type='password']")
    if pwd:
        pwd.fill("7777")
        time.sleep(1)
        buttons = page.locator("button").all()
        if buttons:
            buttons[-1].click()
            time.sleep(5)
    
    # Tab 0: 出馬表 - full page to see all rows
    page.screenshot(path="c:/WORK/keiba/design_v2_tab0.png", full_page=True)
    print("Tab0 screenshot saved")
    
    # Tab 1: 勝率シミュレーター - scroll to bottom to see ranking bars
    tabs = page.locator("button[role='tab']").all()
    print(f"Found {len(tabs)} tabs")
    
    if len(tabs) > 1:
        tabs[1].click()
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.screenshot(path="c:/WORK/keiba/design_v2_tab1_bottom.png", full_page=True)
        print("Tab1 bottom screenshot saved")
    
    browser.close()
    print("Done")
