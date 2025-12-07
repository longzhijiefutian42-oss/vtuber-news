# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import random

# ===========================================================
# 設定
# ===========================================================
DICTIONARY_JSON = "dictionary.json"
USE_OLLAMA = False  # Ollamaを使う場合はTrueに変更
OLLAMA_MODEL = "llama3.2"

# タグ抽出ルール（重要）
TAG_RULES = [
    ("新衣装", ["新衣装", "衣装", "お披露目"]),
    ("コラボ", ["コラボ", "タイアップ", "コラボレーション"]),
    ("炎上", ["炎上", "物議", "批判", "謝罪", "不祥事"]),
    ("海外", ["海外", "overseas", "EN ", "global"]),
    ("重大発表", ["重大発表", "卒業", "引退", "発表"]),
    ("イベント", ["イベント", "ライブ", "フェス"]),
]

# ===========================================================
# 辞書ロード
# ===========================================================
try:
    with open(DICTIONARY_JSON, "r", encoding="utf-8") as f:
        DICT = json.load(f)
except FileNotFoundError:
    print(f"❌ {DICTIONARY_JSON} が見つかりません")
    exit(1)

QUERIES = DICT.get("queries", [])
KEYWORDS = DICT.get("keywords", [])
KINJI_COMMENTS = DICT.get("kinji_comments", {})
SETTINGS = DICT.get("settings", {})

NOTE_URL = SETTINGS.get("note_url", "")
LINE_URL = SETTINGS.get("line_url", "")
X_URL = SETTINGS.get("x_url", "")

# ===========================================================
# カテゴリ分類
# ===========================================================
def classify_by_keyword(title, snippet):
    """辞書ベースのカテゴリ分類"""
    text = (title + " " + snippet).lower()
    
    for row in KEYWORDS:
        keyword = str(row.get("keyword", "")).lower()
        category = row.get("category", "")
        if keyword and keyword in text:
            return category
    
    return SETTINGS.get("default_category", "その他")

def category_to_class(category):
    """カテゴリ名をCSSクラス名に変換"""
    return {
        "ホロライブ": "cat-hololive",
        "にじさんじ": "cat-nijisanji",
        "個人VTuber": "cat-indie",
        "企業コラボ": "cat-collab",
        "海外VTuber": "cat-global",
        "トラブル／炎上": "cat-trouble",
        "その他": "cat-none",
    }.get(category, "cat-none")

# ===========================================================
# タグ抽出（重要機能）
# ===========================================================
def extract_tags(title, snippet):
    """記事からタグを抽出（最大3個）"""
    text = (title + " " + snippet).lower()
    tags = []
    
    for label, keywords in TAG_RULES:
        for keyword in keywords:
            if keyword.lower() in text:
                tags.append(label)
                break  # 同じタグは1回だけ
    
    # 重複を除去して最大3個まで
    return list(dict.fromkeys(tags))[:3]

# ===========================================================
# 金次コメント
# ===========================================================
_used_comments = {}

def pick_unique_comment(category):
    """カテゴリ別にユニークな金次コメントを選択"""
    if category not in KINJI_COMMENTS:
        category = "その他"
    
    comments = [c.get("comment_text", "") for c in KINJI_COMMENTS.get(category, [])]
    
    if not comments:
        return ""
    
    used = _used_comments.setdefault(category, set())
    remain = [c for c in comments if c not in used]
    
    if not remain:
        used.clear()
        remain = comments[:]
    
    chosen = random.choice(remain)
    used.add(chosen)
    return chosen

# ===========================================================
# ニュース取得
# ===========================================================
def fetch_all_news():
    """辞書のクエリに基づいてニュースを取得"""
    print("▶ ニュース取得を開始...")
    headers = {"User-Agent": "Mozilla/5.0"}
    all_articles = []
    
    for q in QUERIES:
        if not q.get("enabled", False):
            continue
        
        search_query = q.get("search_query", "").strip()
        max_items = int(q.get("max_items", 3))
        
        print(f"  → {search_query} を取得中...")
        
        url = f"https://www.bing.com/news/search?q={search_query}&format=rss"
        
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "xml")
            
            items = soup.find_all("item")[:max_items]
            
            for item in items:
                article = {
                    "title": item.title.text if item.title else "タイトルなし",
                    "url": item.link.text if item.link else "#",
                    "snippet": item.description.text if item.description else "説明なし",
                    "date": item.pubDate.text if item.pubDate else datetime.now().strftime("%Y-%m-%d"),
                }
                all_articles.append(article)
        
        except Exception as e:
            print(f"⚠ {search_query} の取得失敗:", e)
            continue
    
    print(f"  → 合計 {len(all_articles)} 件取得")
    return all_articles

# ===========================================================
# 重複除去
# ===========================================================
def dedupe_articles(articles):
    """タイトルで重複を除去"""
    seen = set()
    deduped = []
    for a in articles:
        key = a["title"]
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    print(f"  → {len(deduped)} 件に重複除去完了")
    return deduped

# ===========================================================
# Ollama AI分析（Page2用）
# ===========================================================
def analyze_with_ollama_deep(articles):
    """TOP2記事をOllamaで深掘り分析"""
    if not USE_OLLAMA or len(articles) < 2:
        return None
    
    top2 = articles[:2]
    
    prompt = f"""以下のVTuberニュース2件について分析してください。

【記事1】
タイトル: {top2[0]['title']}
内容: {top2[0]['snippet']}

【記事2】
タイトル: {top2[1]['title']}
内容: {top2[1]['snippet']}

以下の形式で回答してください：

■ 要点3行
・
・
・

■ 背景説明
（なぜこのニュースが重要か）

■ 文脈解釈
（VTuber業界全体への影響）

■ 今日の傾向
（本日のニュース全体から読み取れるトレンド）

■ X投稿案
（140字以内で投稿できる文章）"""
    
    try:
        print("  → Ollama分析中...")
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=60
        )
        data = r.json()
        return data.get("response", "")
    except Exception as e:
        print(f"⚠ Ollama分析エラー: {e}")
        return None

# ===========================================================
# JSON保存
# ===========================================================
def save_to_json(articles, date_str):
    """データをJSONで保存"""
    archive_dir = "archive/data"
    os.makedirs(archive_dir, exist_ok=True)
    
    # カテゴリとタグの集計
    categories = {}
    tags = {}
    
    for a in articles:
        cat = a.get("category", "その他")
        categories[cat] = categories.get(cat, 0) + 1
        
        for tag in a.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1
    
    data = {
        "date": date_str,
        "articles": articles,
        "article_count": len(articles),
        "categories": categories,
        "tags": tags
    }
    
    filepath = os.path.join(archive_dir, f"news_{date_str}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✓ データ保存: {filepath}")

# ===========================================================
# Page1生成（ニュース一覧）
# ===========================================================
def build_page1(articles, date_str):
    """Page1: ニュース一覧ページを生成"""
    
    # カード生成（重要：data-category と data-tags を埋め込む）
    cards_html = ""
    for a in articles:
        category = a.get("category", "その他")
        tags = a.get("tags", [])
        class_name = category_to_class(category)
        
        snippet = a['snippet'].replace('<', '&lt;').replace('>', '&gt;')
        if len(snippet) > 150:
            snippet = snippet[:150] + "..."
        
        # タグをカンマ区切りで
        tags_str = ",".join(tags) if tags else ""
        
        # タグチップHTML
        tags_html = ""
        for tag in tags:
            tags_html += f'<span class="tag-chip">{tag}</span>'
        
        # X共有ボタン
        share_text = f"{a['title']} {a['url']}"
        share_url = f"https://twitter.com/intent/tweet?text={requests.utils.quote(share_text)}"
        
        kinji_comment = pick_unique_comment(category)
        
        cards_html += f'''      <article class="card {class_name}"
               data-category="{category}"
               data-tags="{tags_str}">
        <span class="category">{category}</span>
        <h3>{a['title']}</h3>
        <p class="snippet">{snippet}</p>
        <div class="tags-container">
{tags_html}
        </div>'''
        
        if kinji_comment:
            cards_html += f'''
        <div class="kinji-comment">{kinji_comment}</div>'''
        
        cards_html += f'''
        <div class="card-footer">
          <a href="{a['url']}" target="_blank">記事を読む →</a>
          <a href="{share_url}" target="_blank" class="share-x">Xで共有</a>
        </div>
        <span class="date">{a['date']}</span>
      </article>
'''
    
    # 全カテゴリとタグを抽出
    all_categories = sorted(list(set([a.get("category", "その他") for a in articles])))
    all_tags = sorted(list(set([tag for a in articles for tag in a.get("tags", [])])))
    
    # カテゴリタブHTML
    category_tabs = '<button class="tab-btn active" data-filter="all">すべて</button>\n'
    for cat in all_categories:
        category_tabs += f'        <button class="tab-btn" data-filter="{cat}">{cat}</button>\n'
    
    # タグフィルタHTML
    tag_filters = ""
    for tag in all_tags:
        tag_filters += f'        <button class="filter-btn" data-tag="{tag}">{tag}</button>\n'
    
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>本日の備忘録 — {date_str} | {SETTINGS.get("site_title", "金次の寺子屋")}</title>
  <link rel="stylesheet" href="style.css">
  <style>
    /* タブとフィルタ */
    .tabs {{
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }}
    .tab-btn, .filter-btn {{
      padding: 8px 16px;
      border: 1px solid #D1D5DB;
      background: #F9FAFB;
      border-radius: 20px;
      cursor: pointer;
      font-size: 0.9rem;
      transition: all 0.2s;
    }}
    .tab-btn:hover, .filter-btn:hover {{
      background: #E5E7EB;
    }}
    .tab-btn.active {{
      background: #C7463C;
      color: white;
      border-color: #C7463C;
    }}
    .filter-btn.active {{
      background: #D6B86A;
      color: white;
      border-color: #D6B86A;
    }}
    /* タグチップ */
    .tags-container {{
      display: flex;
      gap: 6px;
      margin: 8px 0;
      flex-wrap: wrap;
    }}
    .tag-chip {{
      display: inline-block;
      padding: 4px 10px;
      background: rgba(214, 184, 106, 0.15);
      color: #D6B86A;
      border-radius: 12px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    /* カードフッター */
    .card-footer {{
      display: flex;
      gap: 12px;
      margin-top: 8px;
    }}
    .share-x {{
      color: #1DA1F2;
      font-size: 0.85rem;
      font-weight: 600;
    }}
    /* カード表示制御 */
    .card.hidden {{
      display: none;
    }}
  </style>
</head>
<body class="page-news">

  <header class="site-header">
    <div class="site-header-inner">
      <div class="site-title-group">
        <h1 class="logo-main">{SETTINGS.get("site_title", "金次の寺子屋")}</h1>
        <p class="logo-sub">{SETTINGS.get("site_subtitle", "備忘録")}</p>
      </div>
      <nav class="site-nav">
        <a href="index.html" class="nav-link">トップ</a>
        <a href="page2_{date_str}.html" class="nav-link">AI深掘り</a>
        <a href="archive/index.html" class="nav-link">過去の記録</a>
      </nav>
    </div>
  </header>

  <main class="news-main">
    <div class="page-heading">
      <h2 class="page-title">本日の備忘録 — {date_str}</h2>
      <p class="page-intro">VTuber業界の動きを記録。日々の糧とせよ。</p>
    </div>

    <!-- カテゴリタブ -->
    <div class="tabs">
{category_tabs}
    </div>

    <!-- タグフィルタ -->
    <div class="tabs" style="margin-top: 8px;">
      <span style="font-size: 0.9rem; color: #6B7280; align-self: center;">タグ：</span>
{tag_filters}
    </div>

    <section class="news-section">
      <div class="cards-container">
{cards_html}
      </div>
    </section>

    <section class="news-section">
      <h3 class="section-title">更なる学びへ</h3>
      <div class="callout note-callout">
        <span class="callout-title">📝 noteで詳しく学ぶ</span>
        <p>金次の戦略論・深掘り分析をnoteで公開中。</p>
        <a href="{NOTE_URL}" target="_blank" class="callout-link">noteを読む →</a>
      </div>
      <div class="callout line-callout" style="margin-top:12px;">
        <span class="callout-title">💬 公式LINEで相談</span>
        <p>個別相談・戦略アドバイスはLINEにて。</p>
        <a href="{LINE_URL}" target="_blank" class="callout-link">LINEを追加 →</a>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <p>&copy; 2024 {SETTINGS.get("author_name", "金次")} | VTuber備忘録</p>
  </footer>

  <script>
    // カテゴリフィルタ
    const tabBtns = document.querySelectorAll('.tab-btn');
    const cards = document.querySelectorAll('.card');
    
    tabBtns.forEach(btn => {{
      btn.addEventListener('click', () => {{
        // アクティブ状態切り替え
        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        const filter = btn.dataset.filter;
        
        cards.forEach(card => {{
          if (filter === 'all' || card.dataset.category === filter) {{
            card.classList.remove('hidden');
          }} else {{
            card.classList.add('hidden');
          }}
        }});
      }});
    }});
    
    // タグフィルタ
    const filterBtns = document.querySelectorAll('.filter-btn');
    
    filterBtns.forEach(btn => {{
      btn.addEventListener('click', () => {{
        btn.classList.toggle('active');
        
        // アクティブなタグを取得
        const activeTags = Array.from(filterBtns)
          .filter(b => b.classList.contains('active'))
          .map(b => b.dataset.tag);
        
        cards.forEach(card => {{
          const cardTags = card.dataset.tags ? card.dataset.tags.split(',') : [];
          
          if (activeTags.length === 0) {{
            // タグ選択なし = すべて表示
            card.classList.remove('hidden');
          }} else {{
            // 選択されたタグのいずれかを含むか
            const hasTag = activeTags.some(tag => cardTags.includes(tag));
            if (hasTag) {{
              card.classList.remove('hidden');
            }} else {{
              card.classList.add('hidden');
            }}
          }}
        }});
      }});
    }});
  </script>

</body>
</html>'''
    
    filename = f"news_{date_str}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    
    # アーカイブにもコピー
    archive_dir = "archive"
    os.makedirs(archive_dir, exist_ok=True)
    with open(f"{archive_dir}/{filename}", "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✓ Page1生成: {filename}")
    return filename

# ===========================================================
# Page2生成（AI深掘り）
# ===========================================================
def build_page2(articles, ai_analysis, date_str):
    """Page2: AI深掘りページを生成"""
    
    if not ai_analysis:
        ai_analysis = "※ AI分析は現在利用できません。"
    
    # AI分析をHTMLに変換
    analysis_html = ai_analysis.replace("\n", "<br>")
    
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI深掘り分析 — {date_str} | {SETTINGS.get("site_title", "金次の寺子屋")}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body class="page-news">

  <header class="site-header">
    <div class="site-header-inner">
      <div class="site-title-group">
        <h1 class="logo-main">{SETTINGS.get("site_title", "金次の寺子屋")}</h1>
        <p class="logo-sub">AI深掘り分析</p>
      </div>
      <nav class="site-nav">
        <a href="index.html" class="nav-link">トップ</a>
        <a href="news_{date_str}.html" class="nav-link">ニュース一覧</a>
        <a href="archive/index.html" class="nav-link">過去の記録</a>
      </nav>
    </div>
  </header>

  <main class="news-main">
    <div class="page-heading">
      <h2 class="page-title">AI深掘り分析 — {date_str}</h2>
      <p class="page-intro">本日の注目記事をAIが深掘り分析。</p>
    </div>

    <section class="news-section">
      <div class="bamc-block" style="line-height: 1.8;">
{analysis_html}
      </div>
    </section>

    <section class="news-section">
      <a href="news_{date_str}.html" class="btn-primary">← ニュース一覧に戻る</a>
    </section>
  </main>

  <footer class="site-footer">
    <p>&copy; 2024 {SETTINGS.get("author_name", "金次")} | VTuber備忘録</p>
  </footer>

</body>
</html>'''
    
    filename = f"page2_{date_str}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✓ Page2生成: {filename}")
    return filename

# ===========================================================
# ポータルとアーカイブ
# ===========================================================
def create_portal_page(latest_file):
    """index.htmlを生成"""
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{SETTINGS.get("site_title", "金次の寺子屋")}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body class="page-portal">

  <header class="site-header">
    <div class="site-header-inner">
      <div class="site-title-group">
        <h1 class="logo-main">{SETTINGS.get("site_title", "金次の寺子屋")}</h1>
        <p class="logo-sub">{SETTINGS.get("site_subtitle", "備忘録")}</p>
        <p class="logo-tagline">{SETTINGS.get("site_tagline", "明日を拓く者への道標")}</p>
      </div>
    </div>
  </header>

  <main class="portal-main">
    <div class="hero">
      <h2 class="hero-lead">VTuber業界の日々を記録し、道を照らす。</h2>
      <p class="hero-text">
        金次が毎日VTuberニュースを収集・分析。<br>
        タグフィルタとAI深掘りで、個人勢VTuberの成長を支援する。
      </p>
      <div class="hero-actions">
        <a href="{latest_file}" class="btn-primary">本日の備忘録を見る</a>
        <a href="archive/index.html" class="btn-secondary">過去の記録</a>
      </div>
    </div>
  </main>

  <footer class="site-footer">
    <p>&copy; 2024 {SETTINGS.get("author_name", "金次")} | VTuber備忘録</p>
  </footer>

</body>
</html>'''
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print("✓ ポータルページ作成: index.html")

def create_archive_index():
    """アーカイブ一覧ページを生成"""
    archive_dir = "archive"
    files = sorted([f for f in os.listdir(archive_dir) if f.startswith("news_") and f.endswith(".html")], reverse=True)
    
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>過去の記録 | {SETTINGS.get("site_title", "金次の寺子屋")}</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <h1 class="logo-main">過去の備忘録</h1>
      <nav class="site-nav">
        <a href="../index.html" class="nav-link">トップ</a>
      </nav>
    </div>
  </header>

  <main class="archive-container">
    <div class="archive-list">
'''
    
    for filename in files:
        date_str = filename.replace("news_", "").replace(".html", "")
        html += f'      <div class="archive-item"><a href="{filename}"><span>{date_str} の記録</span><span class="archive-arrow">→</span></a></div>\n'
    
    html += '''    </div>
  </main>
</body>
</html>'''
    
    with open(f"{archive_dir}/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print("✓ アーカイブインデックス作成")

# ===========================================================
# メイン
# ===========================================================
def main():
    print("\n========== VTuberニュースサイト完全版生成 ==========")
    
    # ① ニュース取得
    articles_all = fetch_all_news()
    articles = dedupe_articles(articles_all)
    
    if not articles:
        print("❌ ニュースが取得できませんでした")
        return
    
    # ② カテゴリとタグを付与
    print("\n▶ カテゴリ・タグ分析中...")
    for a in articles:
        a["category"] = classify_by_keyword(a["title"], a["snippet"])
        a["tags"] = extract_tags(a["title"], a["snippet"])
    
    print(f"✓ {len(articles)}件の記事を分析完了")
    
    # ③ JSON保存
    date_str = datetime.today().strftime("%Y-%m-%d")
    save_to_json(articles, date_str)
    
    # ④ Page1生成
    print("\n▶ Page1（ニュース一覧）生成中...")
    page1_file = build_page1(articles, date_str)
    
    # ⑤ Page2生成（AI深掘り）
    print("\n▶ Page2（AI深掘り）生成中...")
    ai_analysis = analyze_with_ollama_deep(articles) if USE_OLLAMA else None
    page2_file = build_page2(articles, ai_analysis, date_str)
    
    # ⑥ ポータルとアーカイブ
    create_portal_page(page1_file)
    create_archive_index()
    
    print("\n" + "=" * 50)
    print(f"✅ 生成完了")
    print(f"  Page1: {page1_file}")
    print(f"  Page2: {page2_file}")
    print("=" * 50)

if __name__ == "__main__":
    main()
