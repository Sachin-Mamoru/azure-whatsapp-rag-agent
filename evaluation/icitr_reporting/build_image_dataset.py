"""
Build the image-report evaluation set from openly licensed Wikimedia Commons files.

  python evaluation/icitr_reporting/build_image_dataset.py [--refresh]

Writes image_data/manifest.jsonl (committed) and image_data/images/ (not
committed; re-created from the manifest URLs, verified by SHA-256).

Provenance rules:
- Images are real photographs from fixed Commons categories, licence-filtered
  to CC0 / public domain / CC BY / CC BY-SA. Title, page URL, author, licence
  and categories are recorded per image.
- Captions are CONSTRUCTED from fixed templates (EN/SI/TA) by the evaluation
  author; they are not real community messages and have not been reviewed by
  native speakers.
- `provisional_*` labels come from the Commons source category, not from
  human annotation of these images for this task.
- Degraded and re-encoded items are DERIVED (synthetic transformations of the
  real images) and are flagged as such.
"""
import argparse
import hashlib
import io
import json
import os
import random
import re
import sys
import time

import requests
from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "image_data")
IMAGES = os.path.join(DATA, "images")
MANIFEST = os.path.join(DATA, "manifest.jsonl")
CACHE = os.path.join(DATA, "commons_cache.json")
API = "https://commons.wikimedia.org/w/api.php"
UA = "ICITR-community-reporting-eval/1.0 (research use; contact sachinmamoru@gmail.com)"
SEED = 20261004

# (category, event_group, provisional_class, max_images). Categories are fixed
# before any model output is seen.
SOURCES = [
    ("2016 Sri Lankan floods", "LK-2016-floods", "flood", 20),
    ("2017 Sri Lanka floods", "LK-2017-floods", "flood", 20),
    ("Floods in Sri Lanka", "LK-floods-other", "flood", 15),
    ("2004 floods in Sri Lanka", "LK-2004-floods", "flood", 10),
    ("Cyclone Ditwah", "LK-2025-cyclone-ditwah", "flood", 15),
    ("2018 Kerala floods in Kochi", "IN-2018-kerala-floods", "flood", 8),
    ("2018 Kerala floods in Kottayam", "IN-2018-kerala-floods", "flood", 6),
    ("Flooded roads", "GEN-flooded-roads", "flood", 12),
    ("2014 Koslanda landslide", "LK-2014-koslanda-landslide", "landslide", 15),
    ("Landslides in Sri Lanka in 2014", "LK-2014-landslides", "landslide", 10),
    ("Landslides in Sri Lanka", "LK-landslides-other", "landslide", 10),
    ("Landslides in Kerala", "IN-kerala-landslides", "landslide", 12),
    ("Landslide damage", "GEN-landslide-damage", "landslide", 15),
    ("Active landslides", "GEN-active-landslides", "landslide", 10),
    ("Rockfalls in India", "IN-rockfalls", "landslide", 8),
    ("Mudslides", "GEN-mudslides", "landslide", 10),
    ("Roads in Sri Lanka", "LK-roads", "none", 16),
    ("Rivers of Sri Lanka", "LK-rivers", "none", 14),
    ("Tea plantations in Sri Lanka", "LK-tea", "none", 10),
    ("Paddy fields in Sri Lanka", "LK-paddy", "none", 10),
    ("Storm drains", "GEN-storm-drains", "none", 10),
]
LICENCE_OK = re.compile(r"^(cc0|public domain|pd|cc[ -]by(-sa)?[ -]\d)", re.I)
TITLE_EXCLUDE = re.compile(r"map|diagram|chart|logo|graph|plan|poster|icon|svg|stamp|newspaper", re.I)
PROVISIONAL_CATEGORY = {"flood": "localised_flooding", "landslide": "slope_instability", "none": "none"}

PLACES = [
    ("Ratnapura", "රත්නපුර", "இரத்தினபுரி"), ("Kandy", "මහනුවර", "கண்டி"),
    ("Kegalle", "කෑගල්ල", "கேகாலை"), ("Badulla", "බදුල්ල", "பதுளை"),
    ("Kalutara", "කළුතර", "களுத்துறை"), ("Colombo", "කොළඹ", "கொழும்பு"),
    ("Galle", "ගාල්ල", "காலி"), ("Matara", "මාතර", "மாத்தறை"),
    ("Gampaha", "ගම්පහ", "கம்பஹா"), ("Kelaniya", "කැලණිය", "களனி"),
]
TEMPLATES = {
    ("flood", "en"): ["Flood water is rising on the road near {p}, and it is reaching the houses.",
                      "Heavy rain has flooded the area near {p}; water is still spreading."],
    ("flood", "si"): ["{p} අසල පාරේ ගංවතුර ජලය ඉහළ යනවා, ගෙවල් ළඟටත් ජලය එනවා.",
                      "අධික වැස්ස නිසා {p} ප්‍රදේශය ජලයෙන් යට වෙලා, ජලය තවමත් පැතිරෙනවා."],
    ("flood", "ta"): ["{p} அருகே சாலையில் வெள்ள நீர் உயர்ந்து வீடுகளை நெருங்குகிறது.",
                      "கனமழையால் {p} பகுதி வெள்ளத்தில் மூழ்கியுள்ளது, நீர் இன்னும் பரவுகிறது."],
    ("landslide", "en"): ["Part of the hillside near {p} has slid down and soil is covering the road.",
                          "There is a landslide near {p}; rocks and mud are still coming down the slope."],
    ("landslide", "si"): ["{p} අසල කඳු බෑවුමේ කොටසක් නාය ගිහින් පාරට පස් වැටිලා.",
                          "{p} ළඟ නාය යෑමක් සිද්ධ වෙලා, බෑවුමෙන් තවමත් ගල් සහ මඩ පහළට එනවා."],
    ("landslide", "ta"): ["{p} அருகே மலைச்சரிவின் ஒரு பகுதி சரிந்து சாலையை மண் மூடியுள்ளது.",
                          "{p} அருகே நிலச்சரிவு ஏற்பட்டுள்ளது, சரிவிலிருந்து இன்னும் பாறைகளும் சேறும் விழுகின்றன."],
    ("sparse", "en"): ["Please look at this photo. {p}."],
    ("sparse", "si"): ["කරුණාකර මේ ඡායාරූපය බලන්න. {p}."],
    ("sparse", "ta"): ["தயவுசெய்து இந்தப் படத்தைப் பாருங்கள். {p}."],
}
LANG_INDEX = {"en": 0, "si": 1, "ta": 2}


def session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def api(s, **params):
    params.update(format="json", formatversion=2)
    for attempt in range(5):
        r = s.get(API, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Commons API rate-limited")


def category_files(s, category):
    titles, cont = [], {}
    while True:
        data = api(s, action="query", list="categorymembers", cmtitle=f"Category:{category}",
                   cmtype="file", cmlimit=500, **cont)
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        if "continue" not in data:
            return titles
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}


def file_info(s, titles):
    out = {}
    for i in range(0, len(titles), 50):
        data = api(s, action="query", prop="imageinfo|categories", titles="|".join(titles[i:i + 50]),
                   iiprop="url|size|mime|sha1|extmetadata|user", iiurlwidth=1024, cllimit=500)
        for page in data["query"]["pages"]:
            if page.get("imageinfo"):
                info = page["imageinfo"][0]
                meta = info.get("extmetadata", {})
                text = lambda k: re.sub(r"<[^>]+>", "", (meta.get(k) or {}).get("value", "")).strip()
                out[page["title"]] = {
                    "title": page["title"], "page_url": info.get("descriptionurl"),
                    "original_url": info.get("url"), "thumb_url": info.get("thumburl"),
                    "width": info.get("width"), "height": info.get("height"), "mime": info.get("mime"),
                    "commons_sha1": info.get("sha1"), "uploader": info.get("user"),
                    "licence": text("LicenseShortName"), "licence_url": text("LicenseUrl"),
                    "artist": text("Artist")[:200], "credit": text("Credit")[:200],
                    "date": text("DateTimeOriginal")[:40],
                    "categories": [c["title"].replace("Category:", "") for c in page.get("categories", [])],
                }
        time.sleep(0.5)
    return out


def collect(refresh):
    if os.path.exists(CACHE) and not refresh:
        return json.load(open(CACHE, encoding="utf-8"))
    s = session()
    pool = {}
    for category, group, cls, _ in SOURCES:
        titles = category_files(s, category)
        info = file_info(s, titles)
        pool[category] = list(info.values())
        print(f"{category}: {len(titles)} files listed, {len(info)} with info")
    json.dump(pool, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return pool


def eligible(f):
    return (f["mime"] == "image/jpeg" and (f["width"] or 0) >= 500 and f["thumb_url"]
            and LICENCE_OK.match(f["licence"] or "") and not TITLE_EXCLUDE.search(f["title"]))


def download(s, url):
    for attempt in range(5):
        r = s.get(url, timeout=60)
        if r.status_code in (429, 503):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.content
    raise RuntimeError(f"download failed: {url}")


def save(data):
    digest = hashlib.sha256(data).hexdigest()
    path = os.path.join(IMAGES, f"{digest[:16]}.jpg")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return digest, os.path.relpath(path, DATA)


def caption(cls, lang, variant, place):
    templates = TEMPLATES[(cls, lang)]
    return templates[variant % len(templates)].format(p=place[LANG_INDEX[lang]])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="re-query Commons instead of the cached listing")
    parser.add_argument("--verify", action="store_true",
                        help="re-create missing images from manifest.jsonl and check every SHA-256")
    args = parser.parse_args()
    if args.verify:
        return verify()
    os.makedirs(IMAGES, exist_ok=True)
    rng = random.Random(SEED)
    pool = collect(args.refresh)
    s = session()

    chosen, seen = [], set()
    for category, group, cls, cap in SOURCES:
        files = sorted((f for f in pool.get(category, []) if eligible(f) and f["commons_sha1"] not in seen),
                       key=lambda f: f["title"])
        rng.shuffle(files)
        for f in files[:cap]:
            seen.add(f["commons_sha1"])
            chosen.append((category, group, cls, f))

    items = []
    counters = {}
    for category, group, cls, f in chosen:
        data = download(s, f["thumb_url"])
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            print(f"skip unreadable {f['title']}")
            continue
        digest, rel = save(data)
        n = counters.setdefault(cls, 0)
        counters[cls] += 1
        lang = ["en", "si", "ta"][n % 3]
        place = PLACES[(n * 7) % len(PLACES)]
        if cls == "none":
            condition = ["hazard_claim", "sparse"][(n // 3) % 2]
            claim = ["flood", "landslide"][n % 2] if condition == "hazard_claim" else "none"
        else:
            condition = ["matching", "sparse", "contradiction"][(n // 3) % 3]
            other = "landslide" if cls == "flood" else "flood"
            claim = {"matching": cls, "sparse": "none", "contradiction": other}[condition]
        text = caption(claim if claim != "none" else "sparse", lang, n // 2, place)
        items.append({
            "item_id": f"IMG-{len(items) + 1:03d}", "source_kind": "real_commons",
            "image_file": rel, "image_sha256": digest, "image_bytes": len(data),
            "commons": {k: f[k] for k in ("title", "page_url", "original_url", "thumb_url", "width", "height",
                                          "commons_sha1", "uploader", "licence", "licence_url", "artist",
                                          "credit", "date", "categories")},
            "source_category": category, "event_group": group, "contributor_group": f["uploader"],
            "provisional_image_class": cls,
            "provisional_image_category": PROVISIONAL_CATEGORY[cls],
            "label_source": "Commons source category (provisional; not human-annotated for this task)",
            "caption_condition": condition, "caption_language": lang, "caption_text": text,
            "caption_source": "constructed template (not a real community message; SI/TA not native-speaker reviewed)",
            "text_claim_class": claim,
            "expected_image_supports_report": cls != "none" and condition in ("matching", "sparse"),
            "duplicate_of": None, "transformation": None,
        })
        time.sleep(0.2)

    assign_splits(items)
    add_derived(items, rng)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary(items)


def assign_splits(items):
    """Whole event groups go to dev until ~15% of real items; the rest is test."""
    groups = sorted({i["event_group"] for i in items},
                    key=lambda g: hashlib.sha256(f"{SEED}:{g}".encode()).hexdigest())
    target = 0.15 * len(items)
    dev, count = set(), 0
    for g in groups:
        size = sum(i["event_group"] == g for i in items)
        if count + size <= target + 3:
            dev.add(g)
            count += size
    for i in items:
        i["split"] = "dev" if i["event_group"] in dev else "test"


def add_derived(items, rng):
    """Degraded copies and duplicate controls, built from test-split hazard items
    whose caption matches the image, so each pair differs only in the image."""
    base = [i for i in items if i["split"] == "test" and i["caption_condition"] == "matching"]
    rng.shuffle(base)
    names = ["degraded:gaussian_blur_r12", "degraded:brightness_0.08", "degraded:downscale_40px_upscale"]
    derived = []
    for k, src in enumerate(base[:15]):
        name = names[k % len(names)]
        derived.append(_derive(src, name, TRANSFORMS[name], "derived_degraded_from_real", len(items) + len(derived)))
    for k, src in enumerate(base[15:27]):
        if k < 8:
            derived.append(_derive(src, "exact_copy", None, "duplicate_exact", len(items) + len(derived)))
        else:
            derived.append(_derive(src, "reencoded_jpeg_q25", None, "duplicate_reencoded", len(items) + len(derived)))
    items.extend(derived)


def _derive(src, transformation, fn, kind, index):
    path = os.path.join(DATA, src["image_file"])
    if kind == "duplicate_exact":
        data = open(path, "rb").read()
    else:
        im = Image.open(path).convert("RGB")
        if fn:
            im = fn(im)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=25 if kind == "duplicate_reencoded" else 85)
        data = buf.getvalue()
    digest, rel = save(data)
    item = json.loads(json.dumps(src))
    item.update(item_id=f"IMG-{index + 1:03d}", source_kind=kind, image_file=rel, image_sha256=digest,
                image_bytes=len(data), duplicate_of=src["item_id"], transformation=transformation,
                contributor_group=f"synthetic-copy-of:{src['contributor_group']}" if kind.startswith("duplicate")
                else src["contributor_group"])
    return item


TRANSFORMS = {
    "degraded:gaussian_blur_r12": lambda im: im.filter(ImageFilter.GaussianBlur(12)),
    "degraded:brightness_0.08": lambda im: ImageEnhance.Brightness(im).enhance(0.08),
    "degraded:downscale_40px_upscale": lambda im: im.resize((40, max(1, 40 * im.height // im.width))).resize(im.size),
}


def verify():
    """Re-fetch real images, re-derive derived ones, and compare hashes."""
    os.makedirs(IMAGES, exist_ok=True)
    items = [json.loads(l) for l in open(MANIFEST, encoding="utf-8")]
    by_id = {i["item_id"]: i for i in items}
    s = session()
    bad = []
    for item in sorted(items, key=lambda i: i["source_kind"] != "real_commons"):
        path = os.path.join(DATA, item["image_file"])
        if not os.path.exists(path):
            if item["source_kind"] == "real_commons":
                save(download(s, item["commons"]["thumb_url"]))
            else:
                src = by_id[item["duplicate_of"]]
                _derive(src, item["transformation"], TRANSFORMS.get(item["transformation"]), item["source_kind"], 0)
        if not os.path.exists(path) or hashlib.sha256(open(path, "rb").read()).hexdigest() != item["image_sha256"]:
            bad.append(item["item_id"])
    print(f"{len(items) - len(bad)}/{len(items)} images match the manifest; mismatched or missing: {bad}")
    return 1 if bad else 0


def summary(items):
    from collections import Counter
    print("items:", len(items))
    print("by split:", Counter(i["split"] for i in items))
    print("by kind:", Counter(i["source_kind"] for i in items))
    print("by class x condition:", Counter((i["provisional_image_class"], i["caption_condition"]) for i in items
                                          if i["source_kind"] == "real_commons"))
    print("by language:", Counter(i["caption_language"] for i in items))
    print("events:", Counter(i["event_group"] for i in items if i["source_kind"] == "real_commons"))
    print("licences:", Counter(i["commons"]["licence"] for i in items if i["source_kind"] == "real_commons"))


if __name__ == "__main__":
    sys.exit(main())
