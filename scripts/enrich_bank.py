#!/usr/bin/env python3
"""从多图床拉取摄影作品元数据，增量合并到 bank.json。

只存储 HTTPS 外链 URL，不下载任何图片文件。
"""

import argparse
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
BANK_PATH = os.path.join(PROJECT_DIR, "data", "bank.json")

MIN_WIDTH = 800
MIN_POOL_SIZE = 120
PER_SOURCE_PER_CATEGORY = 3
REQUEST_DELAY = 0.6
USER_AGENT = "daily-photos-enrich/1.0 (https://github.com/czh55/daily-photos)"

ALLOWED_DOMAIN_SUFFIXES = (
    "images.unsplash.com",
    "upload.wikimedia.org",
    "images.pexels.com",
    "cdn.pixabay.com",
    "images-assets.nasa.gov",
    "images.metmuseum.org",
    "live.staticflickr.com",
    "static.flickr.com",
    "images.rawpixel.com",
)

CATEGORY_KEYWORDS = {
    "风景": ["landscape photography", "mountain vista"],
    "自然": ["wildlife nature", "forest light"],
    "建筑": ["architecture urban", "building geometry"],
    "街拍": ["street photography", "city candid"],
    "肖像": ["portrait photography", "human face"],
    "纪实": ["documentary photography", "social life"],
    "光影": ["light and shadow photography", "golden hour"],
    "黑白": ["black and white photography", "monochrome"],
}

SOURCE_LABELS = {
    "openverse": "Openverse",
    "wikimedia": "Wikimedia",
    "nasa": "NASA",
    "met": "Met Museum",
    "unsplash": "Unsplash",
    "pexels": "Pexels",
    "pixabay": "Pixabay",
    "flickr": "Flickr",
    "rawpixel": "Rawpixel",
}

PROVIDER_AS_SOURCE = {"flickr", "wikimedia", "rawpixel", "stocksnap", "iha"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def api_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_allowed_url(url):
    if not url or not url.startswith("https://"):
        return False
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAIN_SUFFIXES)


def build_desc(title, photographer, category, tags=None):
    tags = tags or []
    tag_hint = tags[0] if tags else category
    return (
        f"构图上，{title}以{tag_hint}元素形成清晰视觉焦点；"
        f"光影层次丰富，明暗对比赋予画面深度与空间感；"
        f"情感表达上，{photographer}的镜头传递出对{category}题材的独到观察与共鸣。"
    )


def normalize_entry(entry, category):
    img = entry.get("img", "")
    if not is_allowed_url(img):
        return None
    title = (entry.get("title") or "Untitled").strip()
    if len(title) > 80:
        title = title[:77] + "..."
    photographer = (entry.get("photographer") or "未知摄影师").strip()
    tags = entry.get("tags") or [category]
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t) for t in tags[:5]]
    if category not in tags:
        tags.insert(0, category)

    return {
        "title": title,
        "photographer": photographer,
        "desc": entry.get("desc") or build_desc(title, photographer, category, tags),
        "tags": tags,
        "img": img,
        "category": category,
        "source": entry["source"],
        "source_url": entry.get("source_url", ""),
    }


class SourceAdapter(ABC):
    name = "base"

    @abstractmethod
    def fetch(self, category, keyword, limit):
        pass


class OpenverseAdapter(SourceAdapter):
    name = "openverse"

    def __init__(self, source_filter=None, label=None):
        self.source_filter = source_filter
        if label:
            self.name = label

    def fetch(self, category, keyword, limit):
        query = {"q": keyword, "license": "cc0,by,by-sa", "page_size": min(limit * 3, 20)}
        if self.source_filter:
            query["source"] = self.source_filter
        params = urllib.parse.urlencode(query)
        url = f"https://api.openverse.org/v1/images/?{params}"
        data = api_get(url)
        results = []
        for item in data.get("results", []):
            img = item.get("url") or ""
            if not is_allowed_url(img):
                continue
            w = item.get("width") or 0
            if w and w < MIN_WIDTH:
                continue
            title = item.get("title") or keyword
            photographer = item.get("creator") or "Openverse 摄影师"
            tag_names = [t.get("name", "") for t in (item.get("tags") or []) if t.get("name")][:4]
            provider = (item.get("provider") or item.get("source") or "openverse").lower()
            if self.source_filter:
                source = self.source_filter
            elif provider in PROVIDER_AS_SOURCE:
                source = provider
            elif "staticflickr.com" in img or "flickr.com" in img:
                source = "flickr"
            else:
                source = "openverse"
            if provider and provider not in tag_names:
                tag_names.append(provider)
            results.append({
                "title": title,
                "photographer": photographer,
                "img": img,
                "source": source,
                "source_url": item.get("foreign_landing_url") or "",
                "tags": tag_names or [category],
            })
            if len(results) >= limit:
                break
        return results


class WikimediaAdapter(SourceAdapter):
    name = "wikimedia"

    def fetch(self, category, keyword, limit):
        params = urllib.parse.urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {keyword}",
            "gsrnamespace": "6",
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": "960",
            "format": "json",
        })
        url = f"https://commons.wikimedia.org/w/api.php?{params}"
        data = api_get(url)
        pages = data.get("query", {}).get("pages", {})
        results = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            width = info.get("width") or 0
            if width and width < MIN_WIDTH:
                continue
            img = info.get("thumburl") or info.get("url") or ""
            if not is_allowed_url(img):
                continue
            title = (page.get("title") or "").replace("File:", "")
            meta = info.get("extmetadata") or {}
            artist = meta.get("Artist", {}).get("value", "")
            artist = re.sub(r"<[^>]+>", "", artist).strip() or "Wikimedia 摄影师"
            file_name = page.get("title", "").replace(" ", "_")
            results.append({
                "title": title[:80] if title else keyword,
                "photographer": artist[:60],
                "img": img,
                "source": self.name,
                "source_url": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(file_name)}",
                "tags": [category, "wikimedia"],
            })
            if len(results) >= limit:
                break
        return results


class NasaAdapter(SourceAdapter):
    name = "nasa"

    def fetch(self, category, keyword, limit):
        params = urllib.parse.urlencode({
            "q": keyword,
            "media_type": "image",
            "page_size": min(limit * 4, 30),
        })
        url = f"https://images-api.nasa.gov/search?{params}"
        data = api_get(url)
        results = []
        for item in data.get("collection", {}).get("items", []):
            if item.get("data", [{}])[0].get("media_type") != "image":
                continue
            title = item.get("data", [{}])[0].get("title", keyword)
            photographer = "NASA"
            best_link = None
            best_width = 0
            for link in item.get("links", []):
                if link.get("render") != "image":
                    continue
                w = link.get("width") or 0
                href = link.get("href", "")
                if w >= MIN_WIDTH and w > best_width and is_allowed_url(href):
                    best_link = href
                    best_width = w
            if not best_link:
                continue
            nasa_id = item.get("data", [{}])[0].get("nasa_id", "")
            results.append({
                "title": title,
                "photographer": photographer,
                "img": best_link,
                "source": self.name,
                "source_url": f"https://images.nasa.gov/details-{nasa_id}" if nasa_id else "",
                "tags": [category, "nasa", "space"],
            })
            if len(results) >= limit:
                break
        return results


class MetAdapter(SourceAdapter):
    name = "met"

    PHOTO_DEPARTMENTS = {"19", "21", "36", "37"}

    def fetch(self, category, keyword, limit):
        params = urllib.parse.urlencode({
            "q": keyword,
            "hasImages": "true",
        })
        url = f"https://collectionapi.metmuseum.org/public/collection/v1/search?{params}"
        data = api_get(url)
        object_ids = data.get("objectIDs") or []
        if not object_ids:
            return []
        random.shuffle(object_ids)
        results = []
        for oid in object_ids[: limit * 5]:
            try:
                obj = api_get(
                    f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}"
                )
            except urllib.error.HTTPError:
                continue
            img = obj.get("primaryImage") or ""
            if not is_allowed_url(img):
                continue
            dept = str(obj.get("departmentId") or "")
            if dept and dept not in self.PHOTO_DEPARTMENTS and len(results) > 0:
                continue
            title = obj.get("title") or keyword
            photographer = obj.get("artistDisplayName") or "Met Museum"
            results.append({
                "title": title,
                "photographer": photographer,
                "img": img,
                "source": self.name,
                "source_url": obj.get("objectURL") or "",
                "tags": [category, "met", "art"],
            })
            if len(results) >= limit:
                break
            time.sleep(0.2)
        return results


class PexelsAdapter(SourceAdapter):
    name = "pexels"

    def __init__(self, api_key):
        self.api_key = api_key

    def fetch(self, category, keyword, limit):
        if not self.api_key:
            return []
        params = urllib.parse.urlencode({"query": keyword, "per_page": min(limit * 2, 15)})
        url = f"https://api.pexels.com/v1/search?{params}"
        data = api_get(url, headers={"Authorization": self.api_key})
        results = []
        for photo in data.get("photos", []):
            img = photo.get("src", {}).get("large") or photo.get("src", {}).get("original") or ""
            if not is_allowed_url(img):
                continue
            results.append({
                "title": photo.get("alt") or keyword,
                "photographer": photo.get("photographer") or "Pexels",
                "img": img,
                "source": self.name,
                "source_url": photo.get("url") or "",
                "tags": [category, "pexels"],
            })
            if len(results) >= limit:
                break
        return results


class PixabayAdapter(SourceAdapter):
    name = "pixabay"

    def __init__(self, api_key):
        self.api_key = api_key

    def fetch(self, category, keyword, limit):
        if not self.api_key:
            return []
        params = urllib.parse.urlencode({
            "key": self.api_key,
            "q": keyword,
            "image_type": "photo",
            "per_page": min(limit * 2, 20),
            "safesearch": "true",
        })
        url = f"https://pixabay.com/api/?{params}"
        data = api_get(url)
        results = []
        for hit in data.get("hits", []):
            img = hit.get("largeImageURL") or hit.get("webformatURL") or ""
            if not is_allowed_url(img):
                continue
            if hit.get("imageWidth", MIN_WIDTH) < MIN_WIDTH:
                continue
            results.append({
                "title": hit.get("tags", keyword).split(",")[0].strip() or keyword,
                "photographer": hit.get("user") or "Pixabay",
                "img": img,
                "source": self.name,
                "source_url": hit.get("page") or "",
                "tags": [t.strip() for t in (hit.get("tags") or category).split(",")[:4]],
            })
            if len(results) >= limit:
                break
        return results


class FlickrAdapter(SourceAdapter):
    name = "flickr"

    def __init__(self, api_key):
        self.api_key = api_key

    def fetch(self, category, keyword, limit):
        if not self.api_key:
            return []
        params = urllib.parse.urlencode({
            "method": "flickr.photos.search",
            "api_key": self.api_key,
            "text": keyword,
            "license": "4,5,6,7,8,9,10",
            "content_type": "1",
            "media": "photos",
            "extras": "url_l,owner_name,tags",
            "per_page": min(limit * 2, 20),
            "format": "json",
            "nojsoncallback": "1",
        })
        url = f"https://www.flickr.com/services/rest/?{params}"
        data = api_get(url)
        results = []
        for photo in data.get("photos", {}).get("photo", []):
            img = photo.get("url_l") or ""
            if not is_allowed_url(img):
                continue
            tags = (photo.get("tags") or category).split(",")[:4]
            results.append({
                "title": photo.get("title") or keyword,
                "photographer": photo.get("ownername") or "Flickr",
                "img": img,
                "source": self.name,
                "source_url": f"https://www.flickr.com/photos/{photo.get('owner')}/{photo.get('id')}",
                "tags": tags,
            })
            if len(results) >= limit:
                break
        return results


def get_adapters():
    adapters = [
        OpenverseAdapter(),
        OpenverseAdapter(source_filter="rawpixel", label="rawpixel"),
        WikimediaAdapter(),
        NasaAdapter(),
        MetAdapter(),
    ]
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
    flickr_key = os.environ.get("FLICKR_API_KEY", "")
    if pexels_key:
        adapters.append(PexelsAdapter(pexels_key))
    if pixabay_key:
        adapters.append(PixabayAdapter(pixabay_key))
    if flickr_key:
        adapters.append(FlickrAdapter(flickr_key))
    return adapters


def tag_existing_unsplash(pool):
    for photo in pool:
        img = photo.get("img", "")
        if "staticflickr.com" in img or "flickr.com" in img:
            photo["source"] = "flickr"
        elif photo.get("source") == "openverse":
            provider = photo.get("source")
            if "rawpixel" in " ".join(photo.get("tags", [])).lower():
                photo["source"] = "rawpixel"
        elif "source" not in photo:
            photo["source"] = "unsplash"
        if img.startswith("https://images.unsplash.com"):
            photo["source"] = "unsplash"


def merge_entries(pool, new_entries, existing_urls, category):
    next_id = max((p["id"] for p in pool), default=0) + 1
    added = 0
    for raw in new_entries:
        img = raw.get("img", "")
        if img in existing_urls:
            continue
        normalized = normalize_entry(raw, category)
        if not normalized:
            continue
        normalized["id"] = next_id
        pool.append(normalized)
        existing_urls.add(img)
        next_id += 1
        added += 1
    return added


def enrich_pool(pool, adapters, per_source_limit, bootstrap=False):
    existing_urls = {p["img"] for p in pool}
    total_added = 0

    for category, keywords in CATEGORY_KEYWORDS.items():
        keyword = random.choice(keywords)
        for adapter in adapters:
            try:
                print(f"  [{adapter.name}] {category} ← {keyword}")
                fetched = adapter.fetch(category, keyword, per_source_limit)
                added = merge_entries(pool, fetched, existing_urls, category)
                total_added += added
                print(f"    +{added} 条")
            except Exception as exc:
                print(f"    跳过 ({exc})")
            time.sleep(REQUEST_DELAY)

    return total_added


def main():
    parser = argparse.ArgumentParser(description="从多图床增量扩充 bank.json")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="批量拉取，直到库达到目标规模",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=PER_SOURCE_PER_CATEGORY,
        help="每个源每个类别最多拉取条数",
    )
    args = parser.parse_args()

    print("作品库扩充器（多图床外链）")
    print("=" * 40)

    bank = load_json(BANK_PATH)
    pool = bank.setdefault("pool", [])
    tag_existing_unsplash(pool)

    adapters = get_adapters()
    print(f"  当前: {len(pool)} 条 | 适配器: {[a.name for a in adapters]}")

    if args.bootstrap or len(pool) < MIN_POOL_SIZE:
        rounds = 0
        while len(pool) < MIN_POOL_SIZE and rounds < 6:
            rounds += 1
            print(f"  --- 第 {rounds} 轮扩充 (目标 {MIN_POOL_SIZE}) ---")
            added = enrich_pool(pool, adapters, args.limit, bootstrap=True)
            print(f"  本轮 +{added}，合计 {len(pool)} 条")
            if added == 0:
                break
    else:
        added = enrich_pool(pool, adapters, args.limit, bootstrap=False)
        print(f"  增量 +{added}，合计 {len(pool)} 条")

    sources = {}
    for p in pool:
        sources[p.get("source", "unknown")] = sources.get(p.get("source", "unknown"), 0) + 1
    print(f"  图床分布: {sources}")

    save_json(BANK_PATH, bank)
    print("=" * 40)
    print("扩充完成")


if __name__ == "__main__":
    main()
