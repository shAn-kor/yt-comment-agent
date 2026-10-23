"""브라우저 게시 포트. 서버는 브라우저 구현 대신 이 계약만 사용한다."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

StatusCallback = Callable[[str], None]
LoginFailureCheck = Callable[[str, int], bool]


class PostError(Exception):
    def __init__(
        self, message: str, screenshot: str | None = None, submitted: bool = False
    ):
        super().__init__(message)
        self.screenshot = screenshot
        self.submitted = submitted  # 게시 버튼 뒤 실패는 실제로 올라갔을 수 있다


@runtime_checkable
class CommentPoster(Protocol):
    """프로필에 묶인 게시자. 준비 확인은 브라우저를 열거나 외부 요청을 하지 않는다."""

    def ready(self, *, login_failed_since: LoginFailureCheck, started_ms: int) -> bool:
        """로그인 표시와 실패 기록을 바탕으로 프로필 준비 여부를 반환한다."""
        ...

    async def post(
        self,
        *,
        video_id: str,
        text: str,
        shot_dir: Path,
        on_status: StatusCallback = lambda s: None,
    ) -> dict:
        """commentUrl/screenshot을 반환한다. 게시 뒤 실패는 PostError(submitted=True)."""
        ...
