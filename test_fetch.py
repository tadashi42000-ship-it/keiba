import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

RACE_URL = "https://race.netkeiba.com/race/shutuba.html?race_id=202605010811"

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(RACE_URL, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        content = page.content()
        browser.close()
    print(f"Page content length: {len(content)}")
    soup = BeautifulSoup(content, 'html.parser')
    shutuba_table = soup.find('table', class_='Shutuba_Table')
    print(f"Shutuba_Table found: {shutuba_table is not None}")
    if shutuba_table:
        result = {}
        rows = shutuba_table.find_all('tr')
        print(f"Number of rows: {len(rows)}")
        for row in rows:
            horse_info = row.find('td', class_='HorseInfo')
            if not horse_info:
                continue
            horse_link = horse_info.find('a')
            if not horse_link:
                continue
            horse_name = horse_link.text.strip()
            waku_td = row.find('td', class_=re.compile(r'Waku\d'))
            waku = waku_td.text.strip() if waku_td else ''
            umaban_td = row.find('td', class_=re.compile(r'Umaban\d'))
            umaban = umaban_td.text.strip() if umaban_td else ''
            odds_td = row.select_one('td.Txt_R.Popular')
            odds = odds_td.text.strip() if odds_td else '---.-'
            result[horse_name] = {'枠番': waku, '馬番': umaban, 'オッズ': odds}
        print(f"Horses found: {len(result)}")
        for name, data in list(result.items())[:5]:
            print(f"  {name}: 枠={data['枠番']}, 馬={data['馬番']}, オッズ={data['オッズ']}")
    else:
        print("Shutuba_Table NOT found — dumping first 3000 chars of HTML:")
        print(soup.prettify()[:3000])
except Exception as e:
    import traceback
    print(f"ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
