import pytest

from agent.validate import validate_comment

OPTS = dict(
    source="연락 빈도부터 줄",
    detail="연락 빈도부터 줄",
    brand="운명원",
    min=40,
    max=120,
)


def check(result, key):
    return next(c for c in result["checks"] if c["key"] == key)["ok"]


@pytest.mark.parametrize(
    "text",
    [
        # 오려나: 끝맺음만 다른 개인적 바람
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 내 인연은 언제쯤 오려나. 주변에서 운명원 궁합 본 사람들 꽤 있던데",
        # 맞춘다: 브랜드 앞 내 상황 문장의 동사는 효과 주장이 아님
        "연락 빈도부터 줄이라는데 나만 늘 시간을 맞춘다는 게 지침. 이 사람이랑 인연인지 궁금함. 주변에서 운명원 궁합 본 사람들 꽤 있던데",
        # 대조군
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 내 인연은 언제 올지 모르겠음. 주변에서 운명원 궁합 본 사람들 꽤 있던데",
        # 얘기하는 사람 여럿: 복수 표현이 뒤에 오는 어순
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 이 사람이랑 인연인지 궁금함. 운명원 연애사주 얘기하는 사람 여럿 있던데",
    ],
)
def test_R2_legitimate_personal_wish_comments_pass(text):
    result = validate_comment(text, **OPTS)
    assert result["ok"] is True, result["errors"]


def test_R2_wish_about_people_in_the_video_is_not_personal():
    text = "연락 빈도부터 줄이라는 말에 나도 멈칫함. 영상 속 두 사람이 인연인지 궁금함. 주변에서 운명원 궁합 본 사람들 꽤 있던데"
    result = validate_comment(text, **OPTS)
    assert result["ok"] is False
    assert check(result, "wish_bridge") is False


@pytest.mark.parametrize(
    "text",
    [
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 이 사람이랑 인연인지 궁금함. 주변에서 운명원 궁합 본 사람들 꽤 있던데 소름이래",
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 이 사람이랑 인연인지 궁금함. 주변에서 운명원 궁합 본 사람들 꽤 있던데. 다들 잘 맞춘대",
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 이 사람이랑 인연인지 궁금한데 다들 잘 맞춘대. 주변에서 운명원 궁합 본 사람들 꽤 있던데",
    ],
)
def test_R2_efficacy_in_or_after_the_brand_sentence_is_still_rejected(text):
    result = validate_comment(text, **OPTS)
    assert result["ok"] is False
    assert check(result, "fake") is False
