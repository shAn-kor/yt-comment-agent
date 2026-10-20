"""운영 규칙. 게시 직전에 서버에서 검사한다 (화면에서 버튼을 숨기는 것과 별개)."""

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .config import Config

KST = timezone(timedelta(hours=9))


def kst_date(t: float | None = None) -> str:
    """한국 시간 기준 날짜 (YYYY-MM-DD). t는 초 단위 Unix 시각."""
    return datetime.fromtimestamp(time.time() if t is None else t, KST).strftime(
        "%Y-%m-%d"
    )


def _fail(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def check_load_scope(video: dict, config: Config) -> dict:
    """불러오기·초안 허용 범위: 지정 채널 영상 또는 본인 테스트 영상"""
    if video["videoId"] in config.test_videos:
        return {"ok": True, "kind": "test"}
    if any(c.id == video.get("channelId") for c in config.channels):
        return {"ok": True, "kind": "channel"}
    return _fail("허용 범위 밖 채널")


def check_post_scope(video: dict, config: Config) -> dict:
    """게시 허용 범위: test_only면 테스트 영상만"""
    if video["videoId"] in config.test_videos:
        return {"ok": True, "kind": "test"}
    if config.posting_scope != "channels":
        return _fail("테스트 모드: 본인 테스트 영상에만 게시")
    return check_load_scope(video, config)


class PostHistory(Protocol):
    def has_success(self, video_id: str) -> bool: ...
    def count_success_on(self, day: str) -> int: ...


def check_post(
    video: dict,
    profile: str,
    config: Config,
    store: PostHistory,
    now: float | None = None,
) -> dict:
    if not any(p.name == profile for p in config.profiles):
        return _fail(f"설정에 없는 프로필 ({profile})")
    scope = check_post_scope(video, config)
    if not scope["ok"]:
        return scope
    if store.has_success(video["videoId"]):
        return _fail("이미 댓글을 단 영상 (영상당 1개)")
    if store.count_success_on(kst_date(now)) >= config.limits.daily_max:
        return _fail(f"오늘 게시 상한 {config.limits.daily_max}개 도달")
    return {"ok": True}


def pick_profile(config: Config, last_used: Callable[[str], float]) -> str | None:
    """자동 배정: 가장 오래 안 쓴 프로필"""
    ordered = sorted(config.profiles, key=lambda p: last_used(p.name))
    return ordered[0].name if ordered else None
