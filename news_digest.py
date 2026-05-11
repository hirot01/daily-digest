#!/usr/bin/env python3
"""
news_digest.py — 毎日ニュース自動巡回スクリプト v3.6
機能: RSS巡回 → Geminiで翻訳・全体サマリー・カテゴリ分析・世界トレンド → インタラクティブHTML出力
変更履歴:
  v3.6 - ナビゲーション完全修正（available_dates.json動的取得）・記事クリック修正
  v3.5 - 記事クリック不具合修正・カレンダー前後ナビ修正
  v3.4 - 深掘りボタンをPerplexity検索に変更・ORIGINAL undefinedバグ修正
  v3.3 - 過去3日分との差分分析（What's new・継続・変化）をサマリーに追加
  v3.2 - 日付ナビゲーション（前後矢印＋カレンダーモーダル）追加
  v3.1 - ソース別件数制限撤廃・候補上限60件・保存済みバッジ表示
  v3.0 - カテゴリ5分類・デザイン刷新・世界トレンド枠追加・RSSソース追加・Geminiリトライ機能
  v2.0 - Gemini API対応・全体サマリー・カテゴリ別分析・日本語翻訳・スプレッドシート保存
  v1.0 - 初版（Claude API・シンプルHTML出力）
"""

import feedparser
from google import genai
import os, json, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ========== 設定 ==========

KEYWORDS = [
    # タイ関連
    "Thailand", "Thai", "タイ", "Bangkok", "バンコク",
    # ボイラー・産業設備
    "boiler", "ボイラー", "stoker", "steam", "industrial",
    # バイオマス・再生可能エネルギー
    "biomass", "バイオマス", "EFB", "palm", "renewable energy", "再生可能エネルギー",
    "solar", "wind power", "太陽光", "風力", "FIT", "FIP", "廃棄物発電",
    # エネルギー市場（普遍的キーワードのみ・地政学はGeminiに判断させる）
    "energy", "エネルギー", "fuel", "crude oil", "原油", "LNG", "天然ガス",
    "oil price", "原油価格", "OPEC", "petroleum", "石油",
    "energy security", "エネルギー安全保障", "energy market", "電力",
    "geopolitics", "地政学", "supply chain", "サプライチェーン",
    # 日タイ貿易・マクロ
    "Japan", "日本", "JTEPA", "trade", "export", "import", "貿易", "輸出", "輸入",
    "GDP", "経済政策", "金融政策", "日銀", "BOT", "中央銀行",
    # 為替
    "JPY", "THB", "yen", "baht", "円", "バーツ", "為替", "exchange rate",
    "USD", "dollar", "ドル", "円安", "円高",
    # アジア経済
    "ASEAN", "Southeast Asia", "東南アジア", "Asia",
    # 企業・ビジネス
    "企業", "投資", "M&A", "工場", "製造", "supply chain", "サプライチェーン",
]

RSS_FEEDS = [
    {"name": "Bangkok Post – Business", "url": "https://www.bangkokpost.com/rss/data/business.xml", "lang": "en"},
    {"name": "Bangkok Post – Economy",  "url": "https://www.bangkokpost.com/rss/data/economy.xml",  "lang": "en"},
    {"name": "The Nation Thailand",     "url": "https://www.nationthailand.com/rss",                "lang": "en"},
    {"name": "Thai PBS World",          "url": "https://www.thaipbsworld.com/feed/",                "lang": "en"},
    {"name": "Reuters Business",        "url": "https://feeds.reuters.com/reuters/businessNews",    "lang": "en"},
    {"name": "Bioenergy Insight",       "url": "https://www.bioenergy-news.com/news/rss/",          "lang": "en"},
    {"name": "NHK – アジア太平洋",      "url": "https://www3.nhk.or.jp/rss/news/cat6.xml",         "lang": "ja"},
    {"name": "NHK – ビジネス",          "url": "https://www3.nhk.or.jp/rss/news/cat5.xml",         "lang": "ja"},
    {"name": "JETRO ニュース",           "url": "https://www.jetro.go.jp/rss/news.rdf",             "lang": "ja"},
    {"name": "Google: バイオマス タイ",  "url": "https://news.google.com/rss/search?q=%E3%83%90%E3%82%A4%E3%82%AA%E3%83%9E%E3%82%B9+%E3%82%BF%E3%82%A4&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
    {"name": "Google: biomass Thailand","url": "https://news.google.com/rss/search?q=biomass+Thailand+boiler&hl=en&gl=TH&ceid=TH:en", "lang": "en"},
    {"name": "Google: Japan Thailand",  "url": "https://news.google.com/rss/search?q=Japan+Thailand+trade&hl=en&gl=JP&ceid=JP:en",    "lang": "en"},
    {"name": "Google: 為替 THB",        "url": "https://news.google.com/rss/search?q=USD+JPY+THB+%E7%82%BA%E6%9B%BF&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
    # newsclip.be（タイ日本語ニュース）
    {"name": "newsclip: タイ経済・企業",  "url": "https://newsclip.be/category/thai-news/thai-economy/feed", "lang": "ja"},
    {"name": "newsclip: 業界事情",        "url": "https://newsclip.be/category/business/products/feed",      "lang": "ja"},
    # 日本語専門紙
    {"name": "日刊工業新聞",              "url": "https://www.nikkan.co.jp/rss/nksrdf.rdf", "lang": "ja"},
    {"name": "ニュースイッチ",             "url": "https://newswitch.jp/feed/", "lang": "ja"},
    {"name": "日経ビジネス",              "url": "https://business.nikkei.com/rss/sns/nb.rdf", "lang": "ja"},
    # Google News追加キーワード
    {"name": "Google: バイオマス 日本",   "url": "https://news.google.com/rss/search?q=%E3%83%90%E3%82%A4%E3%82%AA%E3%83%9E%E3%82%B9+%E6%97%A5%E6%9C%AC+%E7%99%BA%E9%9B%BB&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
    {"name": "Google: 再生可能エネルギー","url": "https://news.google.com/rss/search?q=%E5%86%8D%E7%94%9F%E5%8F%AF%E8%83%BD%E3%82%A8%E3%83%8D%E3%83%AB%E3%82%AE%E3%83%BC+%E3%82%BF%E3%82%A4+%E6%97%A5%E6%9C%AC&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
    {"name": "Google: 原油 アジア",       "url": "https://news.google.com/rss/search?q=%E5%8E%9F%E6%B2%B9+%E3%82%A2%E3%82%B8%E3%82%A2+%E3%83%9B%E3%83%AB%E3%83%A0%E3%82%BA&hl=ja&gl=JP&ceid=JP:ja", "lang": "ja"},
    {"name": "Google: crude oil Asia",    "url": "https://news.google.com/rss/search?q=crude+oil+Asia+energy+market&hl=en&gl=US&ceid=US:en", "lang": "en"},
    # 世界トレンド用（Google Newsトップ）
    {"name": "Google News: トップ日本語",  "url": "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja", "lang": "ja", "trend": True},
    {"name": "Google News: Top English",   "url": "https://news.google.com/rss?hl=en&gl=US&ceid=US:en", "lang": "en", "trend": True},
]

CAT_ICONS  = {
    "ボイラー/産業設備":       "🔧",
    "バイオマス/再生可能エネルギー": "🌿",
    "エネルギー市場":          "⚡",
    "日タイ貿易/マクロ":       "🤝",
    "企業/ビジネス動向":       "🏭",
    "その他": "📰"
}
CAT_COLORS = {
    "ボイラー/産業設備":       "#b45309",
    "バイオマス/再生可能エネルギー": "#2d7a4f",
    "エネルギー市場":          "#0369a1",
    "日タイ貿易/マクロ":       "#7c3aed",
    "企業/ビジネス動向":       "#be123c",
    "その他": "#555"
}

# ========== RSS取得 ==========

def fetch_feeds(hours_back=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []
    trend_articles = []
    for fi in RSS_FEEDS:
        count = 0
        is_trend = fi.get("trend", False)
        try:
            feed = feedparser.parse(fi["url"])
            total = len(feed.entries)
            for entry in feed.entries:
                published = None
                for attr in ["published_parsed", "updated_parsed"]:
                    if hasattr(entry, attr) and getattr(entry, attr):
                        published = datetime(*getattr(entry, attr)[:6], tzinfo=timezone.utc)
                        break
                if published is None:
                    published = datetime.now(timezone.utc)
                if published < cutoff:
                    continue
                title   = entry.get("title", "")
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", "")))[:500]
                item = {
                    "source": fi["name"], "lang": fi["lang"],
                    "title": title, "body": summary,
                    "link": entry.get("link", ""),
                    "published": published.isoformat(),
                }
                if is_trend:
                    trend_articles.append(item)
                else:
                    articles.append(item)
                count += 1
            status = feed.get("status", "?")
            print(f"  [{status}] {fi['name']}: {count}件採用 / {total}件取得")
        except Exception as e:
            print(f"  [ERR] {fi['name']}: {e}")
    return articles, trend_articles

def keyword_score(a):
    text = (a["title"] + " " + a["body"]).lower()
    return sum(1 for kw in KEYWORDS if kw.lower() in text)

# ========== Gemini 呼び出し ==========

def gemini(model, prompt, max_retries=4):
    import time
    for attempt in range(max_retries):
        try:
            response = model.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            raw = response.text.strip()
            return re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
        except Exception as e:
            wait = 30 * (attempt + 1)
            print(f"  [RETRY {attempt+1}/{max_retries}] Gemini error: {e} → {wait}秒待機")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise

def analyze_articles(model, candidates):
    """記事の選別・翻訳・日本語要約・カテゴリ分類を一括実行"""
    if not candidates:
        return []
    payload = json.dumps(candidates, ensure_ascii=False, indent=2)
    prompt = f"""あなたは日タイビジネス専門のアナリストです。
以下の記事リストを分析し、関連する記事だけをJSONで返してください。

【追跡トピック】
1. タイのボイラー業界・産業設備・熱利用
2. バイオマス・再生可能エネルギー（太陽光・風力・廃棄物含む、東南アジア・日本）
3. エネルギー市場（原油・LNG・ガス・電力価格・エネルギー安全保障・産油国動向など時々の国際エネルギー情勢全般）
4. 日タイ貿易・マクロ経済（為替・経済政策・貿易統計・国際情勢）
5. 企業・ビジネス動向（日本・タイ・東南アジアの製造業・産業・M&A・サプライチェーン含む）

【指示】
- 関連性が低い記事は除外
- title_ja: タイトルの日本語訳（元が日本語ならそのまま）
- body_ja: 本文の日本語訳（元が日本語ならそのまま）
- summary_ja: 100〜150字の日本語要約（数字・固有名詞を保持）
- category: "ボイラー/産業設備" | "バイオマス/再生可能エネルギー" | "エネルギー市場" | "日タイ貿易/マクロ" | "企業/ビジネス動向"
  ※ エネルギー市場=原油・LNG・ガス・電力価格・エネルギー安全保障・産油国動向など時々の国際エネルギー情勢全般、日タイ貿易/マクロ=為替・経済政策・貿易統計・国際情勢、企業/ビジネス動向=個別企業・案件・業界ニュース
- relevance_score: 1〜5

JSONのみ返答（マークダウン不要）:
[
  {{
    "title": "元タイトル",
    "title_ja": "日本語タイトル",
    "body_ja": "日本語本文",
    "summary_ja": "日本語要約",
    "source": "ソース名",
    "link": "URL",
    "published": "日時",
    "category": "カテゴリ",
    "relevance_score": 5
  }}
]

【記事リスト】
{payload}"""
    raw = gemini(model, prompt)
    try:
        return json.loads(raw)
    except:
        print(f"[WARN] analyze JSON parse failed: {raw[:200]}")
        return []

def generate_overall_summary(model, articles, past_digests=None):
    """全記事から全体サマリーを生成（過去データと比較）"""
    if not articles:
        return "本日、関連ニュースは見つかりませんでした。"
    article_list = "\n".join([f"[{a['category']}] {a['title_ja']}" for a in articles])

    past_context = ""
    if past_digests:
        past_lines = []
        for p in past_digests:
            date_fmt = f"{p['date'][:4]}/{p['date'][4:6]}/{p['date'][6:8]}"
            past_lines.append(f"\n【{date_fmt}のサマリー】\n{p['summary']}")
            if p['titles']:
                past_lines.append("主な記事: " + " / ".join(p['titles'][:10]))
        past_context = "\n".join(past_lines)

    if past_context:
        prompt = f"""あなたは日タイビジネス専門のアナリストです。
本日の記事一覧と過去3日分のデータを比較し、以下の3点を含む200字程度の分析をしてください：
①継続している動き ②今日新たに出てきたトピック ③変化・進展があった点
箇条書きではなく流れのある文章で。数字や固有名詞は残してください。

【本日の記事】
{article_list}

【過去3日間のデータ】
{past_context}"""
    else:
        prompt = f"""以下は本日のニュース記事一覧です。全体的な市場動向・トレンドを200字程度で分析してください。
箇条書きではなく流れのある文章で。重要な数字や固有名詞は残してください。

{article_list}"""
    return gemini(model, prompt)

def generate_world_trend(model, trend_articles):
    """Google Newsトップから世界トレンドを生成"""
    if not trend_articles:
        return ""
    # 芸能・スポーツを除いたタイトル一覧
    titles = [a["title"] for a in trend_articles[:40]]
    titles_text = "\n".join(f"・{t}" for t in titles)
    prompt = f"""以下は今日のGoogle Newsトップ記事の見出し一覧です。
芸能・スポーツ・天気・地域ニュースを除外し、ビジネス・経済・政治・国際情勢・テクノロジーに関わる
今日の主要トレンドを150字程度で分析してください。
「今日は〇〇と〇〇が主要テーマです」のように、大局的な視点でまとめてください。

{titles_text}"""
    return gemini(model, prompt)

def generate_cat_summaries(model, articles, past_digests=None):
    """カテゴリ別トレンド分析を生成（過去データと比較）"""
    from collections import defaultdict
    by_cat = defaultdict(list)
    for a in articles:
        by_cat[a["category"]].append(a)

    # 過去記事をカテゴリ別に整理
    past_by_cat = defaultdict(list)
    if past_digests:
        for p in past_digests:
            date_fmt = f"{p['date'][4:6]}/{p['date'][6:8]}"
            for t in p.get('titles', []):
                past_by_cat['_all'].append(f"[{date_fmt}] {t}")

    summaries = {}
    for cat, arts in by_cat.items():
        titles = "\n".join([f"・{a['title_ja']}" for a in arts])
        # 過去の同カテゴリ記事（タイトルに部分一致で判断はGeminiに任せる）
        past_info = ""
        if past_digests:
            past_lines = []
            for p in past_digests:
                date_fmt = f"{p['date'][4:6]}/{p['date'][6:8]}"
                past_lines.append(f"[{date_fmt}]: {' / '.join(p['titles'][:8])}")
            past_info = f"\n\n【過去3日の全記事タイトル（参考）】\n" + "\n".join(past_lines)

        if past_info:
            prompt = f"""以下の「{cat}」カテゴリの本日記事と過去データを比較し、
What's new（新規動向）と継続トレンドを明確にしながら120字程度で分析してください。

【本日の記事】
{titles}{past_info}"""
        else:
            prompt = f"""以下の「{cat}」カテゴリの記事群から、現在のトレンドと注目点を120字程度で分析してください。
実務担当者向けに、文章形式で簡潔に。

{titles}"""
        summaries[cat] = gemini(model, prompt)
    return summaries

# ========== HTML生成 ==========

def extract_past_digest(date_tag):
    """過去のHTMLから全体サマリーと記事タイトル一覧を抽出"""
    path = Path(f"docs/digest_{date_tag}.html")
    if not path.exists():
        return None
    try:
        html = path.read_text(encoding="utf-8")
        result = {"date": date_tag, "summary": "", "titles": []}

        # 全体サマリーを抽出（summary-textクラスのdiv）
        m = re.search(r'class="summary-text"[^>]*>([^<]{20,})', html)
        if m:
            result["summary"] = m.group(1).strip()[:300]

        # 記事タイトルを抽出（article-titleクラスのdiv）
        titles = re.findall(r'class="article-title"[^>]*>([^<]{5,})', html)
        result["titles"] = titles[:30]  # 最大30件

        return result if result["titles"] or result["summary"] else None
    except Exception as e:
        print(f"  [WARN] 過去データ取得失敗 {date_tag}: {e}")
        return None

def get_past_digests(days=3):
    """過去N日分のダイジェストデータを取得"""
    available = get_available_dates()
    today_tag = datetime.now(tz=timezone(timedelta(hours=9))).strftime("%Y%m%d")
    past = [d for d in available if d < today_tag]
    past = sorted(past, reverse=True)[:days]  # 直近N日分
    results = []
    for tag in past:
        data = extract_past_digest(tag)
        if data:
            results.append(data)
    return results

def get_available_dates():
    """docs/フォルダにある過去のダイジェストの日付リストを返す"""
    docs_dir = Path("docs")
    dates = []
    if docs_dir.exists():
        for f in docs_dir.glob("digest_*.html"):
            name = f.stem  # digest_20260508
            date_str = name.replace("digest_", "")
            if len(date_str) == 8 and date_str.isdigit():
                dates.append(date_str)
    return sorted(dates)

def build_html(articles, overall_summary, world_trend, cat_summaries, all_count, candidate_count):
    today    = datetime.now(tz=timezone(timedelta(hours=9)))
    date_str = today.strftime("%Y年%m月%d日（%a）")

    # 記事データをJSに埋め込む（深掘り用）
    articles_js = json.dumps(articles, ensure_ascii=False)

    # 利用可能な日付リスト（カレンダー用）
    available_dates = get_available_dates()
    # 今日の日付も追加（まだdocsに存在しない場合）
    today_tag = today.strftime("%Y%m%d")
    if today_tag not in available_dates:
        available_dates.append(today_tag)
    available_dates_js = json.dumps(sorted(available_dates))

    # カテゴリ別グループ
    from collections import defaultdict
    by_cat = defaultdict(list)
    for a in articles:
        by_cat[a.get("category", "その他")].append(a)

    # カテゴリカード
    cat_cards_html = ""
    for cat, arts in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        icon  = CAT_ICONS.get(cat, "📰")
        color = CAT_COLORS.get(cat, "#555")
        trend = cat_summaries.get(cat, "")
        cat_cards_html += f"""
        <div class="cat-card" onclick="showCategory('{cat}')" style="border-left:4px solid {color}">
          <div class="cat-card-head">
            <span class="cat-icon">{icon}</span>
            <span class="cat-name">{cat}</span>
            <span class="cat-count">{len(arts)}件</span>
          </div>
          <p class="cat-trend">{trend}</p>
        </div>"""

    # 全記事リスト
    all_articles_html = ""
    for i, a in enumerate(sorted(articles, key=lambda x: -x.get("relevance_score", 0))):
        cat   = a.get("category", "その他")
        color = CAT_COLORS.get(cat, "#555")
        icon  = CAT_ICONS.get(cat, "📰")
        stars = "★" * a.get("relevance_score", 3) + "☆" * (5 - a.get("relevance_score", 3))
        pub   = a.get("published", "")[:16].replace("T", " ")
        all_articles_html += f"""
        <div class="article-item" style="border-left:3px solid {color}" data-cat="{cat}" data-idx="{i}" onclick="showArticle({i})">
          <div class="check-wrap" onclick="event.stopPropagation()">
            <input type="checkbox" id="chk-{i}" onchange="updateCount()">
            <label class="check-label" for="chk-{i}">保存する</label>
          </div>
          <div class="article-meta">
            <span class="art-cat" style="color:{color}">{icon} {cat}</span>
            <span class="art-src">{a['source']}</span>
            <span class="art-stars">{stars}</span>
          </div>
          <div class="article-title">{a.get('title_ja', a['title'])}</div>
          <div class="article-summary">{a.get('summary_ja', '')}</div>
        </div>"""

    if not all_articles_html:
        all_articles_html = '<p class="no-news">本日、関連ニュースは見つかりませんでした。</p>'

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>デイリーニュースダイジェスト — {date_str}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #f8f9fb; --bg2: #ffffff; --bg3: #f0f2f5;
      --fg: #1a1d23; --fg2: #4a5168; --fg3: #9299aa;
      --accent: #1a56db; --accent2: #0e9f6e;
      --rule: #e5e7eb; --shadow: 0 1px 4px rgba(0,0,0,.07);
    }}
    body {{ font-family:'Noto Sans JP',sans-serif; background:var(--bg); color:var(--fg); line-height:1.7; }}
    a {{ color:var(--accent); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}

    /* Header */
    .site-header {{
      position:sticky; top:0; z-index:100;
      background:#fff; border-bottom:1px solid var(--rule);
      padding:14px 24px; display:flex; align-items:center; justify-content:space-between;
      box-shadow:var(--shadow);
    }}
    .site-logo {{ font-size:15px; font-weight:700; color:var(--fg); letter-spacing:-.01em; }}
    .site-logo span {{ color:var(--accent); }}
    .site-date {{ font-size:12px; color:var(--fg3); }}
    .back-btn {{
      display:none; background:#f0f2f5; border:none;
      color:var(--fg2); padding:6px 14px; border-radius:20px; cursor:pointer; font-size:12px; font-weight:500;
    }}
    .back-btn.visible {{ display:block; }}

    /* Navigation */
    .nav-center {{ display:flex; align-items:center; gap:6px; }}
    .nav-arrow {{
      background:none; border:1px solid var(--rule); border-radius:8px;
      width:32px; height:32px; font-size:20px; cursor:pointer;
      color:var(--fg2); display:flex; align-items:center; justify-content:center;
      transition:all .15s; line-height:1;
    }}
    .nav-arrow:hover {{ background:var(--bg3); }}
    .nav-arrow:disabled {{ color:var(--rule); cursor:not-allowed; }}
    .date-btn {{
      background:var(--bg3); border:1px solid var(--rule); border-radius:8px;
      padding:5px 12px; font-size:13px; font-weight:600; cursor:pointer;
      color:var(--fg); transition:all .15s; white-space:nowrap;
    }}
    .date-btn:hover {{ background:#e5e7eb; }}

    /* Pages */
    .page {{ display:none; max-width:780px; margin:0 auto; padding:28px 20px 80px; }}
    .page.active {{ display:block; }}

    /* Overall summary */
    .summary-card {{
      background:linear-gradient(135deg, #1a56db 0%, #0e9f6e 100%);
      border-radius:16px; padding:24px 28px; margin-bottom:28px;
      box-shadow:0 4px 20px rgba(26,86,219,.2);
    }}
    .summary-label {{
      font-size:10px; font-weight:700; letter-spacing:.18em;
      color:rgba(255,255,255,.7); text-transform:uppercase; margin-bottom:10px;
    }}
    .summary-text {{ font-size:14px; line-height:1.9; color:#fff; }}

    /* Section head */
    .section-head {{
      font-size:12px; font-weight:700; color:var(--fg3);
      letter-spacing:.08em; text-transform:uppercase;
      margin-bottom:14px; padding-bottom:8px;
      border-bottom:2px solid var(--rule);
    }}

    /* Category cards */
    .cat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:32px; }}
    @media(max-width:500px){{ .cat-grid {{ grid-template-columns:1fr; }} }}
    .cat-card {{
      background:#fff; border-radius:14px; padding:18px 20px;
      cursor:pointer; transition:all .2s; border:1px solid var(--rule);
      box-shadow:var(--shadow);
    }}
    .cat-card:hover {{ transform:translateY(-2px); box-shadow:0 6px 20px rgba(0,0,0,.1); }}
    .cat-card-head {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }}
    .cat-icon {{ font-size:22px; }}
    .cat-name {{ font-size:13px; font-weight:700; flex:1; color:var(--fg); }}
    .cat-count {{
      font-size:11px; color:#fff; font-weight:600;
      background:var(--accent); padding:2px 10px; border-radius:20px;
    }}
    .cat-trend {{ font-size:12px; color:var(--fg2); line-height:1.75; }}

    /* Article items */
    .article-item {{
      background:#fff; border-radius:12px; border:1px solid var(--rule);
      padding:16px 20px; margin-bottom:10px; cursor:pointer;
      transition:all .15s; box-shadow:var(--shadow);
    }}
    .article-item:hover {{ transform:translateY(-1px); box-shadow:0 4px 16px rgba(0,0,0,.1); }}
    .article-meta {{ display:flex; gap:10px; font-size:11px; color:var(--fg3); margin-bottom:6px; flex-wrap:wrap; align-items:center; }}
    .art-cat {{ font-weight:600; font-size:11px; padding:2px 8px; border-radius:4px; background:var(--bg3); }}
    .art-stars {{ color:#f59e0b; letter-spacing:-1px; }}
    .article-title {{ font-size:14px; font-weight:600; color:var(--fg); line-height:1.55; margin-bottom:6px; }}
    .article-summary {{ font-size:12.5px; color:var(--fg2); line-height:1.7; }}
    .no-news {{ text-align:center; color:var(--fg3); padding:60px 20px; font-size:14px; }}

    /* Category page */
    .cat-page-icon {{ font-size:32px; margin-bottom:4px; }}
    .cat-page-name {{ font-size:22px; font-weight:700; margin-bottom:18px; color:var(--fg); }}
    .cat-summary-box {{
      background:#fff; border:1px solid var(--rule);
      border-radius:12px; padding:18px 22px; margin-bottom:24px;
      box-shadow:var(--shadow);
    }}
    .cat-summary-label {{
      font-size:10px; font-weight:700; letter-spacing:.18em;
      color:var(--accent); text-transform:uppercase; margin-bottom:10px;
    }}
    .cat-summary-text {{ font-size:13.5px; color:var(--fg2); line-height:1.85; }}

    /* Article detail */
    .detail-cat {{ font-size:11px; font-weight:700; margin-bottom:8px; }}
    .detail-title {{ font-size:20px; font-weight:700; line-height:1.5; margin-bottom:6px; color:var(--fg); }}
    .detail-orig {{ font-size:11px; color:var(--fg3); font-style:italic; margin-bottom:12px; }}
    .detail-meta {{ font-size:12px; color:var(--fg3); margin-bottom:18px; display:flex; gap:14px; flex-wrap:wrap; }}
    .detail-body {{
      background:#fff; border:1px solid var(--rule);
      border-radius:12px; padding:20px 22px;
      font-size:14px; line-height:1.9; color:var(--fg2); margin-bottom:16px;
      box-shadow:var(--shadow);
    }}
    .detail-orig-body {{
      margin-top:14px; padding-top:12px; border-top:1px solid var(--rule);
      font-size:12px; color:var(--fg3); line-height:1.7;
    }}
    .detail-orig-label {{ font-size:10px; color:var(--fg3); margin-bottom:4px; letter-spacing:.1em; font-weight:600; }}
    .source-link {{
      display:inline-flex; align-items:center; gap:6px;
      font-size:12px; color:var(--accent); margin-top:12px;
      border:1px solid #c3d5fa; border-radius:6px; padding:5px 12px;
      background:#eef2ff;
    }}

    /* World trend card */
    .trend-card {{
      background:#fff; border:1px solid var(--rule);
      border-radius:16px; padding:22px 26px; margin-bottom:16px;
      box-shadow:var(--shadow); border-left:4px solid #f59e0b;
    }}
    .trend-label {{
      font-size:10px; font-weight:700; letter-spacing:.18em;
      color:#d97706; text-transform:uppercase; margin-bottom:10px;
    }}
    .trend-text {{ font-size:14px; line-height:1.9; color:var(--fg2); }}

    /* Deep dive */
    .deep-card {{
      background:linear-gradient(135deg, #eef2ff, #f0fdf4);
      border:1px solid #c3d5fa; border-radius:14px; padding:22px 24px;
    }}
    .deep-label {{
      font-size:10px; font-weight:700; letter-spacing:.18em;
      color:var(--accent); text-transform:uppercase; margin-bottom:12px;
    }}
    .deep-text {{ font-size:13.5px; line-height:1.95; color:var(--fg2); }}
    .deep-btn {{
      background:#1a56db; border:none; color:#fff;
      padding:10px 22px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600;
      display:inline-flex; align-items:center; gap:6px;
      box-shadow:0 2px 8px rgba(26,86,219,.25); transition:all .15s;
    }}
    .deep-btn:hover {{ background:#1e40af; transform:translateY(-1px); }}
    .deep-loading {{ font-size:13px; color:var(--fg3); }}

    /* Save bar */
    .save-bar {{
      position:fixed; bottom:0; left:0; right:0;
      background:#fff; border-top:1px solid var(--rule);
      padding:12px 24px; display:flex; align-items:center; justify-content:space-between;
      z-index:200; box-shadow:0 -2px 12px rgba(0,0,0,.08);
    }}
    .save-count {{ font-size:13px; color:var(--fg2); font-weight:500; }}
    .save-btn {{
      background:var(--accent2); border:none; color:#fff;
      padding:10px 24px; border-radius:8px; cursor:pointer;
      font-size:14px; font-weight:700; box-shadow:0 2px 8px rgba(14,159,110,.3);
    }}
    .save-btn:disabled {{ background:var(--fg3); cursor:not-allowed; box-shadow:none; }}
    .check-wrap {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
    .check-wrap input[type=checkbox] {{ width:18px; height:18px; cursor:pointer; accent-color:var(--accent); }}
    .check-label {{ font-size:12px; color:var(--fg3); cursor:pointer; }}
    .saved-badge {{
      display:inline-flex; align-items:center; gap:4px;
      font-size:11px; font-weight:600; color:var(--accent2);
      background:#f0fdf4; border:1px solid #bbf7d0;
      padding:2px 8px; border-radius:20px; margin-bottom:8px;
    }}

    footer {{
      text-align:center; font-size:11px; color:var(--fg3);
      padding:20px; border-top:1px solid var(--rule); margin-top:40px;
    }}
  </style>
</head>
<body>

<header class="site-header">
  <div class="site-logo">📋 Daily Digest</div>
  <div class="nav-center">
    <button class="nav-arrow" id="prevBtn" onclick="goToDate('prev')" title="前日">‹</button>
    <button class="date-btn" onclick="toggleCalendar()" title="カレンダー">
      📅 {date_str}
    </button>
    <button class="nav-arrow" id="nextBtn" onclick="goToDate('next')" title="翌日">›</button>
  </div>
  <button class="back-btn" id="backBtn" onclick="goBack()">← 戻る</button>
</header>

<!-- カレンダーモーダル -->
<div id="calendarOverlay" onclick="closeCalendar()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.3);z-index:300;"></div>
<div id="calendarModal" style="display:none;position:fixed;top:64px;left:50%;transform:translateX(-50%);
  background:#fff;border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,.15);
  padding:20px;z-index:301;width:320px;max-width:90vw;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <button onclick="changeCalMonth(-1)" style="background:none;border:none;font-size:20px;cursor:pointer;color:#4a5168;">‹</button>
    <div id="calMonthLabel" style="font-weight:700;font-size:15px;color:#1a1d23;"></div>
    <button onclick="changeCalMonth(1)" style="background:none;border:none;font-size:20px;cursor:pointer;color:#4a5168;">›</button>
  </div>
  <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center;margin-bottom:8px;">
    <div style="font-size:11px;color:#9299aa;font-weight:600;">日</div>
    <div style="font-size:11px;color:#9299aa;font-weight:600;">月</div>
    <div style="font-size:11px;color:#9299aa;font-weight:600;">火</div>
    <div style="font-size:11px;color:#9299aa;font-weight:600;">水</div>
    <div style="font-size:11px;color:#9299aa;font-weight:600;">木</div>
    <div style="font-size:11px;color:#9299aa;font-weight:600;">金</div>
    <div style="font-size:11px;color:#9299aa;font-weight:600;">土</div>
  </div>
  <div id="calGrid" style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center;"></div>
</div>

<!-- TOP PAGE -->
<div class="page active" id="page-top">
  {f'''<div class="trend-card">
    <div class="trend-label">🌍 今日の世界トレンド</div>
    <div class="trend-text">{world_trend}</div>
  </div>''' if world_trend else ''}
  <div class="summary-card">
    <div class="summary-label">📋 本日の関連ニュースサマリー</div>
    <div class="summary-text">{overall_summary}</div>
  </div>

  <div class="section-head">カテゴリ別トレンド</div>
  <div class="cat-grid">
    {cat_cards_html}
  </div>

  <div class="section-head">全記事一覧（{len(articles)}件）</div>
  <div id="all-articles">
    {all_articles_html}
  </div>
</div>

<!-- CATEGORY PAGE -->
<div class="page" id="page-cat">
  <div class="cat-page-head">
    <div class="cat-page-icon" id="cat-icon"></div>
    <div class="cat-page-name" id="cat-name"></div>
    <div class="cat-summary-box">
      <div class="cat-summary-label">📊 カテゴリトレンド分析</div>
      <div class="cat-summary-text" id="cat-summary-text"></div>
    </div>
    <div class="section-head" id="cat-count-head"></div>
    <div id="cat-articles"></div>
  </div>
</div>

<!-- ARTICLE PAGE -->
<div class="page" id="page-article">
  <div class="detail-cat" id="det-cat"></div>
  <div class="detail-title" id="det-title"></div>
  <div class="detail-orig" id="det-orig"></div>
  <div class="detail-meta" id="det-meta"></div>
  <div class="section-head" id="det-body-label"></div>
  <div class="detail-body" id="det-body"></div>
  <div class="deep-card">
    <div class="deep-label">🔍 もっと調べる</div>
    <p style="font-size:13px;color:var(--fg2);margin-bottom:12px;line-height:1.7;">
      Perplexity AIがこの記事のトピックについてウェブ上の最新情報を収集・日本語でまとめます。
    </p>
    <button class="deep-btn" id="perplexity-btn" onclick="openPerplexity()">🔍 Perplexityで深掘り</button>
  </div>
</div>

<footer>
  生成: {today.strftime("%Y-%m-%d %H:%M")} JST　｜　ソース: RSS自動巡回 + Gemini AI　｜
  取得: {all_count}件 / 候補: {candidate_count}件 / 掲載: {len(articles)}件
</footer>

<script>
const ARTICLES = {articles_js};
const THIS_TAG = "{today_tag}"; // このHTMLの日付タグ

// ── 日付ナビゲーション（available_dates.jsonを動的取得）──
let AVAILABLE_DATES = [];

function getCurrentTag() {{
  const path = location.pathname;
  const re = new RegExp('digest_([0-9]{{8}})\\.html');
  const m = path.match(re);
  return m ? m[1] : THIS_TAG;
}}

function tagToUrl(tag) {{
  const latestTag = AVAILABLE_DATES[AVAILABLE_DATES.length - 1];
  if (tag === latestTag) return 'index.html';
  return `digest_${{tag}}.html`;
}}

function goToDate(dir) {{
  const cur = getCurrentTag();
  const idx = AVAILABLE_DATES.indexOf(cur);
  if (dir === 'prev' && idx > 0) location.href = tagToUrl(AVAILABLE_DATES[idx - 1]);
  if (dir === 'next' && idx < AVAILABLE_DATES.length - 1) location.href = tagToUrl(AVAILABLE_DATES[idx + 1]);
}}

function initNavButtons() {{
  const cur = getCurrentTag();
  const idx = AVAILABLE_DATES.indexOf(cur);
  const prev = document.getElementById('prevBtn');
  const next = document.getElementById('nextBtn');
  if (prev) prev.disabled = idx <= 0;
  if (next) next.disabled = idx >= AVAILABLE_DATES.length - 1;
}}

async function loadAvailableDates() {{
  try {{
    const base = location.href.substring(0, location.href.lastIndexOf('/') + 1);
    const url = base.includes('/docs/') ? base + '../available_dates.json'
              : base + 'available_dates.json';
    const res = await fetch(url);
    AVAILABLE_DATES = res.ok ? await res.json() : [THIS_TAG];
  }} catch(e) {{
    AVAILABLE_DATES = [THIS_TAG];
  }}
  initNavButtons();
}}

// ── カレンダー ──────────────────────────────────────
let calYear, calMonth;

function toggleCalendar() {{
  const modal = document.getElementById('calendarModal');
  const overlay = document.getElementById('calendarOverlay');
  if (modal.style.display === 'none') {{
    const cur = getCurrentTag();
    calYear = parseInt(cur.slice(0, 4));
    calMonth = parseInt(cur.slice(4, 6));
    renderCalendar();
    modal.style.display = 'block';
    overlay.style.display = 'block';
  }} else {{
    closeCalendar();
  }}
}}

function closeCalendar() {{
  document.getElementById('calendarModal').style.display = 'none';
  document.getElementById('calendarOverlay').style.display = 'none';
}}

function changeCalMonth(dir) {{
  calMonth += dir;
  if (calMonth > 12) {{ calMonth = 1; calYear++; }}
  if (calMonth < 1)  {{ calMonth = 12; calYear--; }}
  renderCalendar();
}}

function renderCalendar() {{
  const label = document.getElementById('calMonthLabel');
  const grid  = document.getElementById('calGrid');
  label.textContent = `${{calYear}}年${{calMonth}}月`;

  const firstDay = new Date(calYear, calMonth - 1, 1).getDay();
  const daysInMonth = new Date(calYear, calMonth, 0).getDate();
  const dateSet = new Set(AVAILABLE_DATES);
  const cur = getCurrentTag();

  let html = '';
  // 空白セル
  for (let i = 0; i < firstDay; i++) html += '<div></div>';
  // 日付セル
  for (let d = 1; d <= daysInMonth; d++) {{
    const tag = `${{calYear}}${{String(calMonth).padStart(2,'0')}}${{String(d).padStart(2,'0')}}`;
    const hasData = dateSet.has(tag);
    const isCur = tag === cur;
    const style = isCur
      ? 'background:#1a56db;color:#fff;border-radius:50%;font-weight:700;cursor:pointer;padding:5px 0;font-size:13px;'
      : hasData
        ? 'color:#1a56db;font-weight:600;cursor:pointer;padding:5px 0;font-size:13px;border-radius:50%;'
        : 'color:#d1d5db;padding:5px 0;font-size:13px;';
    const onclick = hasData ? `onclick="location.href='${{tagToUrl(tag)}}';"` : '';
    html += `<div style="${{style}}" ${{onclick}}>${{d}}</div>`;
  }}
  grid.innerHTML = html;
}}

document.addEventListener('DOMContentLoaded', loadAvailableDates);
const CAT_ICONS  = {json.dumps(CAT_ICONS,  ensure_ascii=False)};
const CAT_COLORS = {json.dumps(CAT_COLORS, ensure_ascii=False)};
const CAT_SUMMARIES = {json.dumps(cat_summaries, ensure_ascii=False)};
const GAS_URL = "https://script.google.com/macros/s/AKfycbz9Nc874Azvh8zqv5BySUGToK01aIkInocGYeqxgyyiJ-fN0YCqIW4h2E9NRkYBQ8bO/exec";

let history = ["top"];
let currentArticleIdx = null;

function showPage(id) {{
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.getElementById("page-" + id).classList.add("active");
  document.getElementById("backBtn").classList.toggle("visible", id !== "top");
  window.scrollTo(0, 0);
}}

function goBack() {{
  history.pop();
  const prev = history[history.length - 1];
  if (prev === "top") showPage("top");
  else if (prev && prev.startsWith("cat:")) showCategory(prev.slice(4), false);
}}

function showCategory(cat, push=true) {{
  if (push) history.push("cat:" + cat);
  document.getElementById("cat-icon").textContent = CAT_ICONS[cat] || "📰";
  document.getElementById("cat-name").textContent = cat;
  document.getElementById("cat-summary-text").textContent = CAT_SUMMARIES[cat] || "";
  const arts = ARTICLES.filter(a => a.category === cat).sort((a,b) => b.relevance_score - a.relevance_score);
  document.getElementById("cat-count-head").textContent = arts.length + "件の記事";
  document.getElementById("cat-articles").innerHTML = arts.map(a => {{
    const idx = ARTICLES.indexOf(a);
    const color = CAT_COLORS[cat] || "#555";
    const stars = "★".repeat(a.relevance_score||3) + "☆".repeat(5-(a.relevance_score||3));
    return `<div class="article-item" onclick="showArticle(${{idx}})" style="border-left:3px solid ${{color}}">
      <div class="article-meta">
        <span class="art-src">${{a.source}}</span>
        <span class="art-stars">${{stars}}</span>
      </div>
      <div class="article-title">${{a.title_ja || a.title}}</div>
      <div class="article-summary">${{a.summary_ja || ""}}</div>
    </div>`;
  }}).join("");
  showPage("cat");
}}

function showArticle(idx, push=true) {{
  if (push) history.push("article:" + idx);
  currentArticleIdx = idx;
  const a = ARTICLES[idx];
  const cat = a.category || "その他";
  const color = CAT_COLORS[cat] || "#555";
  document.getElementById("det-cat").innerHTML = `<span style="color:${{color}}">${{CAT_ICONS[cat]||"📰"}} ${{cat}}</span>`;
  document.getElementById("det-title").textContent = a.title_ja || a.title;
  document.getElementById("det-orig").textContent = a.title_ja && a.title_ja !== a.title ? "原題: " + a.title : "";
  document.getElementById("det-meta").innerHTML = `<span>${{a.source}}</span><span>${{(a.published||"").slice(0,16).replace("T"," ")}}</span>`;
  const isTranslated = a.body_ja && a.body_ja !== a.body;
  document.getElementById("det-body-label").textContent = isTranslated ? "記事本文（日本語訳）" : "記事本文";
  const origText = (a.body && a.body !== "undefined") ? a.body : "";
  document.getElementById("det-body").innerHTML =
    (a.body_ja || origText || "") +
    (isTranslated && origText ? `<div class="detail-orig-body"><div class="detail-orig-label">ORIGINAL</div>${{origText}}</div>` : "") +
    `<br><a href="${{a.link}}" target="_blank" rel="noopener" class="source-link">🔗 元記事を開く</a>`;
  showPage("article");
  showPage("article");
}}

function updateCount() {{
  const checked = document.querySelectorAll('#all-articles input[type=checkbox]:checked').length;
  document.getElementById('save-count').textContent = `チェックした記事: ${{checked}}件`;
  document.getElementById('save-btn').disabled = checked === 0;
}}

// 保存済みIDをセッション内で管理
const savedIds = new Set();

function markAsSaved(idx) {{
  savedIds.add(idx);
  const item = document.querySelector(`[data-idx="${{idx}}"]`);
  if (!item) return;
  // チェックボックスを非表示にして保存済みバッジを表示
  const wrap = item.querySelector('.check-wrap');
  if (wrap) wrap.style.display = 'none';
  if (!item.querySelector('.saved-badge')) {{
    const badge = document.createElement('div');
    badge.className = 'saved-badge';
    badge.textContent = '✅ 保存済み';
    item.insertBefore(badge, item.firstChild);
  }}
}}

async function saveChecked() {{
  const checkboxes = document.querySelectorAll('#all-articles input[type=checkbox]:checked');
  if (checkboxes.length === 0) return;
  const articles = [];
  const idxList = [];
  checkboxes.forEach(cb => {{
    const idx = parseInt(cb.id.replace('chk-', ''));
    articles.push(ARTICLES[idx]);
    idxList.push(idx);
  }});
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  btn.textContent = '保存中...';
  try {{
    await fetch(GAS_URL, {{
      method: 'POST',
      mode: 'no-cors',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ articles }})
    }});
    btn.textContent = '✅ 保存しました';
    // 保存済みバッジを付与
    idxList.forEach(idx => markAsSaved(idx));
    updateCount();
    setTimeout(() => {{
      btn.textContent = '📥 スプレッドシートに保存';
    }}, 3000);
  }} catch(e) {{
    btn.textContent = 'エラー: ' + e.message;
    btn.disabled = false;
  }}
}}

function openPerplexity() {{
  const a = ARTICLES[currentArticleIdx];
  const query = encodeURIComponent(a.title_ja || a.title);
  window.open(`https://www.perplexity.ai/search?q=${{query}}`, '_blank');
}}
</script>

<div class="save-bar">
  <div class="save-count" id="save-count">チェックした記事: 0件</div>
  <button class="save-btn" id="save-btn" onclick="saveChecked()" disabled>📥 スプレッドシートに保存</button>
</div>
</body>
</html>"""
    return html

# ========== メイン ==========

def main():
    model = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options={"api_version": "v1"},
    )

    print(f"[{datetime.now().strftime('%H:%M:%S')}] RSS取得中...")
    all_articles, trend_articles = fetch_feeds(hours_back=24)
    print(f"  → 通常記事: {len(all_articles)}件 / トレンド記事: {len(trend_articles)}件")

    candidates = [a for a in all_articles if keyword_score(a) > 0]
    candidates.sort(key=keyword_score, reverse=True)
    candidates = candidates[:60]
    print(f"  → キーワード候補: {len(candidates)}件")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Geminiで分析・翻訳中...")
    articles = analyze_articles(model, candidates)
    print(f"  → 関連記事: {len(articles)}件")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 過去データ取得中...")
    past_digests = get_past_digests(days=3)
    print(f"  → {len(past_digests)}日分の過去データを取得")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 全体サマリー生成中...")
    overall_summary = generate_overall_summary(model, articles, past_digests)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 世界トレンド分析中...")
    world_trend = generate_world_trend(model, trend_articles)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] カテゴリ分析中...")
    cat_summaries = generate_cat_summaries(model, articles, past_digests)

    html = build_html(articles, overall_summary, world_trend, cat_summaries, len(all_articles), len(candidates))

    date_tag = datetime.now().strftime("%Y%m%d")
    out = Path(f"digest_{date_tag}.html")
    out.write_text(html, encoding="utf-8")
    print(f"  → 出力: {out}")

if __name__ == "__main__":
    main()
