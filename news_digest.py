#!/usr/bin/env python3
"""
news_digest.py — 毎日ニュース自動巡回スクリプト v2
機能: RSS巡回 → Geminiで翻訳・全体サマリー・カテゴリ分析 → インタラクティブHTML出力
"""

import feedparser
import google.generativeai as genai
import os, json, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ========== 設定 ==========

KEYWORDS = [
    # タイ関連（広め）
    "Thailand", "Thai", "タイ", "Bangkok", "バンコク",
    # ボイラー・産業設備
    "boiler", "ボイラー", "stoker", "steam", "industrial",
    # バイオマス・エネルギー
    "biomass", "バイオマス", "EFB", "palm", "renewable energy",
    "energy", "エネルギー", "fuel", "combustion",
    # 日タイ貿易
    "Japan", "日本", "JTEPA", "trade", "export", "import", "貿易", "輸出", "輸入",
    # 為替
    "JPY", "THB", "yen", "baht", "円", "バーツ", "為替", "exchange rate",
    "USD", "dollar", "ドル",
    # アジア経済
    "ASEAN", "Southeast Asia", "東南アジア", "Asia",
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
]

CAT_ICONS  = {"ボイラー/産業設備": "🔧", "バイオマス/エネルギー": "🌿", "日タイ貿易/ビジネス": "🤝", "為替/金融": "💹", "その他": "📰"}
CAT_COLORS = {"ボイラー/産業設備": "#b45309", "バイオマス/エネルギー": "#2d7a4f", "日タイ貿易/ビジネス": "#1d4ed8", "為替/金融": "#7c3aed", "その他": "#555"}

# ========== RSS取得 ==========

def fetch_feeds(hours_back=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    articles = []
    for fi in RSS_FEEDS:
        count = 0
        try:
            feed = feedparser.parse(fi["url"])
            total = len(feed.entries)
            for entry in feed.entries[:20]:
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
                articles.append({
                    "source": fi["name"], "lang": fi["lang"],
                    "title": title, "body": summary,
                    "link": entry.get("link", ""),
                    "published": published.isoformat(),
                })
                count += 1
            status = feed.get("status", "?")
            print(f"  [{status}] {fi['name']}: {count}件採用 / {total}件取得")
        except Exception as e:
            print(f"  [ERR] {fi['name']}: {e}")
    return articles

def keyword_score(a):
    text = (a["title"] + " " + a["body"]).lower()
    return sum(1 for kw in KEYWORDS if kw.lower() in text)

# ========== Gemini 呼び出し ==========

def gemini(model, prompt):
    raw = model.generate_content(prompt).text.strip()
    return re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()

def analyze_articles(model, candidates):
    """記事の選別・翻訳・日本語要約・カテゴリ分類を一括実行"""
    if not candidates:
        return []
    payload = json.dumps(candidates, ensure_ascii=False, indent=2)
    prompt = f"""あなたは日タイビジネス専門のアナリストです。
以下の記事リストを分析し、関連する記事だけをJSONで返してください。

【追跡トピック】
1. タイのボイラー業界・産業設備
2. バイオマス燃料・再生可能エネルギー（特に東南アジア）
3. 日タイビジネス・貿易・投資
4. 為替（USD/JPY、THB/JPY）

【指示】
- 関連性が低い記事は除外
- title_ja: タイトルの日本語訳（元が日本語ならそのまま）
- body_ja: 本文の日本語訳（元が日本語ならそのまま）
- summary_ja: 100〜150字の日本語要約（数字・固有名詞を保持）
- category: "ボイラー/産業設備" | "バイオマス/エネルギー" | "日タイ貿易/ビジネス" | "為替/金融"
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

def generate_overall_summary(model, articles):
    """全記事から全体サマリーを生成"""
    if not articles:
        return "本日、関連ニュースは見つかりませんでした。"
    article_list = "\n".join([f"[{a['category']}] {a['title_ja']}" for a in articles])
    prompt = f"""以下の本日のニュース記事一覧から、全体的な市場動向・トレンドを200字程度で分析してください。
箇条書きではなく流れのある文章で。重要な数字や固有名詞は残してください。

{article_list}"""
    return gemini(model, prompt)

def generate_cat_summaries(model, articles):
    """カテゴリ別トレンド分析を生成"""
    from collections import defaultdict
    by_cat = defaultdict(list)
    for a in articles:
        by_cat[a["category"]].append(a)

    summaries = {}
    for cat, arts in by_cat.items():
        titles = "\n".join([f"・{a['title_ja']}" for a in arts])
        prompt = f"""以下の「{cat}」カテゴリの記事群から、現在のトレンドと注目点を120字程度で分析してください。
実務担当者向けに、文章形式で簡潔に。

{titles}"""
        summaries[cat] = gemini(model, prompt)
    return summaries

# ========== HTML生成 ==========

def build_html(articles, overall_summary, cat_summaries, all_count, candidate_count):
    today    = datetime.now(tz=timezone(timedelta(hours=9)))
    date_str = today.strftime("%Y年%m月%d日（%a）")

    # 記事データをJSに埋め込む（深掘り用）
    articles_js = json.dumps(articles, ensure_ascii=False)

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
        <div class="article-item" style="border-left:3px solid {color}" data-cat="{cat}" data-idx="{i}">
          <div class="check-wrap">
            <input type="checkbox" id="chk-{i}" onchange="updateCount()" onclick="event.stopPropagation()">
            <label class="check-label" for="chk-{i}">保存する</label>
          </div>
          <div onclick="showArticle({i})">
            <div class="article-meta">
              <span class="art-cat" style="color:{color}">{icon} {cat}</span>
              <span class="art-src">{a['source']}</span>
              <span class="art-stars">{stars}</span>
            </div>
            <div class="article-title">{a.get('title_ja', a['title'])}</div>
            <div class="article-summary">{a.get('summary_ja', '')}</div>
          </div>
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
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Noto+Serif+JP:wght@700&display=swap');
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0f1117; --bg2: #141824; --bg3: #1a1f2e;
      --fg: #e8e4dc; --fg2: #b0aaa4; --fg3: #5a6070;
      --accent: #6b9fff; --rule: #252a3a;
    }}
    body {{ font-family:'Noto Sans JP',sans-serif; background:var(--bg); color:var(--fg); line-height:1.7; }}
    a {{ color:var(--accent); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}

    /* Header */
    .site-header {{
      position:sticky; top:0; z-index:100;
      background:var(--bg); border-bottom:1px solid var(--rule);
      padding:16px 20px; display:flex; align-items:center; justify-content:space-between;
    }}
    .site-logo {{ font-size:13px; font-weight:700; letter-spacing:.15em; color:var(--accent); }}
    .site-date {{ font-size:12px; color:var(--fg3); }}
    .back-btn {{
      display:none; background:none; border:1px solid var(--rule);
      color:var(--fg3); padding:5px 12px; border-radius:6px; cursor:pointer; font-size:12px;
    }}
    .back-btn.visible {{ display:block; }}

    /* Pages */
    .page {{ display:none; max-width:760px; margin:0 auto; padding:24px 20px 60px; }}
    .page.active {{ display:block; }}

    /* Overall summary */
    .summary-card {{
      background:linear-gradient(135deg,var(--bg2),var(--bg3));
      border:1px solid var(--rule); border-radius:12px;
      padding:20px 24px; margin-bottom:24px;
    }}
    .summary-label {{
      font-size:10px; font-weight:700; letter-spacing:.2em;
      color:var(--accent); text-transform:uppercase; margin-bottom:10px;
    }}
    .summary-text {{ font-size:14px; line-height:1.9; color:var(--fg2); }}

    /* Category cards */
    .section-head {{
      font-size:11px; font-weight:700; letter-spacing:.18em;
      color:var(--fg3); text-transform:uppercase;
      border-bottom:1px solid var(--rule); padding-bottom:8px; margin-bottom:14px;
    }}
    .cat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:28px; }}
    .cat-card {{
      background:var(--bg2); border-radius:10px; padding:16px 18px;
      cursor:pointer; transition:background .15s;
    }}
    .cat-card:hover {{ background:var(--bg3); }}
    .cat-card-head {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
    .cat-icon {{ font-size:20px; }}
    .cat-name {{ font-size:13px; font-weight:600; flex:1; }}
    .cat-count {{
      font-size:11px; color:var(--fg3);
      background:var(--rule); padding:2px 8px; border-radius:10px;
    }}
    .cat-trend {{ font-size:12px; color:var(--fg3); line-height:1.7; }}

    /* Article items */
    .article-item {{
      background:var(--bg2); border-radius:8px;
      padding:14px 18px; margin-bottom:10px; cursor:pointer; transition:background .15s;
    }}
    .article-item:hover {{ background:var(--bg3); }}
    .article-meta {{ display:flex; gap:10px; font-size:11px; color:var(--fg3); margin-bottom:5px; flex-wrap:wrap; }}
    .art-stars {{ color:#c8a400; letter-spacing:-1px; }}
    .article-title {{ font-size:14px; font-weight:500; color:var(--fg); line-height:1.5; margin-bottom:5px; }}
    .article-summary {{ font-size:12px; color:var(--fg3); line-height:1.65; }}
    .no-news {{ text-align:center; color:var(--fg3); padding:40px; }}

    /* Category page */
    .cat-page-head {{ margin-bottom:20px; }}
    .cat-page-icon {{ font-size:28px; margin-bottom:6px; }}
    .cat-page-name {{ font-size:20px; font-weight:700; margin-bottom:16px; }}
    .cat-summary-box {{
      background:var(--bg2); border:1px solid var(--rule);
      border-radius:10px; padding:16px 18px; margin-bottom:20px;
    }}
    .cat-summary-label {{
      font-size:10px; font-weight:700; letter-spacing:.18em;
      color:var(--accent); text-transform:uppercase; margin-bottom:8px;
    }}
    .cat-summary-text {{ font-size:13px; color:var(--fg2); line-height:1.85; }}

    /* Article detail */
    .detail-cat {{ font-size:11px; font-weight:600; margin-bottom:8px; }}
    .detail-title {{ font-size:18px; font-weight:700; line-height:1.5; margin-bottom:6px; }}
    .detail-orig {{ font-size:11px; color:var(--fg3); font-style:italic; margin-bottom:12px; }}
    .detail-meta {{ font-size:11px; color:var(--fg3); margin-bottom:16px; display:flex; gap:12px; }}
    .detail-body {{
      background:var(--bg2); border:1px solid var(--rule);
      border-radius:10px; padding:16px 18px;
      font-size:13.5px; line-height:1.85; color:#9098a8; margin-bottom:16px;
    }}
    .detail-orig-body {{
      margin-top:12px; padding-top:10px; border-top:1px solid var(--rule);
      font-size:12px; color:#3a4050;
    }}
    .detail-orig-label {{ font-size:10px; color:var(--fg3); margin-bottom:4px; letter-spacing:.1em; }}
    .source-link {{
      display:inline-flex; align-items:center; gap:5px;
      font-size:11px; color:var(--accent); margin-top:10px;
      border:1px solid #1a2f5a; border-radius:5px; padding:4px 10px;
    }}

    /* Deep dive */
    .deep-card {{
      background:linear-gradient(135deg,var(--bg2),#1a2030);
      border:1px solid #2a3a5a; border-radius:12px; padding:20px 22px;
    }}
    .deep-label {{
      font-size:10px; font-weight:700; letter-spacing:.2em;
      color:var(--accent); text-transform:uppercase; margin-bottom:12px;
    }}
    .deep-text {{ font-size:13.5px; line-height:1.95; color:var(--fg2); }}
    .deep-btn {{
      background:#1a2f5a; border:none; color:var(--accent);
      padding:8px 16px; border-radius:6px; cursor:pointer; font-size:13px;
    }}
    .deep-loading {{ font-size:13px; color:var(--fg3); }}

    /* Save bar */
    .save-bar {{
      position:fixed; bottom:0; left:0; right:0;
      background:var(--bg2); border-top:1px solid var(--rule);
      padding:12px 20px; display:flex; align-items:center; justify-content:space-between;
      z-index:200;
    }}
    .save-count {{ font-size:13px; color:var(--fg3); }}
    .save-btn {{
      background:var(--accent); border:none; color:#fff;
      padding:10px 24px; border-radius:8px; cursor:pointer;
      font-size:14px; font-weight:700;
    }}
    .save-btn:disabled {{ background:var(--fg3); cursor:not-allowed; }}
    .check-wrap {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; }}
    .check-wrap input[type=checkbox] {{ width:18px; height:18px; cursor:pointer; accent-color:var(--accent); }}
    .check-label {{ font-size:12px; color:var(--fg3); cursor:pointer; }}

    footer {{
      text-align:center; font-size:11px; color:var(--fg3);
      padding:20px; border-top:1px solid var(--rule); margin-top:40px;
    }}
  </style>
</head>
<body>

<header class="site-header">
  <div class="site-logo">📋 Daily Digest</div>
  <div class="site-date">{date_str}</div>
  <button class="back-btn" id="backBtn" onclick="goBack()">← 戻る</button>
</header>

<!-- TOP PAGE -->
<div class="page active" id="page-top">
  <div class="summary-card">
    <div class="summary-label">🌐 本日の全体サマリー</div>
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
    <div class="deep-label">🔬 AI 深掘り分析</div>
    <div id="deep-content"><button class="deep-btn" onclick="loadDeepDive()">分析を生成</button></div>
  </div>
</div>

<footer>
  生成: {today.strftime("%Y-%m-%d %H:%M")} JST　｜　ソース: RSS自動巡回 + Gemini AI　｜
  取得: {all_count}件 / 候補: {candidate_count}件 / 掲載: {len(articles)}件
</footer>

<script>
const ARTICLES = {articles_js};
const CAT_ICONS  = {json.dumps(CAT_ICONS,  ensure_ascii=False)};
const CAT_COLORS = {json.dumps(CAT_COLORS, ensure_ascii=False)};
const CAT_SUMMARIES = {json.dumps(cat_summaries, ensure_ascii=False)};
const GEMINI_KEY = ""; // ← 深掘り分析を使う場合は aistudio.google.com のAPIキーを入力
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
  document.getElementById("det-body").innerHTML =
    (a.body_ja || a.body || "") +
    (isTranslated ? `<div class="detail-orig-body"><div class="detail-orig-label">ORIGINAL</div>${{a.body}}</div>` : "") +
    `<br><a href="${{a.link}}" target="_blank" rel="noopener" class="source-link">🔗 元記事を開く</a>`;
  document.getElementById("deep-content").innerHTML = '<button class="deep-btn" onclick="loadDeepDive()">分析を生成</button>';
  showPage("article");
}}

function updateCount() {{
  const checked = document.querySelectorAll('#all-articles input[type=checkbox]:checked').length;
  document.getElementById('save-count').textContent = `チェックした記事: ${{checked}}件`;
  document.getElementById('save-btn').disabled = checked === 0;
}}

async function saveChecked() {{
  const checkboxes = document.querySelectorAll('#all-articles input[type=checkbox]:checked');
  if (checkboxes.length === 0) return;
  const articles = [];
  checkboxes.forEach(cb => {{
    const idx = parseInt(cb.id.replace('chk-', ''));
    articles.push(ARTICLES[idx]);
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
    checkboxes.forEach(cb => {{ cb.checked = false; }});
    updateCount();
    setTimeout(() => {{
      btn.textContent = '📥 スプレッドシートに保存';
    }}, 3000);
  }} catch(e) {{
    btn.textContent = 'エラー: ' + e.message;
    btn.disabled = false;
  }}
}}

async function loadDeepDive() {{
  const a = ARTICLES[currentArticleIdx];
  document.getElementById("deep-content").innerHTML = '<div class="deep-loading">⟳ 分析中...</div>';
  if (!GEMINI_KEY) {{
    document.getElementById("deep-content").innerHTML =
      '<div class="deep-loading">※ 深掘り分析にはAPIキーが必要です。HTMLファイル内の GEMINI_KEY を設定してください。</div>';
    return;
  }}
  try {{
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${{GEMINI_KEY}}`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body: JSON.stringify({{ contents:[{{ parts:[{{ text:
        `以下のニュース記事を深掘り分析してください（250〜300字、文章形式）。\\n①市場・業界への示唆\\n②タイのボイラー・バイオマス事業または日タイ貿易への影響\\n③今後の注目点\\n\\n【タイトル】${{a.title_ja||a.title}}\\n【本文】${{a.body_ja||a.body}}\\n【カテゴリ】${{a.category}}`
      }}]}}]}})
    }});
    const data = await res.json();
    const text = data.candidates?.[0]?.content?.parts?.[0]?.text || "分析に失敗しました。";
    document.getElementById("deep-content").innerHTML = `<div class="deep-text">${{text}}</div>`;
  }} catch(e) {{
    document.getElementById("deep-content").innerHTML = `<div class="deep-loading">エラー: ${{e.message}}</div>`;
  }}
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
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] RSS取得中...")
    all_articles = fetch_feeds(hours_back=24)
    print(f"  → {len(all_articles)}件取得")

    candidates = [a for a in all_articles if keyword_score(a) > 0]
    candidates.sort(key=keyword_score, reverse=True)
    candidates = candidates[:40]
    print(f"  → キーワード候補: {len(candidates)}件")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Geminiで分析・翻訳中...")
    articles = analyze_articles(model, candidates)
    print(f"  → 関連記事: {len(articles)}件")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 全体サマリー生成中...")
    overall_summary = generate_overall_summary(model, articles)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] カテゴリ分析中...")
    cat_summaries = generate_cat_summaries(model, articles)

    html = build_html(articles, overall_summary, cat_summaries, len(all_articles), len(candidates))

    date_tag = datetime.now().strftime("%Y%m%d")
    out = Path(f"digest_{date_tag}.html")
    out.write_text(html, encoding="utf-8")
    print(f"  → 出力: {out}")

if __name__ == "__main__":
    main()
