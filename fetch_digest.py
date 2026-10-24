#!/usr/bin/env python3
"""
fetch_digest.py

Project: Daily AI news digest.

Architecture (fan-out / merge):
  1. FAN-OUT: reads several RSS feeds independently (each source is a node).
  2. FILTER: keeps only entries published within the given hour window
     (default 26h, to cover gaps between runs).
  3. MERGE: combines all entries into a single digest, grouped by category,
     and saves it as Markdown to output/digest_YYYY-MM-DD.md.

Does not call any AI model: it only collects, filters and ranks headlines
using plain rules (see priorities.yaml), so it needs no paid API key.

Besides the date filter, it applies a RELEVANCE filter by keywords
(see priorities.yaml): discards obvious noise (generic listicles) and
prioritizes items mentioning the labs/topics dominating the news cycle,
keeping only the top N items per category.

Usage:
    python3 fetch_digest.py [--hours 26] [--feeds feeds.yaml] [--priorities priorities.yaml] [--max-per-category 5] [--out output]
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import yaml

LOCAL_TZ = ZoneInfo("Pacific/Auckland")


def load_feeds(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("feeds", [])


def load_priorities(path: str):
    """Loads labs/themes/noise from priorities.yaml. If it doesn't exist, nothing is filtered."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {"labs": [], "themes": [], "noise": []}
    return {
        "labs": data.get("labs", []) or [],
        "themes": data.get("themes", []) or [],
        "noise": data.get("noise", []) or [],
    }


def score_item(item, priorities):
    """Scores an item by relevance. Returns None if it should be discarded (noise)."""
    title_lower = item["title"].lower()

    for pattern in priorities["noise"]:
        if pattern.lower() in title_lower:
            return None

    score = 0
    for lab in priorities["labs"]:
        if lab.lower() in title_lower:
            score += 3
    for theme in priorities["themes"]:
        if theme.lower() in title_lower:
            score += 1
    return score


def entry_datetime(entry):
    """Returns a timezone-aware datetime for a feedparser entry, or None."""
    for field in ("published_parsed", "updated_parsed"):
        value = getattr(entry, field, None)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def fetch_one_feed(feed_cfg, cutoff, timeout=15):
    """FAN-OUT: processes a source independently.
    Returns (source_name, list_of_items, error_or_None).
    """
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    category = feed_cfg.get("category", "General")

    try:
        parsed = feedparser.parse(url, request_headers={"User-Agent": "ai-news-digest/1.0"})
        if parsed.bozo and not parsed.entries:
            return name, [], f"Error parsing feed: {parsed.bozo_exception}"

        items = []
        for entry in parsed.entries:
            dt = entry_datetime(entry)
            if dt is not None and dt < cutoff:
                continue
            items.append(
                {
                    "title": entry.get("title", "(sin título)").strip(),
                    "link": entry.get("link", ""),
                    "published": dt.isoformat() if dt else None,
                    "source": name,
                    "category": category,
                }
            )
        return name, items, None
    except Exception as exc:  # noqa: BLE001
        return name, [], str(exc)


def dedupe(items):
    """Removes duplicates by normalized title (multiple sources may cite the same news item)."""
    seen = set()
    unique = []
    for item in items:
        key = item["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def sanitize_md(text):
    """Strips characters that would break Telegram's Markdown parsing (*, _, `)."""
    return re.sub(r"[*_`]", "", text or "")


def build_digest_markdown(items, run_date, hours):
    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    lines = [f"*Digest de noticias de IA — {run_date.isoformat()}*", ""]
    lines.append(f"_Ventana: últimas {hours} horas. Total de items: {len(items)}._")
    lines.append("")

    if not items:
        lines.append("No se encontraron noticias nuevas en esta ventana.")
        return "\n".join(lines)

    for category, cat_items in sorted(by_category.items()):
        lines.append(f"*{sanitize_md(category)}*")
        lines.append("")
        for item in sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True):
            title = sanitize_md(item["title"])
            source = sanitize_md(item["source"])
            lines.append(f"• *{title}* ({source}) — {item['link']}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fan-out + merge of AI RSS feeds into a daily digest.")
    parser.add_argument("--hours", type=int, default=26)
    parser.add_argument("--feeds", type=str, default=str(Path(__file__).parent / "feeds.yaml"))
    parser.add_argument("--priorities", type=str, default=str(Path(__file__).parent / "priorities.yaml"))
    parser.add_argument("--max-per-category", type=int, default=5)
    parser.add_argument("--out", type=str, default=str(Path(__file__).parent / "output"))
    args = parser.parse_args()

    feeds_cfg = load_feeds(args.feeds)
    if not feeds_cfg:
        print("No feeds configured in feeds.yaml", file=sys.stderr)
        sys.exit(1)

    priorities = load_priorities(args.priorities)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)
    local_date = now.astimezone(LOCAL_TZ).date()

    all_items = []
    errors = []

    for feed_cfg in feeds_cfg:
        name, items, error = fetch_one_feed(feed_cfg, cutoff)
        print(f"[{name}] {len(items)} new items" + (f" -- ERROR: {error}" if error else ""))
        all_items.extend(items)
        if error:
            errors.append((name, error))

    all_items = dedupe(all_items)
    total_before_filter = len(all_items)

    scored_items = []
    discarded_noise = 0
    for item in all_items:
        score = score_item(item, priorities)
        if score is None:
            discarded_noise += 1
            continue
        item["score"] = score
        scored_items.append(item)

    by_category = {}
    for item in scored_items:
        by_category.setdefault(item["category"], []).append(item)

    final_items = []
    for cat_items in by_category.values():
        cat_items.sort(key=lambda x: x["score"], reverse=True)
        final_items.extend(cat_items[: args.max_per_category])

    print(
        f"\nRelevance filter: {total_before_filter} items -> "
        f"{discarded_noise} discarded as noise -> {len(final_items)} left after keeping "
        f"the top {args.max_per_category} per category"
    )

    digest_md = build_digest_markdown(final_items, local_date, args.hours)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"digest_{local_date.isoformat()}.md"
    out_path.write_text(digest_md, encoding="utf-8")

    print(f"\nDigest saved to: {out_path}")
    if errors:
        print("\nWarnings:")
        for name, error in errors:
            print(f"  - {name}: {error}")


if __name__ == "__main__":
    main()
