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
