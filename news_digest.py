#!/usr/bin/env python3
"""
daily_digest.py  —  毎日ニュース自動巡回スクリプト
キーワード: タイ・ボイラー、バイオマス燃料、日タイ貿易、為替
出力: HTML形式のデイリーレポート
"""

import feedparser
import google.generativeai as genai
import os
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ========== 設定 ==========

KEYWORDS = [
    "Thailand boiler", "タイ ボイラー", "GETABEC",
    "biomass fuel", "biomass energy", "バイオマス",
    "Japan Thailand trade", "日タイ 貿易", "日タイ ビジネス",
    "USD JPY", "THB JPY", "ドル円", "バーツ",
    "EFB palm", "coconut shell fuel", "rubber wood biomass",
    "industrial boiler", "stoker boiler", "steam boiler Thailand",
]

# 無料RSSフィード一覧
RSS_FEEDS = [
    # タイ・ビジネス系
    {"name": "Bangkok Post – Business", "url": "https://www.bangkokpost.com/rss/data/business.xml", "lang": "en"},
    {"name": "Bangkok Post – Economy", "url": "https://www.bangkokpost.com/rss/data/economy.xml", "lang": "en"},
    {"name": "The Nation Thailand", "url": "https://www.nationthailand.com/rss", "lang": "en"},
    {"name": "Thai PBS World", "url": "https://www.thaipbsworld.com/feed/", "lang": "en"},

    # エネルギー・バイオマス
    {"name": "Reuters – Energy", "url": "https://feeds.reuters.com/reuters/businessNews", "lang": "en"},
    {"name": "Bioenergy Insight", "url": "https://www.bioenergy-news.com/news/rss/", "lang": "en"},

    # 日本・アジア経済
    {"name": "NHK World – Asia Pacific", "url": "https://www3.nhk.or.jp/rss/news/cat6.xml", "lang": "ja"},
    {"name": "NHK World – Business", "url": "https://www3.nhk.or.jp/rss/news/cat5.xml", "lang": "ja"},
    {"name": "JETRO ニュース", "url": "https://www.jetro.go.jp/rss/news.rdf", "lang": "ja"},

    # Google News RSS（キーワード検索）
    {"name": "Google News: バイオマス タイ", "url": "https://news.google.com/rss/search?q=%E3%83%90%E3%82%A4%E3%82%AA%E3%83%9E%E3%82%B9+%E3%82%BF%E3%82%A4&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
    {"name": "Google News: biomass Thailand", "url": "https://news.google.com/rss/search?q=biomass+Thailand+boiler&hl=en&gl=TH&ceid=TH:en", "lang": "en"},
    {"name": "Google News: Japan Thailand trade", "url": "https://news.google.com/rss/search?q=Japan+Thailand+trade+2025&hl=en&gl=JP&ceid=JP:en", "lang": "en"},
    {"name": "Google News: USD/JPY THB", "url": "https://news.google.com/rss/search?q=USD+JPY+THB+%E7%82%BA%E6%9B%BF&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
]

# ========== フィード取得 ==========

def fetch_feeds(hours_back=24):
    """全RSSフィードを取得し、直近N時間の記事を返す"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []

    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:20]:  # 各フィード最大20件
                # 公開日時を取得
                published = None
                for attr in ["published_parsed", "updated_parsed"]:
                    if hasattr(entry, attr) and getattr(entry, attr):
                        published = datetime(*getattr(entry, attr)[:6], tzinfo=timezone.utc)
                        break
                if published is None:
                    published = datetime.now(timezone.utc)  # 日時不明は今日として扱う

                if published < cutoff:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                # HTMLタグ除去
                summary = re.sub(r"<[^>]+>", "", summary)[:500]
                link = entry.get("link", "")

                articles.append({
                    "source": feed_info["name"],
                    "lang": feed_info["lang"],
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published.isoformat(),
                })
        except Exception as e:
            print(f"  [WARN] {feed_info['name']}: {e}")

    return articles

# ========== キーワード関連度フィルタ（ローカル） ==========

def keyword_score(article):
    """タイトル＋概要にキーワードが何個含まれるか（大文字小文字無視）"""
    text = (article["title"] + " " + article["summary"]).lower()
    score = sum(1 for kw in KEYWORDS if kw.lower() in text)
    return score

# ========== Gemini APIで要約・スコアリング ==========

def analyze_with_claude(articles):
    """Gemini APIで関連記事を選別し、日本語要約を生成"""
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash")

    # まずローカルフィルタで絞り込み（スコア0は除外、APIコスト節約）
    candidates = [a for a in articles if keyword_score(a) > 0]
    # スコア順にソートし上位40件まで
    candidates.sort(key=keyword_score, reverse=True)
    candidates = candidates[:40]

    if not candidates:
        return []

    # Gemini に一括判定・要約させる
    articles_json = json.dumps(candidates, ensure_ascii=False, indent=2)

    prompt = f"""あなたはビジネスニュースアナリストです。
以下の記事リストを分析し、次のトピックに関連する記事だけを選別して日本語で要約してください：

【追跡トピック】
1. タイのボイラー業界・産業設備
2. バイオマス燃料・再生可能エネルギー（特に東南アジア）
3. 日タイビジネス・貿易・投資
4. 為替（USD/JPY、THB/JPY）

【指示】
- 関連性が低い記事は除外してください
- 関連する記事は、以下のJSON形式で返してください（他のテキストは不要）
- 要約は100〜150字の日本語で、ビジネスパーソン向けに具体的な数字や固有名詞を残してください
- relevance_score: 1〜5（5が最も関連性高い）
- category: "ボイラー/産業設備" | "バイオマス/エネルギー" | "日タイ貿易/ビジネス" | "為替/金融"

返答形式（JSONのみ、マークダウン不要）:
[
  {{
    "title": "元のタイトル",
    "source": "ソース名",
    "link": "URL",
    "published": "日時",
    "summary_ja": "日本語要約",
    "category": "カテゴリ",
    "relevance_score": 5
  }}
]

【記事リスト】
{articles_json}
"""

    response = model.generate_content(prompt)
    raw = response.text.strip()
    # JSONフェンス除去
    raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"[WARN] JSON parse failed: {raw[:200]}")
        return []

# ========== HTML生成 ==========

def build_html(analyzed_articles, all_count, candidate_count):
    today = datetime.now(tz=timezone(timedelta(hours=9)))
    date_str = today.strftime("%Y年%m月%d日（%a）")

    # カテゴリ別グループ化
    categories = {}
    for a in analyzed_articles:
        cat = a.get("category", "その他")
        categories.setdefault(cat, []).append(a)

    # カテゴリアイコン
    icons = {
        "ボイラー/産業設備": "🔧",
        "バイオマス/エネルギー": "🌿",
        "日タイ貿易/ビジネス": "🤝",
        "為替/金融": "💹",
        "その他": "📰",
    }

    cat_html = ""
    for cat, articles in sorted(categories.items(), key=lambda x: -len(x[1])):
        icon = icons.get(cat, "📰")
        items_html = ""
        for a in sorted(articles, key=lambda x: -x.get("relevance_score", 0)):
            stars = "★" * a.get("relevance_score", 3) + "☆" * (5 - a.get("relevance_score", 3))
            pub = a.get("published", "")[:16].replace("T", " ")
            items_html += f"""
            <article class="card">
              <div class="card-meta">
                <span class="source">{a['source']}</span>
                <span class="date">{pub}</span>
                <span class="stars">{stars}</span>
              </div>
              <h3><a href="{a['link']}" target="_blank" rel="noopener">{a['title']}</a></h3>
              <p class="summary-ja">{a.get('summary_ja', '')}</p>
            </article>"""

        cat_html += f"""
        <section class="category">
          <h2>{icon} {cat} <span class="count">{len(articles)}件</span></h2>
          {items_html}
        </section>"""

    if not cat_html:
        cat_html = '<p class="no-news">本日、関連ニュースは見つかりませんでした。</p>'

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>デイリーニュースダイジェスト — {date_str}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;700&family=Noto+Sans+JP:wght@400;500&display=swap');

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --ink: #1a1a2e;
      --paper: #faf8f3;
      --accent: #c8570a;
      --accent2: #2d6a4f;
      --rule: #d4c5a9;
      --muted: #7a6f5e;
      --card-bg: #ffffff;
    }}

    body {{
      font-family: 'Noto Sans JP', sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.7;
      padding: 0 16px 60px;
    }}

    header {{
      border-bottom: 3px double var(--ink);
      padding: 32px 0 20px;
      margin-bottom: 32px;
      text-align: center;
    }}

    header .masthead {{
      font-family: 'Noto Serif JP', serif;
      font-size: clamp(1.4rem, 4vw, 2.2rem);
      font-weight: 700;
      letter-spacing: 0.05em;
      color: var(--ink);
    }}

    header .sub {{
      font-size: 0.85rem;
      color: var(--muted);
      margin-top: 6px;
      letter-spacing: 0.08em;
    }}

    .stats-bar {{
      display: flex;
      justify-content: center;
      gap: 24px;
      font-size: 0.8rem;
      color: var(--muted);
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--rule);
    }}

    .stats-bar span {{ display: flex; align-items: center; gap: 4px; }}

    main {{
      max-width: 860px;
      margin: 0 auto;
    }}

    .category {{
      margin-bottom: 40px;
    }}

    .category h2 {{
      font-family: 'Noto Serif JP', serif;
      font-size: 1.15rem;
      font-weight: 700;
      border-left: 4px solid var(--accent);
      padding-left: 12px;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .category h2 .count {{
      font-size: 0.75rem;
      font-family: 'Noto Sans JP', sans-serif;
      font-weight: 400;
      color: var(--muted);
      background: var(--rule);
      padding: 2px 8px;
      border-radius: 10px;
    }}

    .card {{
      background: var(--card-bg);
      border: 1px solid var(--rule);
      border-radius: 6px;
      padding: 16px 20px;
      margin-bottom: 12px;
      transition: box-shadow 0.2s;
    }}

    .card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}

    .card-meta {{
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 0.75rem;
      color: var(--muted);
      margin-bottom: 6px;
      flex-wrap: wrap;
    }}

    .source {{
      font-weight: 500;
      color: var(--accent2);
    }}

    .stars {{
      color: #c8a400;
      letter-spacing: -1px;
    }}

    .card h3 {{
      font-size: 0.95rem;
      font-weight: 500;
      margin-bottom: 8px;
      line-height: 1.5;
    }}

    .card h3 a {{
      color: var(--ink);
      text-decoration: none;
    }}

    .card h3 a:hover {{ color: var(--accent); text-decoration: underline; }}

    .summary-ja {{
      font-size: 0.875rem;
      color: #3a3530;
      line-height: 1.75;
      border-top: 1px solid var(--rule);
      padding-top: 8px;
      margin-top: 4px;
    }}

    .no-news {{
      text-align: center;
      color: var(--muted);
      padding: 40px;
      font-size: 0.9rem;
    }}

    footer {{
      text-align: center;
      font-size: 0.75rem;
      color: var(--muted);
      margin-top: 48px;
      padding-top: 16px;
      border-top: 1px solid var(--rule);
    }}
  </style>
</head>
<body>
  <header>
    <div class="masthead">📋 デイリーニュースダイジェスト</div>
    <div class="sub">{date_str}　｜　業界ニュースダイジェスト</div>
    <div class="stats-bar">
      <span>📡 取得記事数: {all_count}件</span>
      <span>🔍 キーワード候補: {candidate_count}件</span>
      <span>✅ 掲載: {len(analyzed_articles)}件</span>
    </div>
  </header>

  <main>
    {cat_html}
  </main>

  <footer>
    生成: {today.strftime("%Y-%m-%d %H:%M")} JST　｜　ソース: RSS自動巡回 + Claude AI要約
  </footer>
</body>
</html>"""
    return html

# ========== メイン ==========

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] フィード取得中...")
    articles = fetch_feeds(hours_back=24)
    print(f"  → {len(articles)}件取得")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Claude APIで分析中...")
    analyzed = analyze_with_claude(articles)
    print(f"  → {len(analyzed)}件を関連ありと判定")

    candidates = [a for a in articles if keyword_score(a) > 0]

    html = build_html(analyzed, len(articles), len(candidates))

    # 出力ファイル名（日付入り）
    date_tag = datetime.now().strftime("%Y%m%d")
    out_path = Path(f"digest_{date_tag}.html")
    out_path.write_text(html, encoding="utf-8")
    print(f"  → 出力: {out_path}")
    return str(out_path)

if __name__ == "__main__":
    main()
