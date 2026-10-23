"""브라우저 포트·팩터리. 브라우저를 열거나 댓글을 게시하지 않는다."""

import asyncio
import importlib
import os
import subprocess
import sys

import pytest

from agent.browsers import CommentPoster, PostError, create_poster, registry
from agent.config import LOGIN_MARK, ROOT, Profile, load_config


@pytest.mark.parametrize(
    "name,adapter", [("chrome", "ChromePoster"), ("ego", "EgoPoster")]
)
def test_등록된_브라우저_팩터리(name, adapter, tmp_path):
    profile = Profile("테스트", tmp_path, name)
    poster = create_poster(profile)
    assert isinstance(poster, CommentPoster)
    assert type(poster).__name__ == adapter
    assert poster.profile is profile


@pytest.mark.parametrize("name", ["firefox", "", None, 0, ["ego"]])
def test_알_수_없는_브라우저는_설정에서_지원_이름과_함께_거절(name, tmp_path):
    import yaml

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"profiles": [{"name": "test", "browser": name}]}))
    with pytest.raises(ValueError, match="알 수 없는 브라우저.*지원: chrome, ego"):
        load_config(config)


def test_팩터리도_등록되지_않은_이름을_거절(tmp_path):
    with pytest.raises(ValueError, match="지원: chrome, ego"):
        create_poster(Profile("테스트", tmp_path, "unknown"))


def test_기존_문자열_프로필과_browser_누락은_크롬(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("profiles: [유튜브1, {name: 유튜브2}]", encoding="utf-8")
    assert [p.browser for p in load_config(config).profiles] == ["chrome", "chrome"]


class ExtraPoster:
    def __init__(self, profile):
        self.profile = profile

    def ready(self, **_):
        return True

    async def post(self, **_):
        return {"commentUrl": "test", "screenshot": None}


def test_새_어댑터_등록은_설정과_팩터리에_함께_반영(monkeypatch, tmp_path):
    monkeypatch.setitem(registry.ADAPTERS, "extra", "tests.test_browsers:ExtraPoster")
    config = tmp_path / "config.yaml"
    config.write_text("profiles: [{name: extra, browser: extra}]")
    [profile] = load_config(config).profiles
    assert isinstance(create_poster(profile), ExtraPoster)


def test_크롬_준비_여부는_로그인_표시_이후_실패를_확인(tmp_path):
    profile = Profile("크롬", tmp_path / "profile")
    poster = create_poster(profile)
    seen = []

    def failed(name, since):
        seen.append((name, since))
        return False

    assert not poster.ready(login_failed_since=failed, started_ms=999)
    assert not seen
    profile.dir.mkdir()
    mark = profile.dir / LOGIN_MARK
    mark.touch()
    os.utime(mark, (100, 100))
    assert poster.ready(login_failed_since=failed, started_ms=999)
    assert seen == [("크롬", 100_000)]
    assert not poster.ready(login_failed_since=lambda *_: True, started_ms=999)


def test_ego_준비_여부는_서버_시작_이후_실패를_확인(tmp_path):
    poster = create_poster(Profile("이고", tmp_path / "missing", "ego"))
    seen = []

    def failed(name, since):
        seen.append((name, since))
        return False

    assert poster.ready(login_failed_since=failed, started_ms=1234)
    assert seen == [("이고", 1234)]
    assert not poster.ready(login_failed_since=lambda *_: True, started_ms=1234)


@pytest.mark.parametrize(
    "browser,driver", [("chrome", "agent.poster"), ("ego", "agent.poster_ego")]
)
@pytest.mark.parametrize("failure", [None, False, True])
def test_어댑터는_기존_게시_인자_결과_오류를_그대로_전달(
    browser, driver, failure, monkeypatch, tmp_path
):
    profile = Profile("테스트", tmp_path / "profile", browser)
    calls, statuses = [], []
    result = {
        "commentUrl": "https://www.youtube.com/watch?v=x&lc=one",
        "screenshot": "one.png",
    }
    error = PostError("확인 실패", "fail.png", submitted=bool(failure))

    async def fake_post(**kw):
        calls.append(kw)
        kw["on_status"]("입력 중")
        if failure is not None:
            raise error
        return result

    monkeypatch.setattr(importlib.import_module(driver), "post_comment", fake_post)
    poster = create_poster(profile)
    callback = statuses.append
    run = poster.post(
        video_id="allowedVid1", text="댓글", shot_dir=tmp_path, on_status=callback
    )
    if failure is None:
        assert asyncio.run(run) is result
    else:
        with pytest.raises(PostError) as caught:
            asyncio.run(run)
        assert caught.value is error
        assert (
            caught.value.submitted is failure and caught.value.screenshot == "fail.png"
        )
    assert statuses == ["입력 중"]
    assert calls == [
        {
            "profile_dir": profile.dir,
            "video_id": "allowedVid1",
            "text": "댓글",
            "shot_dir": tmp_path,
            "on_status": callback,
        }
    ]


def test_PostError_기존_import_경로_호환():
    from agent.poster import PostError as LegacyPostError

    assert LegacyPostError is PostError


def test_설정_팩터리_준비확인과_ego는_Playwright를_불러오지_않음():
    script = """
import sys
from pathlib import Path
from agent.config import Profile
from agent.browsers import create_poster
import agent.poster
import agent.poster_ego
for name in ('chrome', 'ego'):
    poster = create_poster(Profile('test', Path('/nonexistent-yt-test'), name))
    poster.ready(login_failed_since=lambda *_: False, started_ms=0)
assert not any(name == 'playwright' or name.startswith('playwright.') for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
