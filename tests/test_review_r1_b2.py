import pytest

from agent.validate import validate_comment

TEXT = "연락 빈도부터 줄이라는 말에 나도 멈칫함. 주변에서 운명원 인연 얘기 많이 하던데"


@pytest.mark.parametrize(
    "text",
    [
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 주변에서 인연이 언제 올지 운명원 얘기 많이 하던데",
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 주변에서 운명원 얘기 많이 하던데 내 인연은 언제일지 궁금함",
        "연락 빈도부터 줄이라는 말에 나도 멈칫함. 인연은 타이밍이라는 말도 기억남. 주변에서 운명원 궁합 얘기 많이 하던데",
    ],
)
def test_R1_B2_incidental_or_after_brand_words_are_not_own_wish(text):
    result = validate_comment(
        text,
        source="연락 빈도부터 줄",
        detail="연락 빈도부터 줄",
        brand="운명원",
        min=40,
        max=120,
    )
    assert result["ok"] is False
    assert (
        next(check for check in result["checks"] if check["key"] == "wish_bridge")["ok"]
        is False
    )


def test_R1_B2_same_sentence_personal_wish_before_hearsay_passes():
    text = "연락 빈도부터 줄이라는 말에 나도 멈칫함. 이 사람이 맞는지 궁금해서 주변에서 운명원 사주 보고 왔다는 사람 몇 명 있던데"
    result = validate_comment(
        text,
        source="연락 빈도부터 줄",
        detail="연락 빈도부터 줄",
        brand="운명원",
        min=40,
        max=120,
    )
    assert result["ok"], result["errors"]


def test_R1_B2_brand_hearsay_cannot_supply_personal_wish():
    result = validate_comment(
        TEXT,
        source="연락 빈도부터 줄",
        detail="연락 빈도부터 줄",
        brand="운명원",
        min=40,
        max=120,
    )
    assert result["ok"] is False
    assert (
        next(check for check in result["checks"] if check["key"] == "wish_bridge")["ok"]
        is False
    )
