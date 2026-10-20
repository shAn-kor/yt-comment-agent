"""레드팀 검토(2026-10-20)에서 찾은 우회 방법이 막히는지 확인한다.
각 테스트는 고치기 전 코드에서 실제로 통과(우회)되던 사례다."""

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from agent import server
from agent.config import LOGIN_MARK, Profile
from agent.poster import PostError
from agent.rules import check_post, pick_profile
from agent.store import Store
from agent.validate import validate_comment
from agent.youtube import get_video_context, parse_video_id
from tests.test_rules import BASE, TEST_VIDEO, EmptyStore
from tests.test_server import ALLOWED, ctx
from tests.test_validate import GOOD, OPTS, errors

TEST_ID = "myTestVid01"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", Store(tmp_path / "t.db"))
    monkeypatch.setattr(
        server,
        "contexts",
        {TEST_ID: ctx(TEST_ID, "UCmine"), "allowedVid1": ctx("allowedVid1", ALLOWED)},
    )
    monkeypatch.setattr(server.config, "test_videos", [TEST_ID])
    monkeypatch.setattr(server, "busy", False)
    return TestClient(server.app, base_url="http://localhost")


# ── 검증기 우회 ─────────────────────────────────────


@pytest.mark.parametrize(
    "tail",
    [
        "운명원 궁금하신 분은 ｕｍｗ．ｃｏｍ 에서 찾아보세요",  # 전각 링크
        "운명원 궁금하신 분은 umw 닷 com 검색",  # 말로 쓴 링크
        "운명원 궁금하신 분은 umw . com 검색",  # 점 앞뒤 띄어쓰기
        "운명원 궁금하신 분은 사주보기.한국 검색",  # 한글 도메인
    ],
)
def test_모양을_바꾼_링크도_차단(tail):
    assert "링크" in errors(GOOD.split("운명원")[0] + tail)


def test_전각_해시태그도_차단():
    assert "해시태그" in errors(GOOD.replace("궁금하다", "궁금 ＃연애사주"))


@pytest.mark.parametrize(
    "text",
    [
        # 경험담을 브랜드가 없는 문장으로 떼어 씀
        "확신이 없으면 연락 빈도부터 줄인다는 말 공감. 어제 사주 봤는데 진짜 맞더라. 운명원 궁금하다 다들",
        # 목록에 없던 경험 표현
        "확신이 없으면 연락 빈도부터 줄인다는 말 듣고 작년에 운명원에서 해봤던 연애 사주가 떠올랐다",
        # 이용자처럼 추천
        "확신이 없으면 연락 빈도부터 줄인다는 말 진짜 공감ㅠㅠ 운명원 연애사주 강추해요 다들 꼭 보세요",
    ],
)
def test_후기처럼_쓰는_우회_차단(text):
    assert "이용해 본 것처럼" in errors(text)


def test_평범한_문장은_링크로_오인하지_않음():
    for s in (
        "그래요. 한국 남자들은 다 그런가",
        "맞아요.저도 그랬어요",
        "점점 컴컴해지는 밤",
    ):
        text = GOOD.replace("나도 맨날", s + " 나도 맨날")
        assert validate_comment(text, **OPTS)["ok"], errors(text)


def test_흔한_짧은_인용구로는_장면_검사_통과_못함():
    src = "오늘은 남자친구가 연락을 안 하는 이유를 이야기합니다"
    text = "오늘은 저도 마음이 좀 그래서 끝까지 봤네요 ㅠㅠ 운명원에서 연애 사주 한번 보고 싶어지는 밤이에요"
    assert not validate_comment(text, **{**OPTS, "source": src, "detail": "오늘은"})[
        "ok"
    ]


# ── 영상당 1개 우회 (영상 ID 변형) ──────────────────


def test_영상_ID_변형은_받지_않음(client):
    for vid in (TEST_ID + "&t=1", "가나다라마바사아자차카", "../../../x"):
        assert (
            client.post("/api/post", json={"videoId": vid, "comment": GOOD}).status_code
            == 422
        )
        assert client.get("/api/post-state", params={"videoId": vid}).status_code == 422
    assert parse_video_id("https://www.youtube.com/watch?v=abcdefghijk%26t=1") is None
    assert parse_video_id("https://evilyoutube.com/watch?v=abcdefghijk") is None


def test_yt_dlp가_다른_영상을_돌려주면_거부(monkeypatch):
    monkeypatch.setattr("agent.youtube._extract", lambda *a, **k: {"id": "otherVideo1"})
    with pytest.raises(RuntimeError, match="다름"):
        get_video_context("abcdefghijk", comments=False)


# ── 다른 웹사이트의 요청 (DNS 리바인딩) ────────────


def test_다른_주소로_온_요청_차단(client):
    assert (
        client.get("/api/logs", headers={"Host": "evil.example:4310"}).status_code
        == 403
    )
    r = client.post(
        "/api/validate",
        json={"videoId": TEST_ID},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert (
        client.get("/api/logs", headers={"Origin": "http://localhost:4310"}).status_code
        == 200
    )


# ── 게시 후 확인 실패 ───────────────────────────────


def test_확인_안_된_게시도_영상당_1개와_상한에_셈(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add(
        {"videoId": TEST_VIDEO["videoId"], "profile": "유튜브1", "status": "unverified"}
    )
    assert "영상당 1개" in check_post(TEST_VIDEO, "유튜브1", BASE, store)["reason"]
    assert (
        store.count_success_on(
            time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))
        )
        == 1
    )


def test_게시_버튼_뒤_실패는_확인_안_됨으로_기록(client, monkeypatch):
    async def fake_post(**_):
        raise PostError("게시 후 내 댓글이 보이지 않음", None, submitted=True)

    monkeypatch.setattr("agent.poster.post_comment", fake_post)
    monkeypatch.setattr(server, "profile_ready", lambda _: True)
    job_id = client.post(
        "/api/post",
        json={"videoId": TEST_ID, "comment": GOOD, "detail": "연락 빈도부터 줄"},
    ).json()["jobId"]
    for _ in range(50):
        job = client.get("/api/job", params={"id": job_id}).json()
        if job["done"]:
            break
        time.sleep(0.02)
    assert job["unverified"] and not job["ok"]
    assert server.store.list()[0]["status"] == "unverified"
    state = client.get("/api/post-state", params={"videoId": TEST_ID}).json()
    assert "영상당 1개" in state["reason"]


# ── 로그인 안 된 프로필 ─────────────────────────────


def test_자동_배정은_로그인된_프로필만():
    used = {"유튜브1": 200}
    assert (
        pick_profile(BASE, lambda n: used.get(n, 0), lambda n: n == "유튜브1")
        == "유튜브1"
    )
    assert pick_profile(BASE, lambda n: 0, lambda n: False) is None
    assert (
        "로그인된 프로필이 없음"
        in check_post(TEST_VIDEO, None, BASE, EmptyStore())["reason"]
    )
    assert (
        "로그인 필요"
        in check_post(TEST_VIDEO, "유튜브2", BASE, EmptyStore(), ready=lambda _: False)[
            "reason"
        ]
    )


def test_로그인_표시와_로그인_실패_기록으로_준비_여부(tmp_path, monkeypatch):
    p = Profile("유튜브1", tmp_path / "p1")
    monkeypatch.setattr(server.config, "profiles", [p])
    monkeypatch.setattr(server, "store", Store(tmp_path / "t.db"))
    assert not server.profile_ready("유튜브1")  # login.py를 안 돌림
    p.dir.mkdir()
    (p.dir / LOGIN_MARK).touch()
    assert server.profile_ready("유튜브1")
    server.store.add(
        {"profile": "유튜브1", "status": "failed", "reason": "로그인 안 됨 — …"},
        now=time.time() + 1,
    )
    assert not server.profile_ready("유튜브1")  # 로그인 표시 뒤에 로그인 실패


def test_없는_프로필_폴더로는_Chrome을_열지_않음(tmp_path):
    from agent.poster import post_comment

    missing = tmp_path / "none"
    with pytest.raises(PostError, match="로그인 안 됨"):
        asyncio.run(
            post_comment(
                profile_dir=missing, video_id=TEST_ID, text="x", shot_dir=tmp_path
            )
        )
    assert not missing.exists()


# ── 동시에 두 번 누르기 ─────────────────────────────


def test_동시_게시_요청은_하나만_검사로_들어감(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", Store(tmp_path / "t.db"))
    monkeypatch.setattr(
        server, "contexts", {}
    )  # 서버를 막 켠 상태: 영상 자료를 받는 동안 await
    monkeypatch.setattr(server, "busy", False)

    def slow(video_id):
        time.sleep(0.2)
        return ctx(video_id, "UCmine")

    monkeypatch.setattr(server, "get_video_context", slow)

    async def run():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as c:
            body = {"videoId": TEST_ID, "comment": "짧음"}
            return await asyncio.gather(
                c.post("/api/post", json=body), c.post("/api/post", json=body)
            )

    codes = sorted(r.status_code for r in asyncio.run(run()))
    assert codes == [
        409,
        422,
    ]  # 하나는 검사에서 떨어지고, 하나는 "게시하는 중"으로 거절
    assert server.busy is False
