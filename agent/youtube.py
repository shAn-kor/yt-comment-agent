"""영상 목록·자막·인기 댓글. YouTube Data API 키 없이 yt-dlp 라이브러리를 쓴다.
모두 블로킹 함수다. 서버는 스레드에서 부른다."""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, quote, urlparse

import httpx
from yt_dlp import YoutubeDL

from .config import Channel, Rising


VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")  # \w는 한글도 받아서 쓰지 않는다


def is_video_id(value) -> bool:
    return isinstance(value, str) and bool(VIDEO_ID.fullmatch(value))


def parse_video_id(value) -> str | None:
    s = str(value or "").strip()
    if is_video_id(s):
        return s
    try:
        u = urlparse(s)
    except ValueError:
        return None
    host = u.hostname or ""
    if host == "youtu.be" or host.endswith(".youtu.be"):
        v = u.path[1:12]
        return v if is_video_id(v) else None
    if host == "youtube.com" or host.endswith(".youtube.com"):
        if v := parse_qs(u.query).get("v"):
            return v[0] if is_video_id(v[0]) else None
        if m := re.search(r"/(shorts|live|embed)/([\w-]{11})", u.path):
            return m[2]
    return None


def _extract(
    url: str, extractor_args: dict | None = None, korean: bool = True, **opts
) -> dict:
    # lang=ko: 기본값이면 제목이 영어 자동 번역으로 온다
    # approximate_date: 채널 목록에서도 "3 days ago" 표시로 올린 날짜를 계산한다
    args = {
        "youtube": {"lang": ["ko"]} if korean else {},
        "youtubetab": {"approximate_date": [""]},
    }
    for k, v in (extractor_args or {}).items():
        args[k] = {**args.get(k, {}), **v}
    base = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": args,
    }
    try:
        with YoutubeDL({**base, **opts}) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:  # yt-dlp는 여러 종류의 예외를 낸다
        raise RuntimeError(f"yt-dlp 실패: {str(e).strip().splitlines()[-1]}") from e


def _iso(ts) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


RSS_TRIES = 3
RSS_WAIT = 0.5  # 초. 실패한 요청은 대개 바로 다시 하면 된다
_ATOM = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def _rss_feed(channel: Channel, limit: int) -> list[dict]:
    """채널 RSS. 올린 시각이 정확하다. 가끔 404·500을 내서 몇 번 다시 요청한다."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel.id}"
    last = ""
    for i in range(RSS_TRIES):
        if i:
            time.sleep(RSS_WAIT)
        try:
            res = httpx.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        except httpx.HTTPError as e:
            last = type(e).__name__
            continue
        if res.status_code == 200:
            break
        last = f"HTTP {res.status_code}"
    else:
        raise RuntimeError(f"RSS {RSS_TRIES}번 실패 ({last})")

    videos = []
    for e in ET.fromstring(res.content).findall("a:entry", _ATOM):
        title = e.findtext("a:title", "", _ATOM)
        # 라이브 방송 다시보기(유튜브 자동 제목)는 자막이 없고 장면을 짚기 어려워 뺀다
        if re.match(r"Live streaming of ", title, re.I):
            continue
        video_id = e.findtext("yt:videoId", "", _ATOM)
        stats = e.find("media:group/media:community/media:statistics", _ATOM)
        views = stats.get("views") if stats is not None else None
        published = e.findtext("a:published", "", _ATOM)
        videos.append(
            {
                "videoId": video_id,
                "title": title,
                "published": _iso(datetime.fromisoformat(published).timestamp()) if published else None,
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "views": int(views) if views and views.isdigit() else None,
                "channelId": channel.id,
                "channelName": channel.name,
            }
        )
    return [v for v in videos if v["videoId"]][:limit]


def _tab_feed(channel: Channel, limit: int) -> list[dict]:
    """채널 '동영상' 탭. RSS가 계속 실패할 때 쓴다.
    라이브 다시보기는 '라이브' 탭에 있어 여기 섞이지 않는다.
    올린 날짜는 "3일 전" 같은 표시에서 계산한 근삿값이다.
    한국어 화면으로 받으면 yt-dlp가 날짜·조회수를 못 읽고, 영어로 받으면 제목이 번역된다.
    그래서 두 번 읽어 합친다 (한 번에 1초 안쪽)."""
    url = f"https://www.youtube.com/channel/{channel.id}/videos"

    def listing(korean):
        return _extract(
            url, korean=korean, extract_flat="in_playlist", playlistend=limit
        )

    with ThreadPoolExecutor(2) as pool:
        ko, en = pool.map(listing, (True, False))
    titles = {e.get("id"): e.get("title") for e in ko.get("entries") or []}
    return [
        {
            "videoId": e["id"],
            "title": titles.get(e["id"]) or e.get("title") or "",
            "published": _iso(e.get("timestamp")),
            "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg",
            "views": e.get("view_count"),
            "channelId": channel.id,
            "channelName": channel.name,
        }
        for e in (en.get("entries") or [])[:limit]
        if e.get("id")
    ]


def fetch_channel_feed(channel: Channel, limit: int = 5) -> list[dict]:
    """채널 최신 영상. RSS를 먼저 쓰고, 다시 요청해도 실패하면 '동영상' 탭으로 넘어간다.
    영상마다 어느 방법으로 받았는지 via("rss" | "tab")에 적는다."""
    try:
        return [{**v, "via": "rss"} for v in _rss_feed(channel, limit)]
    except Exception as rss_error:
        try:
            return [{**v, "via": "tab"} for v in _tab_feed(channel, limit)]
        except RuntimeError as e:
            raise RuntimeError(f"{channel.name} 목록 실패: {rss_error}, {e}") from e


def _pick_caption(info: dict) -> tuple[str, str] | None:
    for label, tracks in (
        ("자막", info.get("subtitles")),
        ("자동 자막", info.get("automatic_captions")),
    ):
        if not tracks:
            continue
        key = next((k for k in ("ko-orig", "ko") if k in tracks), None) or next(
            (k for k in tracks if re.match(r"ko(-|$)", k)), None
        )
        fmt = key and next((f for f in tracks[key] if f.get("ext") == "json3"), None)
        if fmt:
            return label, fmt["url"]
    return None


def _fetch_transcript(url: str) -> str:
    try:
        data = httpx.get(url, timeout=30).json()
    except Exception:
        return ""
    words = [
        s.get("utf8", "") for e in data.get("events", []) for s in e.get("segs", [])
    ]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def get_video_context(video_id: str, comments: bool = True) -> dict:
    """영상 메타·자막·인기 댓글"""
    if not is_video_id(video_id):
        raise ValueError(f"영상 ID 형식이 아님: {video_id!r}")
    opts = {}
    if comments:
        opts = {
            "getcomments": True,
            "extractor_args": {
                "youtube": {
                    "comment_sort": ["top"],
                    "max_comments": ["40", "40", "0", "0"],
                }
            },
        }
    info = _extract(f"https://www.youtube.com/watch?v={video_id}", **opts)

    track = _pick_caption(info)
    transcript = _fetch_transcript(track[1]) if track else ""
    roots = [c for c in info.get("comments") or [] if c.get("parent") in (None, "root")]
    roots.sort(key=lambda c: c.get("like_count") or 0, reverse=True)

    if info.get("id") != video_id:
        raise RuntimeError(f"요청한 영상({video_id})과 받은 영상({info.get('id')})이 다름")
    return {
        "videoId": video_id,
        "title": info.get("title") or "",
        "description": (info.get("description") or "")[:1500],
        "channelId": info.get("channel_id"),
        "channelName": info.get("channel") or info.get("uploader") or "",
        "views": info.get("view_count"),
        "timestamp": info.get("timestamp"),
        "transcript": transcript,
        "sourceLabel": track[0] if transcript else "제목·설명",
        "topComments": [str(c.get("text") or "")[:200] for c in roots[:20]],
    }


def find_rising(r: Rising, now: float | None = None) -> list[dict]:
    """'연애' 오늘 올라온 영상 중 막 뜨기 시작한 영상 (초안까지만)"""
    now = time.time() if now is None else now
    # 검색 필터 '오늘 업로드' (sp=EgIIAg==)
    url = (
        f"https://www.youtube.com/results?search_query={quote(r.query)}&sp=EgIIAg%3D%3D"
    )
    listing = _extract(url, extract_flat="in_playlist", playlistend=r.scan)
    ids = [
        e["id"]
        for e in listing.get("entries") or []
        if e.get("id")
        and (
            e.get("view_count") is None or r.min_views <= e["view_count"] <= r.max_views
        )
    ]

    def info(vid):
        try:
            return _extract(f"https://www.youtube.com/watch?v={vid}")
        except RuntimeError:
            return None

    with ThreadPoolExecutor(4) as pool:
        infos = [v for v in pool.map(info, ids) if v]

    out = []
    for v in infos:
        # 방금 올린 영상의 값이 과하게 커지지 않도록 최소 15분으로 계산
        hours = max((now - (v.get("timestamp") or now)) / 3600, 0.25)
        views = v.get("view_count") or 0
        item = {
            "videoId": v["id"],
            "title": v.get("title"),
            "channelId": v.get("channel_id"),
            "channelName": v.get("channel") or v.get("uploader"),
            "thumbnail": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg",
            "published": _iso(v.get("timestamp")),
            "views": views,
            "viewsPerHour": round(views / hours),
        }
        if r.min_views <= views <= r.max_views and item["viewsPerHour"] >= r.min_vph:
            out.append(item)
    return sorted(out, key=lambda x: x["viewsPerHour"], reverse=True)
