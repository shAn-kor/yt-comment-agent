"""API가 화면(app.js)이 기대하는 모양으로 답하고, 게시 전에 규칙을 서버에서 막는지 확인한다.
네트워크 없이 돌도록 영상 자료와 기록 저장소를 바꿔 끼운다."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from agent import server
from agent.browsers.port import PostError
from agent.config import Profile
from agent.generate import draft_comment
from agent.store import Store
from tests.test_validate import GOOD, SOURCE
from tests.test_generate import candidate_json

ALLOWED = server.config.channels[0].id


def ctx(video_id, channel_id):
    return {
        "videoId": video_id,
        "title": "남자가 연락을 줄이는 진짜 이유",
        "description": "",
        "transcript": SOURCE,
        "sourceLabel": "자막",
        "channelId": channel_id,
        "channelName": "원래 이름",
        "views": 10,
        "timestamp": None,
        "topComments": [],
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", Store(tmp_path / "t.db"))
    monkeypatch.setattr(
        server,
        "contexts",
        {
            "allowedVid1": ctx("allowedVid1", ALLOWED),
            "outsideVid1": ctx("outsideVid1", "UCother"),
        },
    )
    return TestClient(server.app, base_url="http://localhost")


def test_설정과_화면_파일(client):
    c = client.get("/api/config").json()
    assert (
        c["postingScope"] == "test_only"
        and c["dailyMax"] == 10
        and c["comment"]["brand"] == "운명원"
    )
    assert "댓글 에이전트" in client.get("/").text


def test_허용_밖_링크는_차단하고_기록(client):
    r = client.post("/api/resolve", json={"url": "https://youtu.be/outsideVid1"})
    assert r.status_code == 403 and "허용 범위 밖" in r.json()["error"]
    assert server.store.list()[0]["status"] == "blocked"


def test_허용_채널_링크는_설정의_채널_이름으로(client):
    r = client.post("/api/resolve", json={"url": "https://youtu.be/allowedVid1"})
    assert r.json()["video"]["channelName"] == server.config.channels[0].name


def test_내용_없는_영상은_대시보드에_명확한_오류(client, monkeypatch):
    monkeypatch.setattr(server, "session_drafts", [])
    server.contexts["allowedVid1"].update(
        title="IMG 0978", description="", transcript="", scene=""
    )
    r = client.post("/api/draft", json={"videoId": "allowedVid1"})
    assert r.status_code == 422
    assert r.json() == {"error": "영상 내용을 파악하지 못해 초안을 만들지 않음"}
    assert not server.session_drafts


def test_연애와_무관한_영상은_초안_없이_대시보드에_오류(client, monkeypatch):
    monkeypatch.setattr(server, "session_drafts", [])
    server.contexts["allowedVid1"].update(
        title="IMG 0978", transcript="", scene="흰 강아지가 풀밭을 걷는다."
    )
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        return json.dumps({"relevant": False})

    monkeypatch.setattr(
        server,
        "draft_comment",
        lambda ctx, **kw: draft_comment(ctx, **kw, llm=fake_llm),
    )
    response = client.post("/api/draft", json={"videoId": "allowedVid1"})
    assert response.status_code == 422
    assert response.json() == {
        "error": "연애 고민과 관련 없는 영상이라 운명원 연결이 억지스러움 — 게시 비추천"
    }
    assert len(calls) == 1 and not server.session_drafts
    assert "comment" not in response.json()
    assert not server.store.list()


def test_초안_API는_선택한_입장도_반환(client, monkeypatch):
    monkeypatch.setattr(server, "session_drafts", [])
    monkeypatch.setattr(
        server,
        "draft_comment",
        lambda ctx, **kw: draft_comment(
            ctx,
            **kw,
            llm=lambda _: candidate_json(
                {
                    "relevant": True,
                    "stance": "한줄요약",
                    "bridge": "계속 기다려도 될까?",
                    "concern": "연락 고민",
                    "detail": "연락 빈도부터 줄",
                    "comment": GOOD,
                }
            ),
        ),
    )
    r = client.post("/api/draft", json={"videoId": "allowedVid1"})
    assert r.status_code == 200 and r.json()["stance"] == "한줄요약"
    assert r.json()["bridge"] == "계속 기다려도 될까?"
    assert r.json()["selected_index"] == 0 and len(r.json()["candidates"]) == 4


def test_고친_글_다시_검사(client):
    v = client.post(
        "/api/validate",
        json={"videoId": "allowedVid1", "comment": GOOD, "detail": "연락 빈도부터 줄"},
    ).json()
    assert v["ok"] and len(v["checks"]) == 18


def test_테스트_모드면_지정_채널에도_게시_차단(client):
    r = client.post(
        "/api/post",
        json={"videoId": "allowedVid1", "comment": GOOD, "detail": "연락 빈도부터 줄"},
    )
    assert r.status_code == 403 and "테스트 모드" in r.json()["error"]
    state = client.get("/api/post-state", params={"videoId": "allowedVid1"}).json()
    assert [c["key"] for c in state["checks"]] == [
        "scope",
        "once",
        "quota",
    ] and not state["ok"]


def test_검사에_떨어진_글은_게시_차단(client, monkeypatch):
    monkeypatch.setattr(server.config, "test_videos", ["allowedVid1"])
    monkeypatch.setattr(server, "profile_ready", lambda _: True)
    r = client.post(
        "/api/post", json={"videoId": "allowedVid1", "comment": "짧음", "detail": ""}
    )
    assert r.status_code == 422
    assert server.store.list()[0]["reason"].startswith("검증 실패")


def test_브랜드_맥락_없는_수정_댓글은_게시_전에_차단(client, monkeypatch):
    monkeypatch.setattr(server.config, "test_videos", ["allowedVid1"])
    monkeypatch.setattr(server, "profile_ready", lambda _: True)
    text = GOOD.replace(
        "운명원에서 내 인연은 언제 오는지 궁금하다",
        "운명원도 궁금해지네요",
    )
    r = client.post(
        "/api/post",
        json={"videoId": "allowedVid1", "comment": text, "detail": "연락 빈도부터 줄"},
    )
    assert r.status_code == 422
    assert "40자 이내" in r.json()["error"]
    assert server.store.list()[0]["status"] == "blocked"


def test_허용_밖_영상은_글이_틀려도_범위_이유로_차단(client, monkeypatch):
    monkeypatch.setattr(server, "profile_ready", lambda _: True)
    r = client.post(
        "/api/post", json={"videoId": "outsideVid1", "comment": "짧음", "detail": ""}
    )
    assert r.status_code == 403 and r.json()["error"] == "허용 범위 밖 채널"
    assert server.store.list()[0]["reason"] == "허용 범위 밖 채널"


@pytest.mark.parametrize("ready", [False, True])
def test_profile_ready는_주입한_어댑터에_위임(ready, monkeypatch, tmp_path):
    profile = Profile("가짜", tmp_path / "unused", "test-adapter")
    monkeypatch.setattr(server.config, "profiles", [profile])
    calls = []

    class FakePoster:
        def ready(self, **kw):
            calls.append(kw)
            return ready

    def factory(p):
        assert p is profile
        return FakePoster()

    monkeypatch.setattr(server.app.state, "poster_factory", factory)
    assert server.profile_ready("가짜") is ready
    assert calls == [
        {
            "login_failed_since": server.store.login_failed_since,
            "started_ms": server.STARTED_MS,
        }
    ]
    assert not server.profile_ready("없는 프로필")
    assert len(calls) == 1


@pytest.mark.parametrize("submitted", [None, False, True])
def test_서버는_팩터리에_주입한_가짜_게시자를_사용(
    client, monkeypatch, tmp_path, submitted
):
    profile = Profile("가짜", tmp_path / "unused", "test-adapter")
    monkeypatch.setattr(server.config, "profiles", [profile])
    monkeypatch.setattr(server.config, "test_videos", ["allowedVid1"])
    monkeypatch.setattr(server, "busy", False)
    monkeypatch.setattr(server, "jobs", {})
    monkeypatch.setattr(server, "SHOTS", tmp_path / "shots")
    calls = []

    class FakePoster:
        def ready(self, **kw):
            return True

        async def post(self, **kw):
            calls.append(kw)
            kw["on_status"]("입력 중")
            assert next(iter(server.jobs.values()))["status"] == "입력 중"
            if submitted is not None:
                raise PostError("테스트 실패", "fake.png", submitted=submitted)
            return {
                "commentUrl": "https://www.youtube.com/watch?v=allowedVid1&lc=fake",
                "screenshot": "fake.png",
            }

    poster = FakePoster()

    def factory(p):
        assert p is profile
        return poster

    monkeypatch.setattr(server.app.state, "poster_factory", factory)
    with client:
        response = client.post(
            "/api/post",
            json={
                "videoId": "allowedVid1",
                "comment": GOOD,
                "detail": "연락 빈도부터 줄",
            },
        )
        assert response.status_code == 200
        assert response.json()["profile"] == "가짜"
        for _ in range(50):
            job = client.get("/api/job", params={"id": response.json()["jobId"]}).json()
            if job["done"]:
                break
            time.sleep(0.01)
    assert job["done"] and not server.busy
    assert len(calls) == 1
    assert {k: v for k, v in calls[0].items() if k != "on_status"} == {
        "video_id": "allowedVid1",
        "text": GOOD,
        "shot_dir": tmp_path / "shots",
    }
    row = server.store.list()[0]
    assert row["screenshot"] == "fake.png"
    if submitted is None:
        assert job["ok"] and job["status"] == "게시 완료"
        assert row["status"] == "success" and row["comment_url"].endswith("lc=fake")
    else:
        assert not job["ok"] and job["unverified"] is submitted
        assert row["status"] == ("unverified" if submitted else "failed")


def test_화면_밖_경로_차단(client):
    for path in (
        "/shots/%2e%2e/%2e%2e/config.yaml",
        "/%2e%2e/config.yaml",
        "/shots/..%2f..%2fconfig.yaml",
    ):
        r = client.get(path)
        assert r.status_code == 404 and "posting_scope" not in r.text, path
