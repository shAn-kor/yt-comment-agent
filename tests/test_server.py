"""API가 화면(app.js)이 기대하는 모양으로 답하고, 게시 전에 규칙을 서버에서 막는지 확인한다.
네트워크 없이 돌도록 영상 자료와 기록 저장소를 바꿔 끼운다."""

import pytest
from fastapi.testclient import TestClient

from agent import server
from agent.store import Store
from tests.test_validate import GOOD, SOURCE

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


def test_고친_글_다시_검사(client):
    v = client.post(
        "/api/validate",
        json={"videoId": "allowedVid1", "comment": GOOD, "detail": "연락 빈도부터 줄"},
    ).json()
    assert v["ok"] and len(v["checks"]) == 6


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


def test_검사에_떨어진_글은_게시_차단(client):
    r = client.post(
        "/api/post", json={"videoId": "allowedVid1", "comment": "짧음", "detail": ""}
    )
    assert r.status_code == 422
    assert server.store.list()[0]["reason"].startswith("검증 실패")


def test_화면_밖_경로_차단(client):
    for path in ("/shots/%2e%2e/%2e%2e/config.yaml", "/%2e%2e/config.yaml", "/shots/..%2f..%2fconfig.yaml"):
        r = client.get(path)
        assert r.status_code == 404 and "posting_scope" not in r.text, path
