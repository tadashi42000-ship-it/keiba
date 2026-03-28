import asyncio
from playwright.async_api import async_playwright

async def investigate_url(browser, url, label):
    page = await browser.new_page()
    print(f"\n=== {label} ===")
    print(f"URL: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        
        title = await page.title()
        print(f"Page title: {title}")
        
        table = await page.query_selector("table.Shutuba_Table")
        print(f"Shutuba_Table found: {table is not None}")
        
        if table:
            rows = await page.query_selector_all("table.Shutuba_Table tr")
            print(f"Number of rows: {len(rows)}")
            
            horse_cells = await page.query_selector_all("td.HorseInfo")
            print(f"HorseInfo cells found: {len(horse_cells)}")
            
            waku_cells = await page.query_selector_all("td.Waku")
            print(f"Waku cells found: {len(waku_cells)}")
            if waku_cells:
                first_waku = await waku_cells[0].inner_text()
                print(f"First waku value: {first_waku!r}")
            
            umaban_cells = await page.query_selector_all("td.Umaban")
            print(f"Umaban cells found: {len(umaban_cells)}")
            if umaban_cells:
                first_umaban = await umaban_cells[0].inner_text()
                print(f"First umaban value: {first_umaban!r}")
            
            odds_cells = await page.query_selector_all("td.Popular")
            print(f"Popular (odds) cells found: {len(odds_cells)}")
            if odds_cells:
                first_odds = await odds_cells[0].inner_text()
                print(f"First odds value: {first_odds!r}")
            
            if horse_cells:
                for i, hc in enumerate(horse_cells[:5]):
                    name = await hc.inner_text()
                    print(f"Horse {i+1}: {name.strip()!r}")
        else:
            content = await page.content()
            print(f"Page source length: {len(content)}")
            markers = ["\u30d5\u30a7\u30d6\u30e9\u30ea\u30fc", "Shutuba", "shutuba", "\u51fa\u99ac\u8868"]
            for m in markers:
                print(f"  Contains {m!r}: {m in content}")
            body = await page.query_selector("body")
            if body:
                body_text = await body.inner_text()
                print(f"Body text (first 800 chars):\n{body_text[:800]}")
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await page.close()

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await investigate_url(browser, "https://race.netkeiba.com/race/shutuba.html?race_id=202605010811", "URL1: shutuba.html")
        await investigate_url(browser, "https://db.netkeiba.com/race/202605010811/", "URL2: db.netkeiba")
        await browser.close()

asyncio.run(main())
