import pytest

from agent.validate import plural_hearsay, validate_comment

TEXT = "연락 빈도부터 줄인다는 말에 나도 기다릴 건가 싶음. 이 사람이랑 인연인지 궁금해짐. 주변에서 운명원 궁합 본 사람들 꽤 있던데 잘 맞힌다던데"


@pytest.mark.parametrize(
    "claim",
    [
        "잘 맞힌다던데",
        "맞힌대",
        "맞춘다던데",
        "맞춘다고 하더라",
        "맞췄다더라",
        "맞혔대",
        "잘 맞히는 곳이래",
        "잘 맞추나 봄",
        "용하다던데",
        "용하다고들 하더라",
        "용하댔음",
        "소름",
        "후기",
        "추천",
    ],
)
def test_R1_B3_ordinary_reported_efficacy_conjugations_fail(claim):
    text = TEXT.rsplit("잘 맞힌다던데", 1)[0] + claim
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
    assert plural_hearsay(text, "운명원") is False


def test_R1_B3_partner_fit_is_not_service_efficacy():
    text = "연락 빈도부터 줄인다는 말에 나도 멈칫함. 이 사람이 맞는지 궁금함. 주변에서 운명원 궁합 본 사람들 꽤 있던데"
    result = validate_comment(
        text,
        source="연락 빈도부터 줄",
        detail="연락 빈도부터 줄",
        brand="운명원",
        min=40,
        max=120,
    )
    assert result["ok"], result["errors"]


def test_R1_B3_conjugated_efficacy_is_never_exempted():
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
        next(check for check in result["checks"] if check["key"] == "fake")["ok"]
        is False
    )
