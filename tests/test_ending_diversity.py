import json
from itertools import combinations
from pathlib import Path

import pytest

from agent.validate import (
    WISH_ENDING_SIMILARITY,
    plural_hearsay,
    validate_comment,
    wish_ending_similarity,
)
from tests.test_bridge2 import checked

FINAL1 = json.loads(
    (Path(__file__).parent / "fixtures/final1_endings.json").read_text()
)["endings"]
DISTINCT = (
    "나도 기다리는 중. 언제쯤 될지 궁금함. 주변에서 운명원 사주 보고 온 사람들 꽤 있더라",
    "내 생활은 그대로 지키고 싶음. 이번엔 다를지 궁금함. 요즘 주변에서 운명원 연애사주 얘기 많이 하던데",
    "나는 괜히 급해지나 봄. 결국 타이밍인지 알고 싶다. 주변에서 운명원 궁합 본 사람들 얘기가 들리더라",
    "나만 연락 기다리게 됨. 다시 이어질지 궁금함. 운명원 사주 보러 간 사람 몇 명 얘길 들었음",
    "나도 기준을 놓쳤나 싶음. 이 사람이 맞는지 알고 싶다. 주변에서 운명원 궁합 얘기하는 사람 여럿 있던데",
)


@pytest.mark.parametrize(
    "suffix",
    [
        "주변에 운명원 궁합 본 사람들 꽤 있더라",
        "주변에서 운명원 궁합 본 사람들 꽤 있다더라",
        "주변에 운명원 궁합 본 사람들 얘기가 들리더라",
        "주변에서 운명원 궁합 보고 온 사람들 꽤 있더라",
        "주변에서 운명원 궁합 보고 온 사람들 꽤 있다더라",
        "요즘 주변에서 운명원 연애사주 얘기하는 사람 여럿 있던데",
        "요즘 주변에 운명원 연애사주 얘기가 많이 들리더라",
    ],
)
def test_복수전언의_일상적인_문법_변형도_인정(suffix):
    assert plural_hearsay(suffix, "운명원")
    result = checked(suffix)
    assert result["ok"], result["errors"]


@pytest.mark.parametrize("left,right", list(combinations(FINAL1, 2)))
def test_final1의_같은_바람과_사회적증거_틀은_모두_반복(left, right):
    assert plural_hearsay(left, "운명원") and plural_hearsay(right, "운명원")
    assert wish_ending_similarity(left, right, "운명원") >= WISH_ENDING_SIMILARITY
    result = validate_comment(
        left,
        source=left,
        detail=left[:12],
        brand="운명원",
        min=0,
        max=1000,
        previous=[right],
    )
    assert not next(
        check for check in result["checks"] if check["key"] == "ending_unique"
    )["ok"]


@pytest.mark.parametrize("left,right", list(combinations(DISTINCT, 2)))
def test_서로_다른_바람과_전언은_실제로_통과(left, right):
    assert wish_ending_similarity(left, right, "운명원") < WISH_ENDING_SIMILARITY
    result = validate_comment(
        left,
        source=left,
        detail=left[:12],
        brand="운명원",
        min=40,
        max=120,
        previous=[right],
    )
    assert result["ok"], result["errors"]


def test_전언의_문법을_넓혀도_직접이용과_효능은_예외_없음():
    for suffix in (
        "나는 운명원 궁합 봤는데 주변에 보고 온 사람들 꽤 있더라",
        "주변에 운명원 궁합 보고 온 사람들 꽤 있더라 맞췄대",
    ):
        result = checked(suffix)
        assert not next(check for check in result["checks"] if check["key"] == "fake")[
            "ok"
        ]
