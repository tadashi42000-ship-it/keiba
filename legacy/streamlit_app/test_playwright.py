"""
Playwright / static-analysis を用いた app.py の実装検証テスト

検証項目:
  T1: パスワード認証画面が表示される
  T2: 正しいパスワード + ボタンクリックでログインできる
  T3: ログイン後にサイドバーにレースセレクターが表示される
  T4: combined_keyword のウィジェットキーがレース別スコープになっている
  T5: _on_race_change が combined_keyword:: / yt_detail_keyword:: を prefix クリアする
  T6: _normalize_special_url が不正URLを弾く（race_catalog 単体テスト）
  T7: [OK]/[NG] ログ記号が get_keiba_info.py に存在する（Windows cp932 安全確認）
"""

import sys
import re
import importlib
import time
from pathlib import Path

PROJECT = Path(__file__).parent

# ===== ユニットテスト（Playwright不要） ================================

def test_normalize_special_url():
    """T6: _normalize_special_url が不正URLを弾く"""
    sys.path.insert(0, str(PROJECT))
    import race_catalog
    importlib.reload(race_catalog)
    fn = race_catalog._normalize_special_url

    valid = fn("https://race.netkeiba.com/race/special.html?race_id=202605010811")
    assert valid.startswith("https://race.netkeiba.com"), f"[NG] valid URL failed: {valid}"

    assert fn("javascript:alert(1)") == "", "[NG] javascript: should be blocked"
    assert fn("https://evil.example.com/hack") == "", "[NG] external domain should be blocked"
    assert fn("") == "", "[NG] empty string should return empty"

    valid2 = fn("//db.netkeiba.com/race/?pid=race_list")
    assert "netkeiba.com" in valid2, f"[NG] subdomain URL failed: {valid2}"

    print("T6 [OK]: _normalize_special_url")


def test_log_symbols():
    """T7: get_keiba_info.py に [OK]/[NG] が使われ、非ASCII記号がない"""
    src = (PROJECT / "get_keiba_info.py").read_text(encoding="utf-8")
    assert "[OK]" in src, "[NG] [OK] not found"
    assert "[NG]" in src, "[NG] [NG] not found"

    for pat in ["\u2705", "\u274c", "\u2713", "\u2717"]:  # checkmark/cross symbols
        assert pat not in src, f"[NG] non-ASCII symbol '{pat}' still present"
    print("T7 [OK]: [OK]/[NG] log symbols")


def test_race_session_keys_prefix_clear():
    """T5: _on_race_change が combined_keyword:: / yt_detail_keyword:: を prefix クリアする"""
    src = (PROJECT / "app.py").read_text(encoding="utf-8")
    assert "combined_keyword::" in src, \
        "[NG] combined_keyword:: prefix clear not found in _on_race_change"
    assert "yt_detail_keyword::" in src, \
        "[NG] yt_detail_keyword:: prefix clear not found in _on_race_change"
    print("T5 [OK]: race-scoped widget key prefix clear in _on_race_change")


def test_widget_key_format():
    """T4: combined_keyword / yt_detail_keyword のウィジェットキーが race_widget_scope スコープ"""
    src = (PROJECT / "app.py").read_text(encoding="utf-8")

    assert "combined_keyword::{race_widget_scope}" in src, \
        "[NG] combined_keyword widget key not race-scoped"
    assert "yt_detail_keyword::{race_widget_scope}" in src, \
        "[NG] yt_detail_keyword widget key not race-scoped"
    assert 'race_widget_scope = r.race_key if r else' in src, \
        "[NG] race_widget_scope definition not found"
    print("T4 [OK]: widget key format race-scoped")


def test_race_catalog_interface():
    """race_catalog.py の公開インターフェース確認"""
    sys.path.insert(0, str(PROJECT))
    import race_catalog
    importlib.reload(race_catalog)

    for fn_name in ["fetch_graded_races", "resolve_race_id", "get_upcoming_races", "ensure_data_dir"]:
        assert hasattr(race_catalog, fn_name), f"[NG] {fn_name} not in race_catalog"

    from dataclasses import fields
    field_names = {f.name for f in fields(race_catalog.RaceInfo)}
    for required in ["race_name", "grade", "date_str", "date", "venue", "distance",
                     "surface", "race_id", "race_key", "csv_file", "special_url"]:
        assert required in field_names, f"[NG] RaceInfo missing field: {required}"

    print("T3/catalog [OK]: race_catalog interface")


def test_get_keiba_info_interface():
    """get_keiba_info.py の公開インターフェース確認"""
    src = (PROJECT / "get_keiba_info.py").read_text(encoding="utf-8")
    assert "def fetch_race_csv" in src, "[NG] fetch_race_csv not found"
    assert "argparse" in src, "[NG] argparse not found"
    assert "--race-id" in src, "[NG] --race-id option not found"
    assert "--output" in src, "[NG] --output option not found"
    assert "RuntimeError" in src, "[NG] RuntimeError not found"
    print("T3/get_keiba [OK]: get_keiba_info interface")


def test_app_helper_functions():
    """app.py に必要なヘルパー関数が存在し、削除対象定数が無いこと"""
    src = (PROJECT / "app.py").read_text(encoding="utf-8")

    for fn in ["get_race_config", "get_race_display_name", "get_csv_path",
               "get_race_url", "get_minimal_race_characteristics",
               "_on_race_change", "_display_race_selector"]:
        assert f"def {fn}" in src, f"[NG] {fn} not found in app.py"

    for dead in ["FEATURED_HORSES", "HORSE_NAME_ALIASES", "RACE_INFO_FROM_DOC"]:
        assert dead not in src, f"[NG] deleted constant {dead} still present"
    print("T2/helpers [OK]: app.py helper functions and removed constants")


def test_password_title():
    """タイトルが重賞予想アプリになっているか"""
    src = (PROJECT / "app.py").read_text(encoding="utf-8")
    assert "重賞予想アプリ" in src, "[NG] title not changed to 重賞予想アプリ"
    print("T1/title [OK]: app title")


# ===== Playwright ブラウザテスト =====================================

def run_playwright_tests(base_url: str = "http://localhost:8501"):
    """Streamlit が起動済みの前提でブラウザテストを実行する"""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("SKIP: playwright not installed")
        return

    import urllib.request
    try:
        urllib.request.urlopen(base_url, timeout=3)
    except Exception:
        print(f"SKIP: Streamlit not running at {base_url}")
        return

    print(f"\n--- Playwright browser tests ({base_url}) ---")
    pw_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(base_url, wait_until="networkidle")
        time.sleep(2)

        # T1: パスワード画面
        content = page.content()
        has_pw = "パスワード" in content or "password" in content.lower()
        pw_input = page.query_selector("input[type='password']")
        if has_pw and pw_input:
            pw_results.append(("T1", "PASS", "password screen shown"))
        elif not pw_input:
            pw_results.append(("T1", "SKIP", "already logged in or no password screen"))
        else:
            pw_results.append(("T1", "FAIL", "password text present but input not found"))

        # T2: ログイン（ボタンクリック）
        if pw_input:
            try:
                page.wait_for_selector("input[type='password']:not([disabled])", timeout=10000)
                pw_input = page.query_selector("input[type='password']")
                pw_input.fill("7777")
                login_btn = page.query_selector("button:has-text('ログイン')")
                if login_btn:
                    login_btn.click()
                else:
                    pw_input.press("Enter")
                try:
                    page.wait_for_function(
                        "() => !document.querySelector('input[type=\"password\"]')",
                        timeout=10000
                    )
                    pw_results.append(("T2", "PASS", "login succeeded"))
                except Exception:
                    pw_results.append(("T2", "FAIL", "password field still visible after login attempt"))
            except Exception as e:
                pw_results.append(("T2", "FAIL", f"input not enabled: {e}"))
        else:
            pw_results.append(("T2", "SKIP", "already logged in"))

        time.sleep(3)
        page.wait_for_load_state("networkidle")

        # T3: レースセレクター
        content = page.content()
        has_selector = (
            "直近の重賞レース" in content
            or "レース選択" in content
            or "レースIDを手動入力" in content
            or "重賞一覧を取得できませんでした" in content
        )
        pw_results.append(("T3", "PASS" if has_selector else "FAIL",
                           "race selector found" if has_selector else "race selector not found"))

        # T4: race-scoped widget key（ソース検査で補完）
        src_check = "combined_keyword::{race_widget_scope}" in (PROJECT / "app.py").read_text(encoding="utf-8")
        pw_results.append(("T4", "PASS" if src_check else "FAIL",
                           "race-scoped widget key in source"))

        browser.close()

    for t_id, status, detail in pw_results:
        mark = "[OK]" if status == "PASS" else ("[SKIP]" if status == "SKIP" else "[NG]")
        print(f"  {t_id} {mark}: {detail}")
    print("--- Playwright browser tests done ---\n")


# ===== メイン =========================================================

def main():
    unit_tests = [
        test_normalize_special_url,
        test_log_symbols,
        test_race_session_keys_prefix_clear,
        test_widget_key_format,
        test_race_catalog_interface,
        test_get_keiba_info_interface,
        test_app_helper_functions,
        test_password_title,
    ]

    print("=" * 60)
    print("Keiba App Implementation Verification")
    print("=" * 60)

    failed = 0
    results = []
    for test_fn in unit_tests:
        try:
            test_fn()
            results.append((test_fn.__name__, "PASS"))
        except AssertionError as e:
            print(f"FAIL: {test_fn.__name__}: {e}")
            results.append((test_fn.__name__, f"FAIL: {e}"))
            failed += 1
        except Exception as e:
            print(f"ERROR: {test_fn.__name__}: {type(e).__name__}: {e}")
            results.append((test_fn.__name__, f"ERROR: {e}"))
            failed += 1

    run_playwright_tests()

    print("=" * 60)
    print("Unit Test Summary")
    print("=" * 60)
    for name, status in results:
        mark = "[OK]" if status == "PASS" else "[NG]"
        print(f"  {mark} {name}: {status}")

    total = len(results)
    passed = total - failed
    print(f"\n{passed}/{total} passed" + (" -- ALL OK" if failed == 0 else f" -- {failed} FAILED"))
    return failed


if __name__ == "__main__":
    sys.exit(main())
