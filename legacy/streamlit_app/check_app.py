import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("http://localhost:8504", timeout=30000)
            await page.wait_for_timeout(3000)
            title = await page.title()
            print("Title: " + title)
            page_text = await page.inner_text("body")
            if "password" in page_text.lower() or chr(12497)+chr(12473)+chr(12527)+chr(12540)+chr(12489) in page_text:
                print("Password prompt detected - filling 7777")
                pw_input = await page.query_selector("input[type=password]")
                if not pw_input:
                    pw_input = await page.query_selector("input[type=text]")
                if pw_input:
                    await pw_input.fill("7777")
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(3000)
                    print("Password submitted")
            page_text = await page.inner_text("body")
            print("Page text length: " + str(len(page_text)))
            horse1 = chr(12458)+chr(12513)+chr(12460)+chr(12462)+chr(12493)+chr(12473)
            horse2 = chr(12454)+chr(12451)+chr(12523)+chr(12477)+chr(12531)+chr(12486)+chr(12477)+chr(12540)+chr(12525)
            if horse1 in page_text:
                print("[OK] Horse data (horse1) found")
            else:
                print("[NG] horse1 NOT found")
            if horse2 in page_text:
                print("[OK] horse2 found")
            else:
                print("[NG] horse2 NOT found")
            print("First 3000 chars:")
            print(page_text[:3000])
        except Exception as e:
            print("Error: " + str(e))
            import traceback
            traceback.print_exc()
        await browser.close()

asyncio.run(main())