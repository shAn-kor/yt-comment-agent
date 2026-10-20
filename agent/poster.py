"""크롬 프로필을 화면에 띄우고 한 글자씩 입력해 댓글을 게시한 뒤, 내 댓글이 보이는지 확인한다.
유튜브 한국어 화면(hl=ko) 기준."""

import asyncio
import os
import random
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from playwright.async_api import async_playwright


class PostError(Exception):
    def __init__(self, message: str, screenshot: str | None = None):
        super().__init__(message)
        self.screenshot = screenshot


async def post_comment(
    *,
    profile_dir: Path,
    video_id: str,
    text: str,
    shot_dir: Path,
    on_status: Callable[[str], None] = lambda s: None,
) -> dict:
    shot_dir.mkdir(parents=True, exist_ok=True)

    async def shot(page, tag: str) -> str:
        file = f"{int(time.time() * 1000)}-{video_id}-{tag}.png"
        try:
            await page.screenshot(path=shot_dir / file)
        except Exception:
            pass
        return file

    on_status("프로필 여는 중")
    async with async_playwright() as pw:
        chrome = os.environ.get("CHROME_PATH")
        ctx = await pw.chromium.launch_persistent_context(
            str(profile_dir),
            channel=None if chrome else "chrome",
            executable_path=chrome or None,
            headless=False,  # 시연 영상에서 실제 입력이 보이게
            no_viewport=True,
            locale="ko-KR",
            args=["--lang=ko-KR", "--window-size=1280,900"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            on_status("영상 여는 중")
            await page.goto(
                f"https://www.youtube.com/watch?v={video_id}&hl=ko",
                wait_until="domcontentloaded",
            )
            await page.wait_for_selector("ytd-watch-flexy", timeout=30_000)

            sign_in = page.locator(
                'ytd-masthead a[href*="accounts.google.com/ServiceLogin"]'
            ).first
            if await sign_in.is_visible():
                raise PostError(
                    "로그인 안 됨 — uv run python scripts/login.py <프로필 이름> 으로 먼저 로그인하세요",
                    await shot(page, "signed-out"),
                )

            on_status("댓글창 찾는 중")
            placeholder = page.locator(
                "ytd-comments ytd-comment-simplebox-renderer #placeholder-area"
            )
            for _ in range(15):
                if await placeholder.count():
                    break
                if await page.locator("ytd-comments ytd-message-renderer").is_visible():
                    raise PostError(
                        "댓글 사용이 중지된 영상", await shot(page, "comments-off")
                    )
                await page.mouse.wheel(0, 700)
                await asyncio.sleep(0.8)
            if not await placeholder.count():
                raise PostError("댓글 입력창을 찾지 못함", await shot(page, "no-box"))
            await placeholder.scroll_into_view_if_needed()
            await placeholder.click()

            box = page.locator("ytd-commentbox #contenteditable-root")
            await box.wait_for(state="visible", timeout=10_000)
            await box.click()

            on_status("입력 중")
            for ch in text:
                await page.keyboard.type(ch)
                await asyncio.sleep(0.06 + random.random() * 0.11)
            await asyncio.sleep(0.6)

            on_status("게시 중")
            await page.locator(
                "ytd-commentbox #submit-button button, ytd-commentbox #submit-button"
            ).first.click()

            on_status("내 댓글 확인 중")
            mine = (
                page.locator("ytd-comment-thread-renderer")
                .filter(has=page.locator("#content-text", has_text=text[:18]))
                .first
            )
            try:
                await mine.wait_for(state="visible", timeout=20_000)
            except Exception:
                raise PostError(
                    "게시 후 내 댓글이 보이지 않음", await shot(page, "not-visible")
                )
            await mine.scroll_into_view_if_needed()

            try:
                href = await mine.locator("#published-time-text a").first.get_attribute(
                    "href", timeout=3000
                )
            except Exception:
                href = None
            comment_url = (
                urljoin("https://www.youtube.com", href)
                if href
                else f"https://www.youtube.com/watch?v={video_id}"
            )
            screenshot = await shot(page, "posted")
            on_status("게시 완료")
            await asyncio.sleep(2.5)  # 시연 화면에서 결과를 볼 시간
            return {"commentUrl": comment_url, "screenshot": screenshot}
        except PostError:
            raise
        except Exception as e:
            raise PostError(str(e).split("\n")[0], await shot(page, "error")) from e
        finally:
            try:
                await ctx.close()
            except Exception:
                pass
