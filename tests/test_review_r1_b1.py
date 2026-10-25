from agent.generate import draft_comment
from agent.validate import validate_comment
from tests.test_generate import CTX, RULES, candidate_json

TEXT = "연락 빈도부터 줄인다는 말에 나도 기다릴 건가 싶음. 이 사람이랑 인연인지 궁금해짐. 운명원 궁합 궁금함"


def test_R1_B1_generation_cannot_accept_missing_social_proof():
    calls = []

    def llm(prompt):
        calls.append(str(prompt))
        return candidate_json({"detail": "연락 빈도부터 줄", "comment": TEXT})

    draft = draft_comment(CTX, **RULES, llm=llm)
    assert len(calls) == 3 and draft["validation"]["ok"] is False
    assert (
        next(
            check
            for check in draft["validation"]["checks"]
            if check["key"] == "hearsay"
        )["ok"]
        is False
    )


def test_R1_B1_requires_plural_social_proof():
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
        next(check for check in result["checks"] if check["key"] == "hearsay")["ok"]
        is False
    )
