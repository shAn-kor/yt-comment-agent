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
    monkeypatch.setattr(
        youtube, "_tab_feed", lambda ch, limit: [{"videoId": "ccccccccccc"}]
    )
    assert youtube.fetch_channel_feed(CH) == [{"videoId": "ccccccccccc", "via": "tab"}]
    assert len(calls) == youtube.RSS_TRIES


def test_둘_다_실패하면_두_이유를_함께(rss, monkeypatch):
    rss([500])

    def broken(ch, limit):
        raise RuntimeError("yt-dlp 실패: 차단됨")

    monkeypatch.setattr(youtube, "_tab_feed", broken)
    with pytest.raises(
        RuntimeError,
        match="테스트 채널 목록 실패: RSS 3번 실패 \\(HTTP 500\\), yt-dlp 실패",
    ):
        youtube.fetch_channel_feed(CH)


def test_yt_dlp_오류는_읽을_수_있는_말로(monkeypatch):
    class Boom:
        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def extract_info(self, *_, **__):
            raise Exception("ERROR: [youtube] zzzzzzzzzzx: 이 동영상은 볼 수 없습니다.")

    monkeypatch.setattr("agent.youtube.YoutubeDL", Boom)
    with pytest.raises(RuntimeError) as e:
        youtube.get_video_context("zzzzzzzzzzx", comments=False)
    assert str(e.value) == "영상 정보를 가져오지 못함: 이 동영상은 볼 수 없습니다."


@pytest.mark.parametrize("transcript", ["", "안녕 강아지"])
def test_자막이_없거나_짧으면_장면을_읽음(monkeypatch, transcript):
    monkeypatch.setattr(
        youtube,
        "_extract",
        lambda *a, **k: {
            "id": "295yVVpRbmI",
            "title": "IMG 0978",
            "subtitles": {"ko": [{"ext": "json3", "url": "captions"}]},
        },
    )
    monkeypatch.setattr(youtube, "_fetch_transcript", lambda _: transcript)
    calls = []

    def scene(vid, info):
        calls.append(vid)
        return "흰 강아지가 풀밭을 걷는다.", "영상 화면·소리"

    monkeypatch.setattr(youtube, "extract_scene", scene)
    ctx = youtube.get_video_context("295yVVpRbmI", comments=False)
    assert calls == ["295yVVpRbmI"]
    assert ctx["scene"] == "흰 강아지가 풀밭을 걷는다."
    assert "영상 화면·소리" in ctx["sourceLabel"]
    assert ctx["transcript"] == transcript


def test_충분한_자막은_영상_다운로드_생략(monkeypatch):
    monkeypatch.setattr(
        youtube,
        "_extract",
        lambda *a, **k: {
            "id": "295yVVpRbmI",
            "subtitles": {"ko": [{"ext": "json3", "url": "caption"}]},
        },
    )
    monkeypatch.setattr(youtube, "_fetch_transcript", lambda _: "자막" * 50)
    monkeypatch.setattr(
        youtube, "extract_scene", lambda *a: pytest.fail("불필요한 영상 분석")
    )
    ctx = youtube.get_video_context("295yVVpRbmI", comments=False)
    assert ctx["scene"] == "" and ctx["sourceLabel"] == "자막"


def test_영상_분석_후_임시_파일_정리(monkeypatch):
    monkeypatch.setattr(youtube, "media_available", lambda **kw: True)
    paths, calls = [], []

    def download(vid, info, directory):
        path = directory / "video.mp4"
        path.write_bytes(b"video bytes")
        paths.append(path)
        return path

    def media(prompt, parts):
        calls.append(parts)
        return '{"scene": "흰 강아지가 풀밭을 걷는다."}'

    monkeypatch.setattr(youtube, "_download_scene_video", download)
    monkeypatch.setattr(youtube, "complete_media", media)
    assert youtube.extract_scene("295yVVpRbmI", {"duration": 10}) == (
        "흰 강아지가 풀밭을 걷는다.",
        "영상 화면·소리",
    )
    assert calls == [[("video/mp4", b"video bytes")]]
    assert not paths[0].parent.exists()


@pytest.mark.parametrize("failure", ["download", "api", "empty", "malformed"])
def test_영상_실패하면_썸네일과_출처_구분하고_파일_정리(monkeypatch, failure):
    monkeypatch.setattr(youtube, "media_available", lambda **kw: True)
    paths, prompts = [], []

    def download(vid, info, directory):
        paths.append(directory)
        (directory / "partial.mp4").write_bytes(b"partial")
        if failure == "download":
            raise ValueError("다운로드 실패")
        return directory / "partial.mp4"

    def media(prompt, parts):
        prompts.append(prompt)
        if parts[0][0] == "video/mp4":
            if failure == "api":
                raise RuntimeError("API 오류")
            return "[]" if failure == "malformed" else '{"scene": ""}'
        return '```json\n{"scene": "흰 강아지와 잔디가 보인다."}\n```'

    monkeypatch.setattr(youtube, "_download_scene_video", download)
    monkeypatch.setattr(youtube, "_thumbnail_bytes", lambda _: b"jpeg bytes")
    monkeypatch.setattr(youtube, "complete_media", media)
    assert youtube.extract_scene("295yVVpRbmI", {}) == (
        "흰 강아지와 잔디가 보인다.",
        "썸네일 화면 (영상·소리 미확인)",
    )
    assert not paths[0].exists()
    assert "소리·움직임·영상 전체 내용은 추측하지 마라" in prompts[-1]


def test_Gemini가_없어도_이미지_공급자가_있으면_썸네일(monkeypatch):
    monkeypatch.setattr(youtube, "media_available", lambda *, video=False: not video)
    monkeypatch.setattr(
        youtube, "_download_scene_video", lambda *a: pytest.fail("다운로드 금지")
    )
    monkeypatch.setattr(youtube, "_thumbnail_bytes", lambda _: b"jpeg")
    monkeypatch.setattr(
        youtube, "complete_media", lambda *a: '{"scene":"흰 강아지와 잔디가 보인다."}'
    )
    assert youtube.extract_scene("295yVVpRbmI", {})[1].startswith("썸네일")


def test_영상_이미지_모두_실패하면_빈_장면(monkeypatch):
    monkeypatch.setattr(youtube, "media_available", lambda **kw: True)

    def fail(*a):
        raise RuntimeError("사용 불가")

    monkeypatch.setattr(youtube, "_download_scene_video", fail)
    monkeypatch.setattr(youtube, "_thumbnail_bytes", fail)
    assert youtube.extract_scene("295yVVpRbmI", {}) == ("", "")


def test_이미지_키도_없으면_네트워크_없이_빈_장면(monkeypatch):
    monkeypatch.setattr(youtube, "media_available", lambda **kw: False)
    monkeypatch.setattr(
        youtube, "_thumbnail_bytes", lambda *a: pytest.fail("네트워크 금지")
    )
    assert youtube.extract_scene("295yVVpRbmI", {}) == ("", "")


@pytest.mark.parametrize(
    "info", [{"duration": 601}, {"duration": None}, {"duration": 10, "is_live": True}]
)
def test_길거나_길이를_모르는_영상은_다운로드_거절(monkeypatch, tmp_path, info):
    monkeypatch.setattr(youtube, "YoutubeDL", lambda *a: pytest.fail("다운로드 금지"))
    with pytest.raises(ValueError, match="길이"):
        youtube._download_scene_video("295yVVpRbmI", info, tmp_path)


def test_다운로드는_작은_MP4만_받고_크기_초과시_중단(monkeypatch, tmp_path):
    options = {}

    class Download:
        def __init__(self, opts):
            options.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def extract_info(self, url, download):
            assert download
            options["progress_hooks"][0](
                {"downloaded_bytes": youtube.SCENE_MAX_BYTES + 1}
            )

    monkeypatch.setattr(youtube, "YoutubeDL", Download)
    with pytest.raises(ValueError, match="크기 초과"):
        youtube._download_scene_video("295yVVpRbmI", {"duration": 5}, tmp_path)
    assert options["format"] == "worst[ext=mp4][vcodec!=none][acodec!=none]"
    assert options["max_filesize"] == youtube.SCENE_MAX_BYTES
    assert options["match_filter"]({"duration": 601})


def test_썸네일도_크기_제한(monkeypatch):
    class Thumbnail:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"x" * (youtube.THUMBNAIL_MAX_BYTES + 1)

    monkeypatch.setattr(youtube.httpx, "stream", lambda *a, **k: Thumbnail())
    with pytest.raises(ValueError, match="썸네일 크기 초과"):
        youtube._thumbnail_bytes("295yVVpRbmI")
