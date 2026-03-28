import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://race.netkeiba.com/race/shutuba.html?race_id=202605010811"
        print(f"Navigating to: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
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
                first_horse = await horse_cells[0].inner_text()
                print(f"First horse: {first_horse.strip()!r}")
        else:
            content = await page.content()
            if "redirect" in content.lower() or "error" in content.lower():
                print("Page might have redirect or error")
            print(f"Page source length: {len(content)}")
            if "\u30d5\u30a7\u30d6\u30e9\u30ea\u30fc" in content:
                print("\u30da\u30fc\u30b8\u306b\u30d5\u30a7\u30d6\u30e9\u30ea\u30fc\u542b\u6709")
            else:
                print("\u30da\u30fc\u30b8\u306b\u30d5\u30a7\u30d6\u30e9\u30ea\u30fc\u306a\u3057")
            body = await page.query_selector("body")
            if body:
                body_text = await body.inner_text()
                print(f"Body text (first 500 chars): {body_text[:500]}")
        
        await browser.close()

asyncio.run(main())
