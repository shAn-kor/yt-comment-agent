"""설정 이름 → 어댑터. 새 브라우저는 구현 파일을 만들고 이 표에 등록한다."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .port import CommentPoster

if TYPE_CHECKING:
    from ..config import Profile

# 모듈:클래스. 설정을 읽을 때는 브라우저 라이브러리를 불러오지 않는다.
ADAPTERS = {
    "chrome": "agent.browsers.chrome:ChromePoster",
    "ego": "agent.browsers.ego:EgoPoster",
}


def validate_browser(name: str) -> str:
    if not isinstance(name, str) or name not in ADAPTERS:
        raise ValueError(
            f"알 수 없는 브라우저: {name!r} (지원: {', '.join(sorted(ADAPTERS))})"
        )
    return name


def create_poster(profile: Profile) -> CommentPoster:
    module_name, class_name = ADAPTERS[validate_browser(profile.browser)].split(":")
    adapter = getattr(import_module(module_name), class_name)
    return adapter(profile)
