import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = "https://race.netkeiba.com/race/shutuba.html?race_id=202605010811"
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        title = await page.title()
        print("TITLE:", repr(title))

        # Get all rows except header
        rows = await page.query_selector_all("table.Shutuba_Table tr")
        print("Total rows:", len(rows))

        # Print ALL TD content for rows 1-16 (skip header row 0)
        for ri, row in enumerate(rows):
            tds = await row.query_selector_all("td")
            if not tds: continue
            row_data = []
            for td in tds:
                cls = await td.get_attribute("class")
                txt = await td.inner_text()
                row_data.append((cls, txt.strip()))
            print(f"ROW {ri}: {row_data}")

        # Separate: get Waku cells by pattern
        for n in range(1, 9):
            wc = await page.query_selector_all(f"td.Waku{n}")
            if wc:
                print(f"Waku{n} cells: {len(wc)}")
                for c in wc:
                    t = await c.inner_text()
                    print(f"  {repr(t.strip())}")

        # Separate: get Umaban cells by pattern
        for n in range(1, 17):
            uc = await page.query_selector_all(f"td.Umaban{n}")
            if uc:
                print(f"Umaban{n} cells: {len(uc)}")
                for c in uc:
                    t = await c.inner_text()
                    print(f"  {repr(t.strip())}")

        # Popular cells full list
        odds_cells = await page.query_selector_all("td.Popular")
        print("All Popular TD cells:", len(odds_cells))
        for i, oc in enumerate(odds_cells):
            cls = await oc.get_attribute("class")
            txt = await oc.inner_text()
            print(f"  [{i}] class={repr(cls)}, text={repr(txt.strip())}")

        await browser.close()

asyncio.run(main())