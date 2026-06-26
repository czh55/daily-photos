#!/usr/bin/env python3
"""每日摄影作品网络抓取器

从 Openverse（CC 授权图库）按风格分类抓取摄影作品，
合并到 bank.json，并通过 URL / source_id 永久去重。
"""

import html
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
BANK_PATH = os.path.join(DATA_DIR, "bank.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")

USER_AGENT = "DailyPhotosBot/1.0 (+https://github.com/czh55/daily-photos)"
DAILY_COUNT = 20
PHOTOS_PER_CATEGORY = 3
REQUEST_DELAY = 0.4

# 标题关键词过滤（排除教程/非摄影作品）
TITLE_BLOCKLIST = re.compile(
    r"photoshop|tutorial|how to|stock photo|mockup|template|logo|icon|clipart|"
    r"vector|illustration|screenshot|banner|advertisement",
    re.I,
)

# 风格分类与搜索词（Openverse 英文检索）
CATEGORIES = [
    {"category": "风景", "queries": ["landscape photography mountains", "seascape sunset photography"]},
    {"category": "街拍", "queries": ["street photography urban", "street photography candid city"]},
    {"category": "肖像", "queries": ["portrait photography", "environmental portrait photography"]},
    {"category": "纪实", "queries": ["documentary photography", "photojournalism reportage"]},
    {"category": "建筑", "queries": ["architecture photography", "modern architecture photography"]},
    {"category": "自然", "queries": ["nature photography wildlife", "forest nature photography"]},
    {"category": "光影", "queries": ["golden hour photography", "light and shadow photography"]},
    {"category": "黑白", "queries": ["black and white photography", "monochrome photography"]},
]

# 按类别生成中文描述模板
DESC_TEMPLATES = {
    "风景": [
        "远景与近景层次分明，{creator}以开阔构图呈现自然空间的纵深。{light}，画面传递出宁静而壮美的情感。",
        "地平线切割画面，{creator}在{title}中捕捉了天地之间的平衡。光影在大面积色块间流转，营造沉思氛围。",
    ],
    "街拍": [
        "{creator}在都市日常中按下快门，偶然与必然在此交汇。高对比的光影强化了街头的戏剧张力，记录真实生活的瞬间。",
        "动态构图与{light}交织，{creator}的{title}展现了城市脉搏中的人文温度与孤独感。",
    ],
    "肖像": [
        "人物与背景的关系被精心控制，{creator}通过{light}塑造面部立体感。眼神与姿态传递出内省而真实的情感。",
        "{creator}以简洁构图聚焦人物神态，柔和或锐利的光影勾勒出性格与故事。",
    ],
    "纪实": [
        "客观而克制的视角，{creator}记录时代切片。现场光线未经修饰却充满力量，情感在细节中自然流露。",
        "真实场景中的决定性瞬间，{creator}以{title}呈现社会与人文的深层关联。",
    ],
    "建筑": [
        "几何线条与空间节奏构成画面骨架，{creator}以{light}强调结构的秩序美。冷静构图中蕴含对都市文明的凝视。",
        "垂直与水平元素相互呼应，{creator}在{title}里探索建筑形式与光影的对话。",
    ],
    "自然": [
        "自然元素的质感被细腻呈现，{creator}以{light}唤醒生命的原始力量。构图留白让观者沉浸于荒野的静谧。",
        "{creator}捕捉生态瞬间，色彩与纹理在{title}中形成和谐而野性的视觉诗。",
    ],
    "光影": [
        "光线成为画面主角，{creator}以{light}雕刻形体与氛围。高反差或柔光过渡传递出时间流逝的诗意。",
        "明暗交界塑造空间深度，{creator}在{title}中展现对自然光与人工光的精准驾驭。",
    ],
    "黑白": [
        "剥离色彩后，构图与质感成为核心，{creator}以灰阶层次呈现永恒的经典美学。情感在明暗对比中更加纯粹。",
        "{creator}的黑白影像强调线条与纹理，{light}在单色世界中构建戏剧性与沉思感。",
    ],
}

LIGHT_PHRASES = [
    "侧光勾勒出细腻轮廓",
    "柔和漫射光营造静谧氛围",
    "逆光形成剪影与光晕",
    "黄金时刻的暖调光线",
    "高反差硬光强化视觉冲击",
    "窗口自然光赋予画面层次",
]


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def strip_html(text):
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", html.unescape(str(text)))
    return re.sub(r"\s+", " ", clean).strip()


def normalize_url(url):
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url.split("?")[0].strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".lower().rstrip("/")


def load_seen_keys(bank, history):
    """收集所有已使用过的图片 URL 与 source_id，用于永久去重。"""
    seen = set()
    for photo in bank.get("pool", []):
        seen.add(normalize_url(photo.get("img", "")))
        if photo.get("source_id"):
            seen.add(f"source:{photo['source_id']}")
    for record in history:
        for photo in record.get("photos", []):
            seen.add(normalize_url(photo.get("img", "")))
            if photo.get("source_id"):
                seen.add(f"source:{photo['source_id']}")
    return seen


def api_request(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_openverse(query, page=1, page_size=20):
    params = urllib.parse.urlencode(
        {
            "q": query,
            "page": page,
            "page_size": page_size,
            "license_type": "commercial,modification",
        }
    )
    url = f"https://api.openverse.org/v1/images/?{params}"
    try:
        data = api_request(url)
        return data.get("results", [])
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"    Openverse 请求失败 ({query} p{page}): {exc}")
        return []


def fetch_wikimedia(query, limit=10):
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|user|extmetadata",
            "iiurlwidth": 800,
        }
    )
    url = f"https://commons.wikimedia.org/w/api.php?{params}"
    try:
        data = api_request(url)
        pages = data.get("query", {}).get("pages", {})
        results = []
        for page in pages.values():
            info = page.get("imageinfo", [{}])[0]
            meta = info.get("extmetadata", {})
            img_url = info.get("thumburl") or info.get("url", "")
            if not img_url:
                continue
            title = strip_html(page.get("title", "").replace("File:", ""))
            creator = strip_html(
                meta.get("Artist", {}).get("value", "") or info.get("user", "")
            )
            desc = strip_html(meta.get("ImageDescription", {}).get("value", ""))
            results.append(
                {
                    "id": f"wiki-{page.get('pageid', title)}",
                    "title": title or "Wikimedia 摄影作品",
                    "url": img_url,
                    "creator": creator or "Wikimedia 贡献者",
                    "tags": [{"name": t} for t in re.findall(r"\w+", query)[:5]],
                    "description": desc,
                    "source": "wikimedia",
                }
            )
        return results
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"    Wikimedia 请求失败 ({query}): {exc}")
        return []


def validate_image_url(url):
    """验证图片 URL 可访问且为图片类型。"""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ctype = resp.headers.get("Content-Type", "")
            return ctype.startswith("image/")
    except urllib.error.HTTPError:
        pass
    except urllib.error.URLError:
        return False

    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ctype = resp.headers.get("Content-Type", "")
            return ctype.startswith("image/")
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def build_tags(category, item_tags):
    tags = [category]
    for tag in item_tags[:4]:
        name = tag.get("name") if isinstance(tag, dict) else str(tag)
        name = strip_html(name)
        if name and name not in tags and len(name) <= 20:
            tags.append(name)
    return tags[:5]


def build_description(title, creator, category, raw_desc=""):
    if raw_desc and len(raw_desc) > 30:
        base = raw_desc[:120]
        if len(raw_desc) > 120:
            base += "…"
        return base

    template = random.choice(DESC_TEMPLATES.get(category, DESC_TEMPLATES["风景"]))
    light = random.choice(LIGHT_PHRASES)
    return template.format(title=title, creator=creator, light=light)


def normalize_openverse_item(item, category):
    title = strip_html(item.get("title") or "Untitled")
    creator = strip_html(item.get("creator") or "未知摄影师")
    if not creator or creator.lower() in ("unknown", "null"):
        creator = "未知摄影师"

    tags = build_tags(category, item.get("tags", []))
    desc = build_description(title, creator, category)

    return {
        "title": title[:80],
        "photographer": creator[:60],
        "desc": desc,
        "tags": tags,
        "img": item["url"],
        "category": category,
        "source": "openverse",
        "source_id": str(item.get("id", "")),
        "license": item.get("license", ""),
        "fetched_at": datetime.now().strftime("%Y-%m-%d"),
    }


def normalize_wikimedia_item(item, category):
    title = item.get("title", "Wikimedia 摄影作品")[:80]
    creator = item.get("creator", "Wikimedia 贡献者")[:60]
    tags = build_tags(category, item.get("tags", []))
    desc = build_description(title, creator, category, item.get("description", ""))

    return {
        "title": title,
        "photographer": creator,
        "desc": desc,
        "tags": tags,
        "img": item["url"],
        "category": category,
        "source": "wikimedia",
        "source_id": str(item.get("id", "")),
        "license": "CC",
        "fetched_at": datetime.now().strftime("%Y-%m-%d"),
    }


def is_duplicate(item, seen):
    url_key = normalize_url(item.get("url", ""))
    source_key = f"source:{item.get('id', '')}"
    return url_key in seen or source_key in seen


def mark_seen(photo, seen):
    seen.add(normalize_url(photo["img"]))
    if photo.get("source_id"):
        seen.add(f"source:{photo['source_id']}")


def is_blocked_title(title):
    return bool(TITLE_BLOCKLIST.search(title or ""))


def pick_diverse_photos(all_fetched, count=DAILY_COUNT):
    """按风格轮询选取，确保多种类型均有机会入选。"""
    by_cat = {}
    for photo in all_fetched:
        by_cat.setdefault(photo["category"], []).append(photo)

    for photos in by_cat.values():
        random.shuffle(photos)

    selected = []
    categories = list(by_cat.keys())
    random.shuffle(categories)

    # 第一轮：每类至少 1 幅
    for cat in categories:
        if by_cat[cat]:
            selected.append(by_cat[cat].pop(0))

    # 第二轮：轮询补齐
    while len(selected) < count:
        added = False
        for cat in categories:
            if len(selected) >= count:
                break
            if by_cat[cat]:
                selected.append(by_cat[cat].pop(0))
                added = True
        if not added:
            break

    return selected[:count]


def try_add_photo(raw_item, category, seen, fetched, normalizer):
    title = strip_html(raw_item.get("title") or "")
    if is_blocked_title(title):
        return False

    if is_duplicate(raw_item, seen):
        return False

    photo = normalizer(raw_item, category)
    if not validate_image_url(photo["img"]):
        return False

    fetched.append(photo)
    mark_seen(photo, seen)
    return True


def fetch_for_category(category, queries, seen, target_count):
    fetched = []
    for query in queries:
        cat_count = sum(1 for p in fetched if p["category"] == category)
        if cat_count >= target_count:
            break

        for page in range(1, 4):
            cat_count = sum(1 for p in fetched if p["category"] == category)
            if cat_count >= target_count:
                break

            results = fetch_openverse(query, page=page, page_size=20)
            random.shuffle(results)
            for item in results:
                if try_add_photo(item, category, seen, fetched, normalize_openverse_item):
                    cat_count += 1
                    if cat_count >= target_count:
                        break
            time.sleep(REQUEST_DELAY)

    # Wikimedia 补充
    if sum(1 for p in fetched if p["category"] == category) < target_count:
        wiki_query = f"{category} photography"
        if category == "风景":
            wiki_query = "featured landscape photographs"
        results = fetch_wikimedia(wiki_query, limit=15)
        random.shuffle(results)
        for item in results:
            if sum(1 for p in fetched if p["category"] == category) >= target_count:
                break
            try_add_photo(item, category, seen, fetched, normalize_wikimedia_item)
        time.sleep(REQUEST_DELAY)

    return fetched


def fetch_daily_photos(bank=None, history=None):
    """抓取今日 20 幅不重复摄影作品，返回 PhotoEntry 列表（含 id）。"""
    bank = bank or load_json(BANK_PATH, {"pool": []})
    history = history or load_json(HISTORY_PATH, [])
    seen = load_seen_keys(bank, history)

    next_id = max((p["id"] for p in bank.get("pool", [])), default=0) + 1
    all_fetched = []

    print("  开始网络抓取...")
    print(f"  已排除 {len(seen)} 个历史 URL/source_id")

    for cat_config in CATEGORIES:
        category = cat_config["category"]
        batch = fetch_for_category(
            category, cat_config["queries"], seen, PHOTOS_PER_CATEGORY
        )
        all_fetched.extend(batch)
        count = sum(1 for p in batch if p["category"] == category)
        print(f"    {category}: 抓取 {count} 幅")

    # 不足 20 幅时扩大检索
    if len(all_fetched) < DAILY_COUNT:
        print(f"  数量不足 ({len(all_fetched)}/{DAILY_COUNT})，扩大检索范围...")
        extra_queries = [
            "fine art photography",
            "travel photography",
            "film photography",
            "minimalist photography",
            "aerial photography",
        ]
        for query in extra_queries:
            if len(all_fetched) >= DAILY_COUNT:
                break
            category = random.choice([c["category"] for c in CATEGORIES])
            for page in range(1, 3):
                if len(all_fetched) >= DAILY_COUNT:
                    break
                results = fetch_openverse(query, page=page, page_size=20)
                random.shuffle(results)
                for item in results:
                    if len(all_fetched) >= DAILY_COUNT:
                        break
                    try_add_photo(item, category, seen, all_fetched, normalize_openverse_item)
                time.sleep(REQUEST_DELAY)

    if len(all_fetched) < DAILY_COUNT:
        raise RuntimeError(
            f"网络抓取仅获得 {len(all_fetched)} 幅，不足 {DAILY_COUNT} 幅。"
            "请检查网络连接或稍后重试。"
        )

    selected = pick_diverse_photos(all_fetched, DAILY_COUNT)
    for photo in selected:
        photo["id"] = next_id
        next_id += 1

    # 合并到 bank.json
    bank.setdefault("pool", []).extend(selected)
    save_json(BANK_PATH, bank)

    categories = set(p["category"] for p in selected)
    photographers = set(p["photographer"] for p in selected)
    print(f"  抓取完成: {len(selected)} 幅 | {len(photographers)} 位摄影师 | {len(categories)} 种风格")

    return selected


def main():
    print("每日摄影作品网络抓取器")
    print("=" * 40)
    photos = fetch_daily_photos()
    for i, p in enumerate(photos, 1):
        print(f"  {i:2d}. [{p['category']}] {p['title'][:40]} — {p['photographer'][:30]}")
    print("=" * 40)
    print("抓取完成")


if __name__ == "__main__":
    main()
