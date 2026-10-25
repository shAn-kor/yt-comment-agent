import pytest

from agent.validate import validate_comment

TEXT = "연락 빈도부터 줄인다는 말에 나도 멈칫함. 나도 언제 인연이 올지 궁금해서 주변에서 운명원 사주 보고 왔다는 사람 몇 명 있던데"


def test_R1_W1_personal_wish_is_not_the_reported_usage_subject():
    result = validate_comment(
        TEXT,
        source="연락 빈도부터 줄",
        detail="연락 빈도부터 줄",
        brand="운명원",
        min=40,
        max=120,
    )
    assert result["ok"] is True, result["errors"]
    assert (
        next(check for check in result["checks"] if check["key"] == "fake")["ok"]
        is True
    )


@pytest.mark.parametrize(
    "usage",
    [
        "나 운명원 사주 보고 왔는데, 주변에서 보고 왔다는 사람 몇 명 있던데",
        "주변에서 내가 운명원 사주 보고 왔다는 사람 몇 명 있던데",
        "나는 운명원 사주 받아봤음. 주변에서 다녀왔다는 사람 여럿 있던데",
        "주변에서 나도 운명원 다녀왔다는 사람 여럿 있던데",
    ],
)
def test_R1_W1_actual_self_usage_is_still_rejected(usage):
    text = (
        "연락 빈도부터 줄인다는 말에 나도 멈칫함. 내 인연은 언제일지 궁금함. " + usage
    )
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
        next(check for check in result["checks"] if check["key"] == "fake")["ok"]
        is False
    )
