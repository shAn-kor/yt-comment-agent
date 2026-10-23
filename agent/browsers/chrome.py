"""로컬 Chrome 프로필 어댑터. 실제 입력·확인 순서는 기존 드라이버를 쓴다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .port import LoginFailureCheck, StatusCallback

if TYPE_CHECKING:
    from ..config import Profile


@dataclass
class ChromePoster:
    profile: Profile

    def ready(self, *, login_failed_since: LoginFailureCheck, started_ms: int) -> bool:
        at = self.profile.login_at()
        return at is not None and not login_failed_since(self.profile.name, at)

    async def post(
        self,
        *,
        video_id: str,
        text: str,
        shot_dir: Path,
        on_status: StatusCallback = lambda s: None,
    ) -> dict:
        from ..poster import post_comment

        return await post_comment(
            profile_dir=self.profile.dir,
            video_id=video_id,
            text=text,
            shot_dir=shot_dir,
            on_status=on_status,
        )
