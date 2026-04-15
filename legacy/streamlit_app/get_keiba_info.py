"""
netkeiba.com から出馬表を取得してCSVに保存するプログラム

任意のレースIDを指定して出馬表データを取得できる。
CLI実行時は --race-id, --output オプションで対象を変更可能。
"""

import argparse
import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

# ====================
# デフォルト設定（後方互換用）
# ====================

DEFAULT_RACE_ID = "202605010811"  # フェブラリーS 2026（仮ID）
DEFAULT_OUTPUT_FILE = "february_s_info.csv"

# ====================
# 関数定義エリア
# ====================

def get_race_info(url):
    """
    指定されたURLから競馬レース情報を取得する関数

    引数:
        url (str): レース情報のURL

    戻り値:
        BeautifulSoup: 解析されたHTMLデータ
    """
    print(f"レース情報を取得中: {url}")

    # ヘッダー情報を設定（ウェブサイトにブラウザからのアクセスに見せる）
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        # ウェブサイトにリクエストを送信
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'EUC-JP'  # netkeibaの文字エンコーディング

        # ステータスコードが200（成功）であることを確認
        if response.status_code == 200:
            print("[OK] データ取得成功")
            # HTMLを解析してBeautifulSoupオブジェクトを返す
            return BeautifulSoup(response.text, 'html.parser')
        else:
            print(f"[NG] エラー: ステータスコード {response.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"[NG] 接続エラー: {e}")
        return None


def parse_shutuba_table(soup):
    """
    出馬表のHTMLから必要な情報を抽出する関数

    引数:
        soup (BeautifulSoup): 解析されたHTMLデータ

    戻り値:
        list: 馬の情報を含む辞書のリスト
    """
    print("出馬表を解析中...")

    horses_data = []  # 馬のデータを格納するリスト

    # 出馬表のテーブルを探す
    shutuba_table = soup.find('table', class_='Shutuba_Table')

    if not shutuba_table:
        print("[NG] 出馬表が見つかりませんでした")
        return horses_data

    def _find_td_by_class_prefix(row, prefix: str):
        """class='Waku1' のような接尾辞付きクラスにも対応する。"""
        for td in row.find_all('td'):
            classes = td.get('class') or []
            if any(str(c).startswith(prefix) for c in classes):
                return td
        return None

    # テーブルの各行（馬）を処理
    rows = shutuba_table.find_all('tr')

    for row in rows:
        # 馬名のセルを探す
        horse_name_tag = row.find('td', class_='HorseInfo')
        if not horse_name_tag:
            continue  # 馬名がない行はスキップ

        # 馬名を取得
        horse_link = horse_name_tag.find('a')
        if horse_link:
            horse_name = horse_link.text.strip()
        else:
            continue

        # 枠番を取得
        waku_tag = _find_td_by_class_prefix(row, 'Waku')
        waku = waku_tag.text.strip() if waku_tag else "不明"

        # 馬番を取得
        umaban_tag = _find_td_by_class_prefix(row, 'Umaban')
        umaban = umaban_tag.text.strip() if umaban_tag else "不明"

        # 性齢を取得
        barei_tag = row.find('td', class_='Barei')
        barei = barei_tag.text.strip() if barei_tag else "不明"

        # 斤量を取得
        kinryo_tag = row.find('td', class_='Weight')
        kinryo = kinryo_tag.text.strip() if kinryo_tag else "不明"

        # 騎手を取得
        jockey_tag = row.find('td', class_='Jockey')
        if jockey_tag:
            jockey_link = jockey_tag.find('a')
            jockey = jockey_link.text.strip() if jockey_link else "不明"
        else:
            jockey = "不明"

        # 調教師を取得
        trainer_tag = row.find('td', class_='Trainer')
        if trainer_tag:
            trainer_link = trainer_tag.find('a')
            trainer = trainer_link.text.strip() if trainer_link else "不明"
        else:
            trainer = "不明"

        # オッズを取得（ある場合）
        odds_tag = row.find('td', class_='Popular')
        odds = odds_tag.text.strip() if odds_tag else "未発表"

        # データを辞書にまとめる
        horse_data = {
            '枠番': waku,
            '馬番': umaban,
            '馬名': horse_name,
            '性齢': barei,
            '斤量': kinryo,
            '騎手': jockey,
            '調教師': trainer,
            'オッズ': odds
        }

        horses_data.append(horse_data)
        print(f"  {umaban}番 {horse_name} - データ取得完了")

    print(f"[OK] 合計 {len(horses_data)} 頭の情報を取得しました")
    return horses_data


def save_to_csv(data, filename):
    """
    データをCSVファイルに保存する関数

    引数:
        data (list): 保存するデータのリスト
        filename (str): 保存先のファイル名
    """
    print(f"\nCSVファイルに保存中: {filename}")

    if not data:
        print("[NG] 保存するデータがありません")
        return

    # 親ディレクトリが存在しなければ作成
    parent = os.path.dirname(filename)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # pandasのDataFrameに変換
    df = pd.DataFrame(data)

    # CSVファイルとして保存（日本語対応のため、エンコーディングをutf-8-sigに設定）
    df.to_csv(filename, index=False, encoding='utf-8-sig')

    print(f"[OK] {len(data)}件のデータを {filename} に保存しました")
    print(f"\n保存されたデータのプレビュー:")
    print(df.to_string())


def fetch_race_csv(race_id: str, output_file: str) -> str:
    """
    指定レースIDの出馬表を取得し、CSVファイルに保存する。

    引数:
        race_id: netkeiba.com のレースID（12桁）
        output_file: 保存先CSVファイルパス

    戻り値:
        str: 保存したファイルパス

    例外:
        RuntimeError: 取得・解析に失敗した場合
    """
    race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"

    soup = get_race_info(race_url)
    if soup is None:
        raise RuntimeError(
            f"レース情報の取得に失敗しました (race_id={race_id})。"
            "インターネット接続・レースIDを確認してください。"
        )

    time.sleep(1)  # サーバー負荷軽減

    horses_data = parse_shutuba_table(soup)
    if not horses_data:
        raise RuntimeError(
            f"出馬表データが見つかりませんでした (race_id={race_id})。"
            "出馬表が公開されているか確認してください。"
        )

    save_to_csv(horses_data, output_file)
    return output_file


# ====================
# メイン処理
# ====================

def main():
    """
    メイン処理を実行する関数（CLI対応）
    """
    parser = argparse.ArgumentParser(description="netkeiba.com から出馬表を取得してCSVに保存")
    parser.add_argument('--race-id', default=DEFAULT_RACE_ID, help=f"レースID（デフォルト: {DEFAULT_RACE_ID}）")
    parser.add_argument('--output', default=DEFAULT_OUTPUT_FILE, help=f"出力ファイル（デフォルト: {DEFAULT_OUTPUT_FILE}）")
    args = parser.parse_args()

    print("=" * 60)
    print("競馬レース 出馬表取得ツール")
    print(f"  レースID: {args.race_id}")
    print(f"  出力先:   {args.output}")
    print("=" * 60)
    print()

    try:
        fetch_race_csv(args.race_id, args.output)
    except RuntimeError as e:
        print(f"\n[NG] {e}")
        return

    print("\n" + "=" * 60)
    print("処理が完了しました！")
    print("=" * 60)


# ====================
# プログラムの実行
# ====================

if __name__ == "__main__":
    # このファイルが直接実行された場合のみ、main関数を実行
    main()
