from agent.youtube import parse_video_id


def test_영상_링크_파싱():
    assert parse_video_id("https://youtu.be/akn-AvCeHBI") == "akn-AvCeHBI"
    assert (
        parse_video_id("https://www.youtube.com/watch?v=JjY09DSdzx0&t=3")
        == "JjY09DSdzx0"
    )
    assert parse_video_id("https://www.youtube.com/shorts/DvxMfC_KjX0") == "DvxMfC_KjX0"
    assert parse_video_id("JjY09DSdzx0") == "JjY09DSdzx0"
    assert parse_video_id("https://example.com/watch?v=xx") is None


from types import SimpleNamespace

import httpx
import pytest

from agent import youtube
from agent.config import Channel

CH = Channel(id="UCtest", name="테스트 채널")
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry><yt:videoId>aaaaaaaaaaa</yt:videoId><title>Live streaming of 테스트</title><published>2026-10-19T01:00:00+00:00</published></entry>
 <entry><yt:videoId>bbbbbbbbbbb</yt:videoId><title>연락이 줄어든 이유 &amp; 해법</title><published>2026-10-18T08:30:08+00:00</published>
  <media:group><media:community><media:statistics views="1234"/></media:community></media:group></entry>
</feed>""".encode()


@pytest.fixture
def rss(monkeypatch):
    """RSS 응답 순서를 정해 두고, 요청 횟수를 센다"""
    monkeypatch.setattr(youtube, "RSS_WAIT", 0)
    calls = []

    def answer(codes):
        def get(url, **kw):
            code = codes[len(calls)] if len(calls) < len(codes) else codes[-1]
            calls.append(code)
            if code == "timeout":
                raise httpx.ConnectTimeout("timeout")
            return SimpleNamespace(status_code=code, content=FEED)

        monkeypatch.setattr(youtube.httpx, "get", get)
        return calls

    return answer


def test_RSS_목록은_정확한_시각과_라이브_제외(rss):
    rss([200])
    [v] = youtube.fetch_channel_feed(CH)
    assert v["via"] == "rss" and v["videoId"] == "bbbbbbbbbbb"
    assert v["title"] == "연락이 줄어든 이유 & 해법"
    assert v["published"] == "2026-10-18T08:30:08Z" and v["views"] == 1234


def test_RSS가_가끔_실패하면_다시_요청(rss):
    calls = rss([500, "timeout", 200])
    assert youtube.fetch_channel_feed(CH)[0]["via"] == "rss"
    assert calls == [500, "timeout", 200]


def test_RSS가_계속_실패하면_동영상_탭으로(rss, monkeypatch):
    calls = rss([404])
    monkeypatch.setattr(youtube, "_tab_feed", lambda ch, limit: [{"videoId": "ccccccccccc"}])
    assert youtube.fetch_channel_feed(CH) == [{"videoId": "ccccccccccc", "via": "tab"}]
    assert len(calls) == youtube.RSS_TRIES


def test_둘_다_실패하면_두_이유를_함께(rss, monkeypatch):
    rss([500])

    def broken(ch, limit):
        raise RuntimeError("yt-dlp 실패: 차단됨")

    monkeypatch.setattr(youtube, "_tab_feed", broken)
    with pytest.raises(RuntimeError, match="테스트 채널 목록 실패: RSS 3번 실패 \\(HTTP 500\\), yt-dlp 실패"):
        youtube.fetch_channel_feed(CH)
