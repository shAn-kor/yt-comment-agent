import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env(file: Path = ROOT / ".env") -> None:
    """.env를 읽어 os.environ에 없는 값만 채운다."""
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m and m[2] and m[1] not in os.environ:
            os.environ[m[1]] = m[2].strip("\"'")


LOGIN_MARK = ".agent-login"  # scripts/login.py가 프로필 폴더에 남기는 표시 (로그인 창을 연 시각)


@dataclass
class Profile:
    name: str
    dir: Path
    browser: str = "chrome"  # chrome: 이 폴더의 크롬 프로필 / ego: ego 브라우저에 로그인된 계정

    def login_at(self) -> int | None:
        """login.py로 로그인 창을 연 시각(밀리초). 연 적이 없으면 None"""
        mark = self.dir / LOGIN_MARK if self.dir else None
        return int(mark.stat().st_mtime * 1000) if mark and mark.exists() else None


@dataclass
class Channel:
    id: str
    name: str


@dataclass
class CommentRules:
    min: int = 40
    max: int = 120
    brand: str = "운명원"


@dataclass
class Limits:
    daily_max: int = 10
    per_channel: int = 5


@dataclass
class Rising:
    query: str = "연애"
    scan: int = 30
    min_views: int = 1000
    max_views: int = 5000
    min_vph: int = 150


@dataclass
class Config:
    profiles: list[Profile] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    test_videos: list[str] = field(default_factory=list)
    posting_scope: str = "test_only"  # test_only | channels
    comment: CommentRules = field(default_factory=CommentRules)
    limits: Limits = field(default_factory=Limits)
    rising: Rising = field(default_factory=Rising)


def load_config(file: Path = ROOT / "config.yaml") -> Config:
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    comment = raw.get("comment") or {}
    limits = raw.get("limits") or {}
    rising = raw.get("rising") or {}

    def profile(p):
        if isinstance(p, str):
            return Profile(p, ROOT / "profiles" / p)
        return Profile(
            p["name"],
            (ROOT / (p.get("dir") or f"profiles/{p['name']}")).resolve(),
            "ego" if p.get("browser") == "ego" else "chrome",
        )

    return Config(
        profiles=[profile(p) for p in raw.get("profiles") or []],
        channels=[
            Channel(c, c) if isinstance(c, str) else Channel(c["id"], c["name"])
            for c in raw.get("channels") or []
        ],
        test_videos=[str(v) for v in raw.get("test_videos") or []],
        # 이상한 값은 안전한 쪽(test_only)으로 본다
        posting_scope="channels"
        if raw.get("posting_scope") == "channels"
        else "test_only",
        comment=CommentRules(
            min=comment.get("min_chars", 40),
            max=comment.get("max_chars", 120),
            brand=comment.get("brand", "운명원"),
        ),
        limits=Limits(
            daily_max=limits.get("daily_max_comments", 10),
            per_channel=limits.get("videos_per_channel", 5),
        ),
        rising=Rising(
            query=rising.get("query", "연애"),
            scan=rising.get("scan", 30),
            min_views=rising.get("min_views", 1000),
            max_views=rising.get("max_views", 5000),
            min_vph=rising.get("min_views_per_hour", 150),
        ),
    )
