import asyncio
import sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        url = "https://race.netkeiba.com/race/shutuba.html?race_id=202605010811"
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        title = await page.title()
        print(repr(title))

        rows = await page.query_selector_all("table.Shutuba_Table tr")
        print("rows:", len(rows))

        if len(rows) > 1:
            first_data_row = rows[1]
            cells = await first_data_row.query_selector_all("td")
            print("cells in row 1:", len(cells))
            for i, cell in enumerate(cells):
                cls = await cell.get_attribute("class")
                txt = await cell.inner_text()
                print(f"  Cell {i}: class={repr(cls)}, text={repr(txt[:40])}")

        all_tds = await page.query_selector_all("table.Shutuba_Table td")
        classes_seen = set()
        for td in all_tds:
            cls = await td.get_attribute("class")
            if cls: classes_seen.add(cls)
        print("All TD classes:", sorted(classes_seen))

        horse_cells = await page.query_selector_all("td.HorseInfo")
        print("HorseInfo count:", len(horse_cells))
        for i, hc in enumerate(horse_cells):
            name = await hc.inner_text()
            print(f"  Horse {i+1}: {repr(name.strip())}")

        odds_cells = await page.query_selector_all("td.Popular")
        print("Popular count:", len(odds_cells))
        for i, oc in enumerate(odds_cells[:10]):
            txt = await oc.inner_text()
            print(f"  Odds {i}: {repr(txt)}")

        await browser.close()

asyncio.run(main())