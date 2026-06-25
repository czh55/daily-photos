#!/usr/bin/env python3
"""每日摄影推荐生成器

从 bank.json 选取 20 幅作品，生成 docs/index.html，
归档旧版到 docs/archive/，更新 data/history.json 避免重复推荐。
"""

import json
import os
import random
import shutil
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


def select_photos(bank, history):
    """从作品库中选取 20 幅，优先未推荐过的作品。"""
    pool = bank["pool"]
    used_ids = get_recently_used_ids(history)

    # 分为可用和已用过
    available = [p for p in pool if p["id"] not in used_ids]
    if len(available) < DAILY_COUNT:
        fallback = [p for p in pool if p["id"] in used_ids]
        available += fallback

    if len(available) < DAILY_COUNT:
        raise RuntimeError(f"作品库总量不足 {DAILY_COUNT} 幅")

    selected = random.sample(available, DAILY_COUNT)
    return selected


def compute_stats(selected):
    """计算统计信息。"""
    photographers = set(p["photographer"] for p in selected)
    categories = set(p["category"] for p in selected)
    return {
        "photo_count": len(selected),
        "photographer_count": len(photographers),
        "category_count": len(categories),
    }


def archive_current_index():
    """将当前的 docs/index.html 归档到 archive/ 目录。"""
    if os.path.exists(INDEX_PATH):
        today = datetime.now().strftime("%Y-%m-%d")
        archive_path = os.path.join(ARCHIVE_DIR, f"{today}.html")
        shutil.copy2(INDEX_PATH, archive_path)
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
    template = load_template(TEMPLATE_PATH)
    photos_json = json.dumps(selected, ensure_ascii=False)
    today_cn = datetime.now().strftime("%Y年%m月%d日 %A")
    weekdays = {"Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
                "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日"}
    for en, cn in weekdays.items():
        today_cn = today_cn.replace(en, cn)

    html = template.replace("{{PHOTOS_JSON}}", photos_json)
    html = html.replace("{{DATE}}", today_cn)
    html = html.replace("{{PHOTO_COUNT}}", str(stats["photo_count"]))
    html = html.replace("{{PHOTOGRAPHER_COUNT}}", str(stats["photographer_count"]))
    html = html.replace("{{CATEGORY_COUNT}}", str(stats["category_count"]))

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
    history = load_json(HISTORY_PATH)
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

    # 更新历史
    update_history(history, selected)

    print("=" * 40)
    print("生成完成")


if __name__ == "__main__":
    main()
