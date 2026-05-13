#!/usr/bin/env python3
"""
Build a reusable content catalog for the Manki Cantonese roadmap site.

What it does:
  1. Fetches all public playlists from the Manki Cantonese channel.
     - Preferred: official YouTube Data API, using YOUTUBE_API_KEY.
     - Fallback: scrape YouTube's public playlist page and parse ytInitialData.
  2. Captures playlist descriptions when using the YouTube Data API.
  3. Infers difficulty from playlist titles.
  4. Fetches recent uploads from YouTube RSS.
  5. Writes a JSON catalog plus a JS snippet that can be pasted into index.html.
  6. Optionally patches index.html's `const library = ...` and `const linkTargets = ...` blocks.

Usage:
  python manki_youtube_catalog.py
  YOUTUBE_API_KEY=... python manki_youtube_catalog.py --patch-index index.html
  python manki_youtube_catalog.py --out data/manki-catalog.json --js-out data/manki-catalog-snippet.js

No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

CHANNEL_ID = "UC9xosUh_LZUdQv-kw38RehA"
CHANNEL_PLAYLISTS_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}/playlists"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"
SCRIPT_VERSION = "2026-05-11-playlist-descriptions"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

LEVEL_ORDER = [
    "Absolute Beginner",
    "Beginner",
    "Advanced Beginner",
    "Low Intermediate",
    "Intermediate",
    "Upper Intermediate",
    "Advanced",
    "Misc",
]

# Order matters: check more-specific phrases before shorter phrases like "beginner".
LEVEL_PATTERNS: list[tuple[str, list[str]]] = [
    ("Absolute Beginner", ["absolute beginner"]),
    ("Advanced Beginner", ["advanced beginner", "upper beginner", "beginner+"]),
    ("Low Intermediate", ["low intermediate", "lower intermediate"]),
    ("Upper Intermediate", ["upper intermediate"]),
    ("Advanced", ["advanced"]),
    ("Intermediate", ["intermediate"]),
    ("Beginner", ["beginner"]),
]

# Reviewed from official YouTube playlistItems titles. These playlists do not
# expose a roadmap difficulty in the playlist title itself, but their video
# titles do.
LEVEL_OVERRIDES_BY_PLAYLIST_ID: dict[str, str] = {
    "PLI-XaJOyyTLTr3MEyfNGMjn1C8PY7HwjD": "Advanced",  # Advanced
    "PLI-XaJOyyTLQY9rCVpEa-26VBU4mWX_7D": "Advanced",  # Disco Elysium (Advanced)
    "PLI-XaJOyyTLSYH04pE60Ci7kOcYn3XCpK": "Intermediate",  # board game
    "PLI-XaJOyyTLT3W_tMtDLuqBFKdTBD6YwQ": "Intermediate",  # movie talk
    "PLI-XaJOyyTLR38oL_csT8UOSjrpEljjvQ": "Intermediate",  # Old Master Q
    "PLI-XaJOyyTLTdmffqj_ix8O9TvNwqaqvT": "Intermediate",  # storybook with transcript
    "PLI-XaJOyyTLQ59PO0So4g9IVYhhmswun3": "Intermediate",  # The Untitled Goose Game
    "PLI-XaJOyyTLSUE4qsMPcHhEHLSzulCk_X": "Intermediate",  # tutorial
    "PLI-XaJOyyTLRMf0txpKhEvHM8cPH-g4oI": "Intermediate",  # watch together
}

LEVEL_PLAYLIST_TITLES: dict[str, list[str]] = {
    "Advanced Beginner": ["Beginner+"],
    "Upper Intermediate": ["Intermediate+"],
}


@dataclass
class Playlist:
    title: str
    playlist_id: str
    url: str
    thumbnail: str | None = None
    description: str | None = None
    level: str = "Misc"
    video_count: int | None = None
    source: str = "unknown"

    @property
    def display_title(self) -> str:
        # Remove trailing level markers from titles like "Bear (Absolute Beginner)".
        title = self.title.strip()
        title = re.sub(
            r"\s*\((absolute beginner|advanced beginner|upper beginner|beginner\+|beginner|low intermediate|lower intermediate|intermediate|upper intermediate|advanced)\)\s*$",
            "",
            title,
            flags=re.I,
        )
        return html.unescape(title).strip()


def fetch_text(url: str, *, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    return json.loads(fetch_text(url, timeout=timeout))


def best_thumbnail(thumbnails: dict[str, Any] | None) -> str | None:
    if not thumbnails:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = thumbnails.get(key, {}).get("url")
        if url:
            return url
    for value in thumbnails.values():
        if isinstance(value, dict) and value.get("url"):
            return value["url"]
    return None


def clean_description(value: str | None) -> str | None:
    """Normalize YouTube description text for JSON output."""
    if not value:
        return None
    value = html.unescape(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return value or None


def playlist_description_from_snippet(snippet: dict[str, Any]) -> str | None:
    """Return the official playlist description when available.

    YouTube playlist descriptions live under snippet.description. Some responses also
    include snippet.localized.description; use it as a fallback only.
    """
    description = clean_description(snippet.get("description"))
    if description:
        return description
    localized = snippet.get("localized")
    if isinstance(localized, dict):
        return clean_description(localized.get("description"))
    return None


def infer_level(title: str) -> str:
    lower = title.lower()
    for level, patterns in LEVEL_PATTERNS:
        if any(pattern in lower for pattern in patterns):
            return level
    return "Misc"


def apply_level_overrides(playlists: list[Playlist]) -> None:
    for playlist in playlists:
        override = LEVEL_OVERRIDES_BY_PLAYLIST_ID.get(playlist.playlist_id)
        if override:
            playlist.level = override


def is_level_playlist(playlist: Playlist, level: str) -> bool:
    titles = {level.casefold(), *(title.casefold() for title in LEVEL_PLAYLIST_TITLES.get(level, []))}
    return playlist.display_title.casefold() in titles or playlist.title.casefold() in titles


def normalize_youtube_thumb(url: str | None) -> str | None:
    if not url:
        return None
    # YouTube often HTML-escapes ampersands in ytInitialData.
    return html.unescape(url)


def fetch_playlists_api(api_key: str, channel_id: str) -> list[Playlist]:
    playlists: list[Playlist] = []
    page_token = ""

    while True:
        params = {
            "part": "snippet,contentDetails",
            "channelId": channel_id,
            "maxResults": "50",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        url = "https://www.googleapis.com/youtube/v3/playlists?" + urllib.parse.urlencode(params)
        data = fetch_json(url)

        for item in data.get("items", []):
            playlist_id = item.get("id")
            snippet = item.get("snippet", {})
            title = snippet.get("title")
            if not playlist_id or not title:
                continue

            playlists.append(
                Playlist(
                    title=title,
                    playlist_id=playlist_id,
                    url=PLAYLIST_URL.format(playlist_id=playlist_id),
                    thumbnail=best_thumbnail(snippet.get("thumbnails")),
                    description=playlist_description_from_snippet(snippet),
                    level=infer_level(title),
                    video_count=item.get("contentDetails", {}).get("itemCount"),
                    source="youtube_data_api",
                )
            )

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    return dedupe_playlists(playlists)


def extract_yt_initial_data(page_html: str) -> dict[str, Any]:
    # Avoid a huge regex over the full JSON; find the assignment then bracket-match.
    markers = ("var ytInitialData =", "window[\"ytInitialData\"] =")
    start = -1
    for marker in markers:
        start = page_html.find(marker)
        if start != -1:
            start = page_html.find("{", start)
            break
    if start == -1:
        raise ValueError("Could not find ytInitialData in playlist page HTML.")

    depth = 0
    in_string = False
    escape = False
    end = None
    for idx in range(start, len(page_html)):
        ch = page_html[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
    if end is None:
        raise ValueError("Could not bracket-match ytInitialData JSON.")
    return json.loads(page_html[start:end])


def walk(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def first_string(obj: Any) -> str | None:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        # YouTube text fields commonly use {"content": "..."}.
        if isinstance(obj.get("content"), str):
            return obj["content"]
        if isinstance(obj.get("simpleText"), str):
            return obj["simpleText"]
        runs = obj.get("runs")
        if isinstance(runs, list):
            text = "".join(run.get("text", "") for run in runs if isinstance(run, dict))
            return text or None
    return None


def lockup_to_playlist(lockup: dict[str, Any]) -> Playlist | None:
    if lockup.get("contentType") != "LOCKUP_CONTENT_TYPE_PLAYLIST":
        return None

    playlist_id = lockup.get("contentId")
    title = first_string(
        lockup.get("metadata", {})
        .get("lockupMetadataViewModel", {})
        .get("title", {})
    )
    if not playlist_id or not title:
        return None

    thumb = None
    image = (
        lockup.get("contentImage", {})
        .get("collectionThumbnailViewModel", {})
        .get("primaryThumbnail", {})
        .get("thumbnailViewModel", {})
        .get("image", {})
    )
    sources = image.get("sources")
    if isinstance(sources, list) and sources:
        # Prefer the last source, usually the largest.
        thumb = sources[-1].get("url") or sources[0].get("url")

    count_text = None
    for node in walk(lockup.get("contentImage", {})):
        if isinstance(node, dict) and "thumbnailBadgeViewModel" in node:
            count_text = first_string(node["thumbnailBadgeViewModel"].get("text"))
            break
    video_count = None
    if count_text:
        m = re.search(r"(\d+)", count_text.replace(",", ""))
        if m:
            video_count = int(m.group(1))

    return Playlist(
        title=html.unescape(title),
        playlist_id=playlist_id,
        url=PLAYLIST_URL.format(playlist_id=playlist_id),
        thumbnail=normalize_youtube_thumb(thumb),
        level=infer_level(title),
        video_count=video_count,
        source="yt_initial_data_scrape",
    )


def fetch_playlists_scrape(channel_id: str) -> list[Playlist]:
    page_html = fetch_text(f"https://www.youtube.com/channel/{channel_id}/playlists")
    data = extract_yt_initial_data(page_html)

    playlists: list[Playlist] = []
    for node in walk(data):
        if isinstance(node, dict) and "lockupViewModel" in node:
            playlist = lockup_to_playlist(node["lockupViewModel"])
            if playlist:
                playlists.append(playlist)
        elif isinstance(node, dict) and node.get("contentType") == "LOCKUP_CONTENT_TYPE_PLAYLIST":
            playlist = lockup_to_playlist(node)
            if playlist:
                playlists.append(playlist)

    return dedupe_playlists(playlists)


def dedupe_playlists(playlists: list[Playlist]) -> list[Playlist]:
    seen: set[str] = set()
    unique: list[Playlist] = []
    for playlist in playlists:
        if playlist.playlist_id in seen:
            continue
        seen.add(playlist.playlist_id)
        unique.append(playlist)
    return sorted(unique, key=lambda p: (LEVEL_ORDER.index(p.level), p.display_title.lower()))


def fetch_recent_uploads(channel_id: str) -> list[dict[str, Any]]:
    xml_text = fetch_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    root = ET.fromstring(xml_text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    videos: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title", default="", namespaces=ns)
        published = entry.findtext("atom:published", default="", namespaces=ns)
        updated = entry.findtext("atom:updated", default="", namespaces=ns)
        media_group = entry.find("media:group", ns)
        thumbnail = None
        description = None
        if media_group is not None:
            thumb_el = media_group.find("media:thumbnail", ns)
            if thumb_el is not None:
                thumbnail = thumb_el.attrib.get("url")
            description = media_group.findtext("media:description", default=None, namespaces=ns)
        if video_id:
            videos.append(
                {
                    "video_id": video_id,
                    "title": html.unescape(title),
                    "url": WATCH_URL.format(video_id=video_id),
                    "published": published,
                    "updated": updated,
                    "thumbnail": thumbnail,
                    "description": description,
                }
            )
    return videos


def grouped_library(playlists: list[Playlist]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for level in LEVEL_ORDER:
        items = [p for p in playlists if p.level == level and not is_level_playlist(p, level)]
        if not items:
            continue
        groups.append(
            {
                "level": level,
                "items": [
                    [
                        p.display_title,
                        p.url,
                        p.thumbnail or f"https://i.ytimg.com/vi/{p.playlist_id}/hqdefault.jpg",
                        p.description,
                    ]
                    for p in items
                ],
            }
        )
    return groups


def link_targets(playlists: list[Playlist]) -> list[list[str]]:
    pairs: list[list[str]] = []
    seen_titles: set[str] = set()
    for p in playlists:
        title = p.display_title
        if title not in seen_titles:
            pairs.append([title, p.url])
            seen_titles.add(title)
        # Add a few safe aliases from common titles without punctuation/level words.
        alias = re.sub(r"^The\s+", "", title, flags=re.I)
        if alias != title and alias not in seen_titles:
            pairs.append([alias, p.url])
            seen_titles.add(alias)
    return pairs


def js_literal(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=6)


def write_js_snippet(path: Path, library: list[dict[str, Any]], targets: list[list[str]]) -> None:
    # This intentionally matches your current index.html structure.
    lib_js = json.dumps(library, ensure_ascii=False, indent=4)
    targets_js = json.dumps(targets, ensure_ascii=False, indent=6)
    text = (
        "// Generated by manki_youtube_catalog.py. Paste these blocks into index.html if needed.\n\n"
        f"const library = {lib_js};\n\n"
        f"const linkTargets = new Map({targets_js});\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def find_js_assignment_end(text: str, start: int) -> int:
    # Start points at the beginning of `const name = ...`; find the semicolon after the
    # first top-level array/object/new Map expression.
    eq = text.find("=", start)
    if eq == -1:
        raise ValueError("Could not find equals sign in JS assignment.")

    expr_start = None
    opening = None
    for idx in range(eq + 1, len(text)):
        if text[idx] in "[{(":
            expr_start = idx
            opening = text[idx]
            break
    if expr_start is None or opening is None:
        raise ValueError("Could not find start of JS expression.")

    pairs = {"[": "]", "{": "}", "(": ")"}
    stack = [pairs[opening]]
    in_string: str | None = None
    escape = False
    template_depth = 0

    for idx in range(expr_start + 1, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in ('"', "'", "`"):
            in_string = ch
            continue
        if ch in "[{(":
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                semicolon = text.find(";", idx)
                if semicolon == -1:
                    raise ValueError("Could not find semicolon after JS assignment.")
                return semicolon + 1
    raise ValueError("Could not find end of JS assignment.")


def patch_index(index_path: Path, library: list[dict[str, Any]], targets: list[list[str]]) -> None:
    text = index_path.read_text(encoding="utf-8")

    lib_start = text.find("const library =")
    if lib_start == -1:
        raise ValueError("index.html does not contain `const library =`.")
    lib_end = find_js_assignment_end(text, lib_start)
    lib_replacement = "const library = " + json.dumps(library, ensure_ascii=False, indent=4) + ";"
    text = text[:lib_start] + lib_replacement + text[lib_end:]

    target_start = text.find("const linkTargets =")
    if target_start == -1:
        raise ValueError("index.html does not contain `const linkTargets =`.")
    target_end = find_js_assignment_end(text, target_start)
    target_replacement = "const linkTargets = new Map(" + json.dumps(targets, ensure_ascii=False, indent=6) + ");"
    text = text[:target_start] + target_replacement + text[target_end:]

    index_path.write_text(text, encoding="utf-8")


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    api_key = args.api_key or os.environ.get("YOUTUBE_API_KEY")
    if api_key:
        try:
            playlists = fetch_playlists_api(api_key, args.channel_id)
        except Exception as exc:
            if not args.allow_scrape_fallback:
                raise
            print(f"YouTube Data API failed; falling back to playlist-page scrape: {exc}", file=sys.stderr)
            playlists = fetch_playlists_scrape(args.channel_id)
    else:
        playlists = fetch_playlists_scrape(args.channel_id)

    apply_level_overrides(playlists)
    playlists = sorted(playlists, key=lambda p: (LEVEL_ORDER.index(p.level), p.display_title.lower()))

    recent_videos: list[dict[str, Any]] = []
    if not args.skip_rss:
        try:
            recent_videos = fetch_recent_uploads(args.channel_id)
        except Exception as exc:
            print(f"Warning: RSS fetch failed: {exc}", file=sys.stderr)

    library = grouped_library(playlists)
    targets = link_targets(playlists)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "channel_id": args.channel_id,
        "channel_url": f"https://www.youtube.com/channel/{args.channel_id}",
        "playlists": [asdict(p) | {"display_title": p.display_title} for p in playlists],
        "playlist_descriptions": {p.display_title: p.description for p in playlists if p.description},
        "library": library,
        "link_targets": targets,
        "recent_videos": recent_videos,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Manki Cantonese roadmap catalog data from YouTube.")
    parser.add_argument("--channel-id", default=CHANNEL_ID)
    parser.add_argument("--api-key", default=None, help="YouTube Data API key. Defaults to YOUTUBE_API_KEY env var.")
    parser.add_argument("--out", default="generated/manki-catalog.json", help="JSON catalog output path.")
    parser.add_argument("--js-out", default="generated/manki-catalog-snippet.js", help="Pasteable JS snippet output path.")
    parser.add_argument("--patch-index", default=None, help="Optional index.html path to patch in place.")
    parser.add_argument("--skip-rss", action="store_true", help="Skip recent uploads RSS fetch.")
    parser.add_argument("--allow-scrape-fallback", action="store_true", default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog = build_catalog(args)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    js_out = Path(args.js_out)
    write_js_snippet(js_out, catalog["library"], catalog["link_targets"])

    if args.patch_index:
        patch_index(Path(args.patch_index), catalog["library"], catalog["link_targets"])

    print(f"Wrote {out_path}")
    print(f"Wrote {js_out}")
    if args.patch_index:
        print(f"Patched {args.patch_index}")
    print(f"Found {len(catalog['playlists'])} playlists and {len(catalog['recent_videos'])} recent RSS videos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
