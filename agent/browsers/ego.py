"""ego의 기존 로그인 세션을 쓰는 어댑터."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .port import LoginFailureCheck, StatusCallback

if TYPE_CHECKING:
    from ..config import Profile


@dataclass
class EgoPoster:
    profile: Profile

    def ready(self, *, login_failed_since: LoginFailureCheck, started_ms: int) -> bool:
        # ego는 로그인 표시가 없다. 이번 서버 실행 뒤의 로그인 실패만 본다.
        return not login_failed_since(self.profile.name, started_ms)

    async def post(
        self,
        *,
        video_id: str,
        text: str,
        shot_dir: Path,
        on_status: StatusCallback = lambda s: None,
    ) -> dict:
        from ..poster_ego import post_comment

        return await post_comment(
            profile_dir=self.profile.dir,
            video_id=video_id,
            text=text,
            shot_dir=shot_dir,
            on_status=on_status,
        )
