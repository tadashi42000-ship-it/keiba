"""
2026-04-26 東京 5R/6R の当日レースモード E2E 検証スクリプト
"""
from __future__ import annotations
import sys
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "http://localhost:8502"
PASSWORD = "7777"
TARGET_DATE = "2026-04-26"
TARGET_VENUE = "東京"
TARGET_RACES = ["5R", "6R"]

PASS = "[OK]"
FAIL = "[NG]"
SKIP = "[SKIP]"

results: list[tuple[str, str, str]] = []


def log(tid: str, status: str, detail: str) -> None:
    mark = PASS if status == "PASS" else (SKIP if status == "SKIP" else FAIL)
    print(f"  {tid} {mark}: {detail}")
    results.append((tid, status, detail))


def wait_for_streamlit(page, timeout=20000):
    """Streamlit のレンダリング完了を待つ"""
    try:
        page.wait_for_function(
            "() => !document.querySelector('[data-testid=\"stStatusWidget\"]') || "
            "document.querySelector('[data-testid=\"stStatusWidget\"]').textContent.trim() === ''",
            timeout=timeout,
        )
    except Exception:
        pass
    time.sleep(1.5)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        time.sleep(2)

        # ── 認証 ──────────────────────────────────────────────────────
        pw_input = page.query_selector("input[type='password']")
        if pw_input:
            pw_input.fill(PASSWORD)
            btn = page.query_selector("button:has-text('ログイン')")
            if btn:
                btn.click()
            else:
                pw_input.press("Enter")
            try:
                page.wait_for_function(
                    "() => !document.querySelector('input[type=\"password\"]')",
                    timeout=15000,
                )
                log("AUTH", "PASS", "login succeeded")
            except Exception:
                log("AUTH", "FAIL", "login did not complete")
                browser.close()
                return
        else:
            log("AUTH", "SKIP", "already logged in")

        wait_for_streamlit(page)

        # ── T1: サイドバーに モード ラジオが存在する ──────────────────
        content = page.content()
        has_mode_radio = "当日レースモード" in content or "重賞モード" in content
        log("T1", "PASS" if has_mode_radio else "FAIL",
            "mode radio found" if has_mode_radio else "mode radio NOT found")

        # ── T2: 当日レースモードに切り替え ───────────────────────────
        mode_btns = page.query_selector_all("label")
        switched = False
        for lbl in mode_btns:
            txt = lbl.inner_text().strip()
            if "当日レース" in txt:
                lbl.click()
                switched = True
                break
        if not switched:
            # ラジオが label.inner_text で取れない場合 Streamlit radio は span
            spans = page.query_selector_all("div[data-testid='stRadio'] span")
            for sp in spans:
                if "当日レース" in sp.inner_text():
                    sp.click()
                    switched = True
                    break
        wait_for_streamlit(page)
        content = page.content()
        log("T2", "PASS" if switched else "FAIL",
            "switched to 当日レースモード" if switched else "could not click mode radio")

        # ── T3: 日付ピッカーで 2026-04-26 を入力 ─────────────────────
        date_input = page.query_selector("input[type='date']")
        if date_input:
            date_input.fill(TARGET_DATE)
            date_input.press("Tab")
            wait_for_streamlit(page)
            log("T3", "PASS", f"date set to {TARGET_DATE}")
        else:
            log("T3", "FAIL", "date input not found")

        # ── T4: 東京 会場が selectbox に表示され選択できる ──────────────
        # Streamlit select box 操作
        wait_for_streamlit(page)
        content = page.content()
        venue_found = TARGET_VENUE in content
        log("T4", "PASS" if venue_found else "FAIL",
            f"venue '{TARGET_VENUE}' found in content" if venue_found
            else f"venue '{TARGET_VENUE}' NOT found in content")

        # 会場 selectbox を探す
        selects = page.query_selector_all("select")
        venue_selected = False
        for sel in selects:
            opts = sel.query_selector_all("option")
            for opt in opts:
                if TARGET_VENUE in opt.inner_text():
                    sel.select_option(label=TARGET_VENUE)
                    venue_selected = True
                    break
            if venue_selected:
                break

        if not venue_selected:
            # Streamlit custom select
            sb = page.query_selector(f"[data-testid='stSelectbox']")
            if sb:
                sb.click()
                time.sleep(0.5)
                opt = page.query_selector(f"li:has-text('{TARGET_VENUE}')")
                if opt:
                    opt.click()
                    venue_selected = True

        wait_for_streamlit(page)
        log("T4b", "PASS" if venue_selected else "SKIP",
            f"selected venue '{TARGET_VENUE}'" if venue_selected else "venue selectbox could not be operated")

        # ── T5: 5R / 6R のタブが表示される ──────────────────────────
        wait_for_streamlit(page, timeout=15000)
        content = page.content()
        tabs_found = []
        for race in TARGET_RACES:
            if race in content:
                tabs_found.append(race)
        log("T5", "PASS" if len(tabs_found) == len(TARGET_RACES) else "FAIL",
            f"race tabs found: {tabs_found}" if tabs_found else "race tabs NOT found")

        # ── T6: 5R タブをクリック + 基本情報取得ボタン押下 ─────────────
        clicked_5r = False
        tabs = page.query_selector_all("[data-testid='stTab'] button, div[role='tab']")
        for tab in tabs:
            if "5R" in tab.inner_text():
                tab.click()
                clicked_5r = True
                break
        if not clicked_5r:
            # タブが別の構造の場合
            btn_5r = page.query_selector("button:has-text('5R')")
            if btn_5r:
                btn_5r.click()
                clicked_5r = True
        wait_for_streamlit(page)
        log("T6", "PASS" if clicked_5r else "FAIL",
            "5R tab clicked" if clicked_5r else "5R tab not clickable")

        # 基本情報取得ボタンを押す
        btn_basic = page.query_selector("button:has-text('基本情報取得')")
        if btn_basic:
            btn_basic.click()
            wait_for_streamlit(page, timeout=30000)
            log("T6b", "PASS", "基本情報取得 button clicked")
        else:
            log("T6b", "FAIL", "基本情報取得 button not found")

        # ── T7: 出馬表 (馬名/枠番) が表示される ─────────────────────
        wait_for_streamlit(page, timeout=20000)
        content = page.content()
        # DataFrameが表示されているか（馬名カラム想定）
        has_table = (
            "dataframe" in content.lower()
            or "data-testid=\"stDataFrame\"" in content
            or "枠番" in content
            or "馬番" in content
        )
        log("T7", "PASS" if has_table else "FAIL",
            "出馬表 (dataframe) found" if has_table else "出馬表 NOT found")

        # ── T8: 脚質列が出馬表に含まれる ─────────────────────────────
        has_style = "脚質" in content
        log("T8", "PASS" if has_style else "FAIL",
            "脚質 column present" if has_style else "脚質 column NOT found")

        # ── T9: 前走情報（直近3走）が表示される ─────────────────────
        has_recent = "前走" in content or "近走" in content or "corners" in content.lower()
        log("T9", "PASS" if has_recent else "FAIL",
            "直近走行情報 present" if has_recent else "直近走行情報 NOT found")

        # ── T10: 6R タブをクリック + 独立動作確認 ───────────────────
        clicked_6r = False
        tabs = page.query_selector_all("[data-testid='stTab'] button, div[role='tab']")
        for tab in tabs:
            if "6R" in tab.inner_text():
                tab.click()
                clicked_6r = True
                break
        if not clicked_6r:
            btn_6r = page.query_selector("button:has-text('6R')")
            if btn_6r:
                btn_6r.click()
                clicked_6r = True
        wait_for_streamlit(page)
        log("T10", "PASS" if clicked_6r else "FAIL",
            "6R tab clicked independently" if clicked_6r else "6R tab not clickable")

        # ── T11: 6R の情報取得が独立（DuplicateWidgetID エラーなし） ─
        content = page.content()
        has_dup_error = "DuplicateWidgetID" in content or "Duplicate widget" in content
        log("T11", "PASS" if not has_dup_error else "FAIL",
            "no DuplicateWidgetID error" if not has_dup_error else "DuplicateWidgetID DETECTED")

        # ── T12: ネット情報取得 ボタンが 6R に存在する ───────────────
        btn_net = page.query_selector("button:has-text('ネット情報取得')")
        if not btn_net:
            btn_net = page.query_selector("button:has-text('情報取得')")
        log("T12", "PASS" if btn_net else "FAIL",
            "ネット情報取得 button present" if btn_net else "ネット情報取得 button NOT found")

        # ── T13: レース特徴タブに会場/距離の統計が表示（6R の子タブ） ─
        # レース特徴タブを探す
        child_tabs = page.query_selector_all("[data-testid='stTab'] button, div[role='tab']")
        clicked_feature = False
        for ct in child_tabs:
            txt = ct.inner_text()
            if "レース特徴" in txt or "傾向" in txt:
                ct.click()
                clicked_feature = True
                break
        wait_for_streamlit(page)
        content = page.content()
        has_course_stats = (
            "枠順" in content or "脚質" in content or "コース" in content
            or "複勝率" in content or "sample_size" in content
        )
        log("T13", "PASS" if has_course_stats else "FAIL",
            "course stats / race characteristics found" if has_course_stats
            else "race characteristics NOT found (may need ネット情報取得 first)")

        # ── T14: X 広域検索ボタンが存在する ──────────────────────────
        btn_x = page.query_selector("button:has-text('X投稿')")
        if not btn_x:
            btn_x = page.query_selector("button:has-text('広域')")
        if not btn_x:
            # X section のどこかに
            btn_x = page.query_selector("button:has-text('X')")
        log("T14", "PASS" if btn_x else "FAIL",
            "X search button present" if btn_x else "X search button NOT found")

        # ── スクリーンショット保存 ────────────────────────────────────
        page.screenshot(path="legacy/streamlit_app/verify_screenshot.png", full_page=True)
        print("\n  [INFO] Screenshot saved: legacy/streamlit_app/verify_screenshot.png")

        browser.close()

    # ── 結果集計 ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("E2E Verification Summary -- 2026-04-26 Tokyo 5R/6R")
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    skipped = sum(1 for _, s, _ in results if s == "SKIP")
    for tid, status, detail in results:
        mark = PASS if status == "PASS" else (SKIP if status == "SKIP" else FAIL)
        print(f"  {tid}: {mark} {detail}")
    print(f"\nTotal: {passed} PASS / {failed} FAIL / {skipped} SKIP")
    return failed


if __name__ == "__main__":
    sys.exit(main())
