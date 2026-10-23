"""ego 브라우저 게시: 설정 읽기, 준비 여부, 스크립트 만들기, 결과 줄 해석. 실제 브라우저는 열지 않는다."""

import asyncio
import json
import time

import pytest

from agent import poster_ego, server
from agent.browsers.port import PostError
from agent.config import Profile, load_config
from agent.store import Store


def test_설정에서_browser_ego를_읽음(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text(
        "profiles:\n  - { name: 이고, browser: ego }\n  - { name: 크롬, dir: ./p }\n",
        encoding="utf-8",
    )
    assert [p.browser for p in load_config(f).profiles] == ["ego", "chrome"]


def test_ego_프로필은_로그인_표시_없이_준비됨_로그인_실패하면_해제(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        server.config, "profiles", [Profile("이고", tmp_path / "none", "ego")]
    )
    monkeypatch.setattr(server, "store", Store(tmp_path / "t.db"))
    assert server.profile_ready("이고")
    server.store.add(
        {"profile": "이고", "status": "failed", "reason": "로그인 안 됨 — …"},
        now=time.time() + 1,
    )
    assert not server.profile_ready("이고")


def test_글의_따옴표와_줄바꿈이_스크립트를_깨지_않음(tmp_path):
    text = '운명원에서 "그 말" 봤는데\n`${x}` </script> \\ 끝'
    js = poster_ego.build_script("OaviuM_8qQ4", text, tmp_path, "1")
    line = next(ln for ln in js.splitlines() if ln.startswith("const A = "))
    args = json.loads(line[len("const A = ") : -1])
    assert args["text"] == text
    assert args["videoId"] == "OaviuM_8qQ4"
    assert "__ARGS__" not in js


def test_결과_줄만_골라_읽음():
    assert poster_ego.parse_line('@@status "입력 중"') == ("status", "입력 중")
    assert poster_ego.parse_line('@@result {"href": "/watch?v=x&lc=y"}') == (
        "result",
        {"href": "/watch?v=x&lc=y"},
    )
    assert poster_ego.parse_line("[ego-browser:notice] 업데이트") is None
    assert poster_ego.parse_line("@@status {깨진") is None


class FakeProc:
    def __init__(self, lines):
        self.stdout = self._gen(lines)
        self.stdin = self
        self.returncode = 0

    async def _gen(self, lines):
        for ln in lines:
            yield (ln + "\n").encode()

    def write(self, _):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait(self):
        return 0

    def kill(self):
        pass


def run_with(monkeypatch, tmp_path, lines):
    monkeypatch.setattr(poster_ego.shutil, "which", lambda _: "/bin/ego")

    async def fake_exec(*a, **k):
        return FakeProc(lines)

    monkeypatch.setattr(poster_ego.asyncio, "create_subprocess_exec", fake_exec)
    seen = []
    coro = poster_ego.post_comment(
        video_id="OaviuM_8qQ4", text="글", shot_dir=tmp_path, on_status=seen.append
    )
    return asyncio.run(coro), seen


def test_성공하면_댓글_주소를_돌려줌(monkeypatch, tmp_path):
    out, seen = run_with(
        monkeypatch,
        tmp_path,
        [
            '@@status "입력 중"',
            '@@result {"href": "/watch?v=OaviuM_8qQ4&lc=abc", "screenshot": "s.png"}',
        ],
    )
    assert out == {
        "commentUrl": "https://www.youtube.com/watch?v=OaviuM_8qQ4&lc=abc",
        "screenshot": "s.png",
    }
    assert "입력 중" in seen


def test_게시를_누른_뒤_실패는_submitted(monkeypatch, tmp_path):
    with pytest.raises(PostError) as e:
        run_with(
            monkeypatch,
            tmp_path,
            [
                '@@status "내 댓글 확인 중"',
                '@@error {"message": "게시 후 내 댓글이 보이지 않음", "submitted": true}',
            ],
        )
    assert e.value.submitted


def test_결과_없이_끝나면_마지막_출력을_알림(monkeypatch, tmp_path):
    with pytest.raises(PostError, match="ego 브라우저 실행 실패: 연결 거부"):
        run_with(monkeypatch, tmp_path, ["연결 거부"])


def test_상태_파일의_줄을_진행_중에_읽음(monkeypatch, tmp_path):
    # ego 실행기는 화면 출력을 끝날 때 몰아서 내보내므로, 진행 상태는 스크립트가 쓰는 파일에서 읽는다
    monkeypatch.setattr(poster_ego.shutil, "which", lambda _: "/bin/ego")
    box = {}

    class FileProc(FakeProc):
        def write(self, data):
            js = data.decode()
            line = next(ln for ln in js.splitlines() if ln.startswith("const A = "))
            box["file"] = json.loads(line[len("const A = ") : -1])["statusFile"]

        async def _gen(self, lines):
            from pathlib import Path

            f = Path(box["file"])
            f.write_text('@@status "입력 중"\n', encoding="utf-8")
            await asyncio.sleep(0.5)
            box["seen_before_end"] = list(seen)
            with f.open("a", encoding="utf-8") as h:
                h.write('@@result {"href": null, "screenshot": "s.png"}\n')
            yield b"\n"

    async def fake_exec(*a, **k):
        return FileProc([])

    monkeypatch.setattr(poster_ego.asyncio, "create_subprocess_exec", fake_exec)
    seen = []
    out = asyncio.run(
        poster_ego.post_comment(
            video_id="OaviuM_8qQ4", text="글", shot_dir=tmp_path, on_status=seen.append
        )
    )
    assert "입력 중" in box["seen_before_end"]
    assert out["screenshot"] == "s.png"
    assert seen.count("입력 중") == 1
