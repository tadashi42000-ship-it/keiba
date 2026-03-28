import json
import re
import sys
from pathlib import Path

import pandas as pd
from google import genai as google_genai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app

# horse list
_df = pd.read_csv('data/race_202606030111.csv', encoding='utf-8-sig')
horses = _df['馬名'].dropna().astype(str).tolist()
horse_list_str = '\n'.join([f'- {n}' for n in horses])

arts = app.search_web_articles_with_tavily('日経賞 2026 予想', max_articles=3, include_domains=app.WEB_SEARCH_ALLOWLIST)
a = arts[1]

prompt = f"""
あなたは競馬予想の専門家です。以下のWeb記事の情報を読み、各馬の詳細な評価情報を抽出してください。

# 記事タイトル
{a['title']}

# 記事内容（要約）
{a['snippet']}

# 注目すべき出走馬（これら以外の馬名が登場しても抽出してください）
{horse_list_str}

# 抽出してほしい情報（各馬について）
プラス情報として以下を重点的に探してください：
- 前走・近走の成績
- 調教・追切の様子
- 体調・調子
- コース・距離適性
- 騎手・厩舎の強み
- その他の好材料

マイナス情報として以下を重点的に探してください：
- 前走・近走での敗因
- 調教不安
- コース・距離の不安
- 枠順・展開の不安
- その他の懸念点

# 出力形式
以下のJSON形式で**必ず**出力してください（説明文は一切不要）：

```json
[
  {{
    "馬名": "馬の名前",
    "プラス情報": "具体的な好材料を2〜3文で詳しく記載",
    "マイナス情報": "具体的な懸念点・不安材料を記載（なければ『特になし』）"
  }}
]
```

# 注意事項
- 記事に情報がない馬は出力しない
- 馬名が全く見当たらない場合のみ「全体的な予想」として1件だけ出力
- JSONのみ出力し、前後に説明文を付けないこと
"""

client = google_genai.Client(api_key=app.GEMINI_API_KEY)
resp = client.models.generate_content(model=app.GEMINI_MODEL, contents=prompt)
text = resp.text or ''
print('resp_len=', len(text))
print('--- head ---')
print(text[:1500])
print('--- tail ---')
print(text[-600:])

m = re.search(r'```json\s*(\[.*?\])\s*```', text, re.DOTALL)
json_text = m.group(1) if m else text.strip()
print('json_extract_len=', len(json_text))
try:
    obj = json.loads(json_text)
    print('json_ok type=', type(obj).__name__, 'len=', len(obj) if hasattr(obj, '__len__') else 'na')
except Exception as e:
    print('json_error', type(e).__name__, str(e))
