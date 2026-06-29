#!/usr/bin/env python3
"""每日摄影推荐生成器

从 bank.json 选取 20 幅作品，生成 docs/index.html，
归档旧版到 docs/archive/，更新 data/history.json 避免重复推荐。
"""

import json
import os
import random
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
DOCS_DIR = os.path.join(PROJECT_DIR, "docs")
TEMPLATES_DIR = os.path.join(PROJECT_DIR, "templates")

BANK_PATH = os.path.join(DATA_DIR, "bank.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "index.html")
INDEX_PATH = os.path.join(DOCS_DIR, "index.html")
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")

DAILY_COUNT = 20
REPEAT_COOLDOWN_DAYS = 30


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_or_rebuild_history():
    """加载历史记录；缺失时从归档页与当前首页重建。"""
    if os.path.exists(HISTORY_PATH):
        return load_json(HISTORY_PATH)

    import re

    print("  历史记录缺失，从归档页重建...")
    history = []

    if os.path.isdir(ARCHIVE_DIR):
        for fname in sorted(os.listdir(ARCHIVE_DIR)):
            if fname.endswith(".html") and fname != "index.html":
                date_str = fname.replace(".html", "")
                path = os.path.join(ARCHIVE_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    photos = extract_photos_from_html(f.read())
                if photos:
                    history.append({"date": date_str, "photos": photos})

    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        photos = extract_photos_from_html(html)
        date_match = re.search(r'<div class="date">(\d{4})年(\d{2})月(\d{2})日', html)
        if photos and date_match:
            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            if not any(r["date"] == date_str for r in history):
                history.append({"date": date_str, "photos": photos})

    history.sort(key=lambda r: r["date"])
    if history:
        save_json(HISTORY_PATH, history)
        print(f"  已重建历史: {len(history)} 期")
    return history


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_template(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_recently_used_ids(history, days=REPEAT_COOLDOWN_DAYS):
    """返回最近 N 天已推荐过的作品 ID 集合。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    used = set()
    for record in history:
        if record.get("date", "") >= cutoff:
            for photo in record.get("photos", []):
                used.add(photo["id"])
    return used


def filter_pool(pool):
    """过滤无效或已标记失效的作品。"""
    valid = []
    for p in pool:
        if p.get("broken"):
            continue
        img = p.get("img", "")
        if not img.startswith("https://"):
            continue
        valid.append(p)
    return valid


def _pick_from(pool_list, selected, used_ids, used_urls, count=1):
    """从列表中选取若干条，避免 ID 与 URL 重复。"""
    random.shuffle(pool_list)
    picked = 0
    for p in pool_list:
        if len(selected) >= DAILY_COUNT:
            break
        if p["id"] in used_ids or p["img"] in used_urls:
            continue
        selected.append(p)
        used_ids.add(p["id"])
        used_urls.add(p["img"])
        picked += 1
        if picked >= count:
            break


def _balanced_select(candidates, count):
    """风格与图床均衡抽样。"""
    selected = []
    used_ids = set()
    used_urls = set()

    by_cat = {}
    by_src = {}
    for p in candidates:
        by_cat.setdefault(p["category"], []).append(p)
        by_src.setdefault(p.get("source", "unknown"), []).append(p)

    cat_keys = list(by_cat.keys())
    random.shuffle(cat_keys)
    min_categories = min(5, len(cat_keys))
    for cat in cat_keys[:min_categories]:
        _pick_from(by_cat[cat], selected, used_ids, used_urls, 1)

    src_keys = sorted(by_src.keys(), key=lambda s: -len(by_src[s]))
    random.shuffle(src_keys)
    min_sources = min(4, len(src_keys))
    for src in src_keys:
        if len({p.get("source") for p in selected}) >= min_sources:
            break
        if any(p.get("source") == src for p in selected):
            continue
        _pick_from(by_src[src], selected, used_ids, used_urls, 1)

    remaining = [p for p in candidates if p["id"] not in used_ids and p["img"] not in used_urls]
    _pick_from(remaining, selected, used_ids, used_urls, count - len(selected))

    return selected[:count]


def select_photos(bank, history):
    """从作品库中选取 20 幅：冷却优先、风格均衡、图床均衡、URL 去重。"""
    pool = filter_pool(bank["pool"])
    if len(pool) < DAILY_COUNT:
        raise RuntimeError(f"作品库有效条目不足 {DAILY_COUNT} 幅")

    candidates = None
    for cooldown in (REPEAT_COOLDOWN_DAYS, 14, 0):
        used_ids = get_recently_used_ids(history, days=cooldown) if cooldown > 0 else set()
        fresh = [p for p in pool if p["id"] not in used_ids]
        if len(fresh) >= DAILY_COUNT:
            candidates = fresh
            break

    if candidates is None:
        candidates = pool

    selected = _balanced_select(candidates, DAILY_COUNT)
    if len(selected) < DAILY_COUNT:
        fallback = [p for p in pool if p["id"] not in {x["id"] for x in selected}]
        extra = _balanced_select(fallback, DAILY_COUNT - len(selected))
        seen = {p["id"] for p in selected}
        for p in extra:
            if p["id"] not in seen:
                selected.append(p)
                seen.add(p["id"])

    return selected[:DAILY_COUNT]


def compute_stats(selected):
    """计算统计信息。"""
    photographers = set(p["photographer"] for p in selected)
    categories = set(p["category"] for p in selected)
    return {
        "photo_count": len(selected),
        "photographer_count": len(photographers),
        "category_count": len(categories),
    }


def format_date_cn(iso_date):
    """将 YYYY-MM-DD 格式化为中文日期。"""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return dt.strftime("%Y年%m月%d日 ") + weekdays[dt.weekday()]


def adapt_html_for_archive(html):
    """调整归档页中的资源与导航路径（archive/ 子目录）。"""
    html = html.replace('href="style.css"', 'href="../style.css"')
    html = html.replace('href="archive/"', 'href="index.html"')
    return html


def extract_photos_from_html(html):
    """从 HTML 中提取 photos 数组。"""
    import re

    match = re.search(r"(?:var|const) photos = (\[[\s\S]*?\]);", html)
    if not match:
        return None
    raw = match.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        titles = re.findall(r'title: "((?:\\.|[^"\\])*)"', html)
        if not titles:
            return None
        bank = load_json(BANK_PATH)
        pool_by_title = {p["title"]: p for p in bank["pool"]}
        return [pool_by_title[t] for t in titles if t in pool_by_title]


def render_index_html(selected, stats, date_cn=None):
    """使用模板渲染首页 HTML 字符串。"""
    template = load_template(TEMPLATE_PATH)
    if date_cn is None:
        date_cn = datetime.now().strftime("%Y年%m月%d日 %A")
        weekdays = {
            "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
            "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日",
        }
        for en, cn in weekdays.items():
            date_cn = date_cn.replace(en, cn)

    html = template.replace("{{PHOTOS_JSON}}", json.dumps(selected, ensure_ascii=False))
    html = html.replace("{{DATE}}", date_cn)
    html = html.replace("{{PHOTO_COUNT}}", str(stats["photo_count"]))
    html = html.replace("{{PHOTOGRAPHER_COUNT}}", str(stats["photographer_count"]))
    html = html.replace("{{CATEGORY_COUNT}}", str(stats["category_count"]))
    return html


def repair_archive_html(path):
    """修复已有归档页的 CSS 路径、固定日期与导航链接。"""
    import re

    date_str = os.path.basename(path).replace(".html", "")
    if not re.match(r"\d{4}-\d{2}-\d{2}$", date_str):
        return

    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    photos = extract_photos_from_html(html)
    is_legacy = (
        "now.getFullYear()" in html
        or re.search(r"const photos\s*=\s*\[\s*\{", html)
        or "const categories" in html
    )

    if photos and is_legacy:
        stats = compute_stats(photos)
        html = adapt_html_for_archive(render_index_html(photos, stats, format_date_cn(date_str)))
    else:
        html = adapt_html_for_archive(html)
        date_cn = format_date_cn(date_str)
        html = re.sub(
            r'<div class="date"[^>]*>.*?</div>',
            f'<div class="date">{date_cn}</div>',
            html,
            count=1,
        )
        html = html.replace("now.getFullYear()", "new Date().getFullYear()")
        if "archive-link" not in html:
            html = html.replace(
                '<div class="filter-bar container" id="filterBar"></div>',
                '<div class="filter-bar container" id="filterBar"></div>\n\n'
                '<div class="archive-link container">\n'
                '  <a href="index.html">浏览往期推荐</a>\n'
                "</div>",
            )

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def archive_current_index():
    """将当前的 docs/index.html 归档到 archive/ 目录。"""
    if os.path.exists(INDEX_PATH):
        today = datetime.now().strftime("%Y-%m-%d")
        archive_path = os.path.join(ARCHIVE_DIR, f"{today}.html")
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            content = adapt_html_for_archive(f.read())
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  归档: {archive_path}")


def generate_archive_index():
    """生成 archive/index.html 浏览页面。"""
    archive_files = sorted(
        [f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".html") and f != "index.html"],
        reverse=True,
    )
    items = ""
    for fname in archive_files:
        date_str = fname.replace(".html", "")
        items += f'      <li><a href="{fname}">{date_str}</a><span class="archive-date">{date_str}</span></li>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>往期推荐 | 每日摄影推荐</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<header class="container">
  <div class="date">ARCHIVE</div>
  <h1>往期推荐</h1>
  <p class="subtitle">浏览所有历史摄影推荐</p>
</header>
<div class="archive-list">
  <h2>推荐历史</h2>
  <ul>
{items}  </ul>
</div>
<footer>
  <p>每日摄影推荐 &copy; {datetime.now().year} · <a href="../" style="color:var(--accent);text-decoration:none;">返回首页</a></p>
</footer>
</body>
</html>"""

    archive_index_path = os.path.join(ARCHIVE_DIR, "index.html")
    with open(archive_index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  归档索引: {archive_index_path} ({len(archive_files)} 期)")


def generate_index_html(selected, stats):
    """使用模板生成 docs/index.html。"""
    html = render_index_html(selected, stats)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  生成主页: {INDEX_PATH}")


def update_history(history, selected):
    """将今日推荐写入历史记录。"""
    today = datetime.now().strftime("%Y-%m-%d")
    history.append({"date": today, "photos": selected})
    save_json(HISTORY_PATH, history)
    print(f"  更新历史: {HISTORY_PATH}")


def main():
    print("每日摄影推荐生成器")
    print("=" * 40)

    # 加载数据
    bank = load_json(BANK_PATH)
    history = load_or_rebuild_history()
    print(f"  作品库: {len(bank['pool'])} 幅 | 历史记录: {len(history)} 期")

    # 选作品
    selected = select_photos(bank, history)
    print(f"  选中: {len(selected)} 幅")

    # 统计
    stats = compute_stats(selected)
    print(f"  统计: {stats['photographer_count']} 位摄影师 | {stats['category_count']} 种风格")

    # 归档旧首页
    archive_current_index()

    # 生成新首页
    generate_index_html(selected, stats)

    # 更新归档索引
    generate_archive_index()

    # 修复所有归档页路径（兼容历史遗留文件）
    if os.path.isdir(ARCHIVE_DIR):
        for fname in os.listdir(ARCHIVE_DIR):
            if fname.endswith(".html") and fname != "index.html":
                repair_archive_html(os.path.join(ARCHIVE_DIR, fname))

    # 更新历史
    update_history(history, selected)

    print("=" * 40)
    print("生成完成")


if __name__ == "__main__":
    main()
