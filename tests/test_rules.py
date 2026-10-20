from dataclasses import replace
from datetime import datetime, timezone

from agent.config import Channel, Config, Limits, Profile
from agent.rules import check_load_scope, check_post, kst_date, pick_profile
from agent.store import Store

BASE = Config(
    profiles=[Profile("유튜브1", None), Profile("유튜브2", None)],
    channels=[Channel("UCallowed", "허용 채널")],
    test_videos=["testVideo01"],
    posting_scope="test_only",
    limits=Limits(daily_max=2),
)
CHANNEL_VIDEO = {"videoId": "chanVideo01", "channelId": "UCallowed"}
TEST_VIDEO = {"videoId": "testVideo01", "channelId": "UCmine"}
OUTSIDE = {"videoId": "otherVid001", "channelId": "UCother"}


class EmptyStore:
    def has_success(self, _):
        return False

    def count_success_on(self, _):
        return 0


def test_불러오기_범위는_지정_채널과_테스트_영상만():
    assert check_load_scope(CHANNEL_VIDEO, BASE)["ok"]
    assert check_load_scope(TEST_VIDEO, BASE)["ok"]
    assert not check_load_scope(OUTSIDE, BASE)["ok"]


def test_테스트_모드에서는_테스트_영상에만_게시():
    assert check_post(TEST_VIDEO, "유튜브1", BASE, EmptyStore())["ok"]
    assert (
        "테스트 모드"
        in check_post(CHANNEL_VIDEO, "유튜브1", BASE, EmptyStore())["reason"]
    )
    open_ = replace(BASE, posting_scope="channels")
    assert check_post(CHANNEL_VIDEO, "유튜브1", open_, EmptyStore())["ok"]
    assert not check_post(OUTSIDE, "유튜브1", open_, EmptyStore())["ok"]


def test_설정에_없는_프로필_차단():
    assert "프로필" in check_post(TEST_VIDEO, "유튜브9", BASE, EmptyStore())["reason"]


def test_영상당_1개와_하루_상한은_SQLite_기록_기준(tmp_path):
    store = Store(tmp_path / "t.db")
    cfg = replace(BASE, test_videos=["testVideo01", "testVideo02", "testVideo03"])
    v = lambda i: {"videoId": f"testVideo0{i}"}
    store.add({"videoId": "testVideo01", "profile": "유튜브1", "status": "success"})
    assert "영상당 1개" in check_post(v(1), "유튜브2", cfg, store)["reason"]
    store.add({"videoId": "testVideo02", "profile": "유튜브1", "status": "failed"})
    assert check_post(v(2), "유튜브1", cfg, store)["ok"]
    store.add({"videoId": "testVideo02", "profile": "유튜브1", "status": "success"})
    assert "상한" in check_post(v(3), "유튜브1", cfg, store)["reason"]
    # 다음 날에는 다시 가능
    tomorrow = datetime.now().timestamp() + 24 * 3600
    assert check_post(v(3), "유튜브1", cfg, store, now=tomorrow)["ok"]


def test_비교용_이전_댓글은_같은_영상을_뺀다(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add({"videoId": "a", "comment": "A 댓글", "status": "success"})
    store.add({"videoId": "b", "comment": "B 댓글", "status": "success"})
    assert store.previous_comments(30, "a") == ["B 댓글"]


def test_자동_배정은_가장_오래_안_쓴_프로필():
    used = {"유튜브1": 200, "유튜브2": 100}
    assert pick_profile(BASE, lambda n: used.get(n, 0)) == "유튜브2"


def test_한국_시간_날짜():
    assert (
        kst_date(datetime(2026, 10, 19, 15, 30, tzinfo=timezone.utc).timestamp())
        == "2026-10-20"
    )
