import pytest

from agent.validate import ENDING_SIMILARITY, count_chars, similarity, validate_comment

SOURCE = "남자가 연락을 줄이는 진짜 이유. 남자는 확신이 없으면 연락 빈도부터 줄입니다. 읽씹은 관심이 식었다는 신호일 수 있어요."
GOOD = (
    "확신이 없으면 연락 빈도부터 줄인다는 말 듣고 나도 맨날 기다릴 건가 싶음. "
    "내 인연은 언제 오는지 궁금하다. 주변에서 운명원 궁합 본 사람들 꽤 있던데"
)
OPTS = dict(source=SOURCE, detail="연락 빈도부터 줄", brand="운명원", min=40, max=120)


def errors(text, **kw):
    return ", ".join(validate_comment(text, **{**OPTS, **kw})["errors"])


def test_조건을_다_지키면_통과():
    v = validate_comment(GOOD, **OPTS)
    assert v["ok"], v["errors"]
    assert v["anchor"]
    assert [c["key"] for c in v["checks"]] == [
        "length",
        "brand",
        "counseling",
        "questions",
        "brand_context",
        "brand_position",
        "wish_bridge",
        "single_source",
        "hearsay",
        "reaction",
        "link",
        "fake",
        "script",
        "stock",
        "anchor",
        "quote",
        "unique",
        "ending_unique",
    ]


def test_글자_수_범위():
    assert "글자 수" in errors("운명원 궁금하다")
    assert "글자 수" in errors(GOOD + GOOD)
    assert count_chars("ㅠㅠ 가나") == 5


@pytest.mark.parametrize(
    "marks,allowed",
    [
        ("", True),
        ("?", True),
        ("？", True),
        ("??", False),
        ("?？", False),
        ("？？", False),
    ],
)
def test_물음표는_전각까지_합쳐_최대_하나(marks, allowed):
    v = validate_comment(GOOD + marks, **OPTS)
    check = next(c for c in v["checks"] if c["key"] == "questions")
    assert check["ok"] is allowed
    if not allowed:
        assert "질문은 하나만" in check["note"] and check["note"] in v["errors"]


def test_브랜드는_정확히_한_번():
    assert "없음" in errors(GOOD.replace("운명원", "그곳"))
    assert "2번" in errors(GOOD.replace("궁금하다", "운명원 궁금하다"))


@pytest.mark.parametrize(
    "text",
    [
        "운명원 연애사주가 궁금하다",
        "연애운은 운명원에서 보고 싶다",
        "운명원에서 궁합 한번 보고 싶다",
        "사주를 잘 본다는 운명원이 궁금하다",
        "운명원 운세가 궁금하다",
        "운명원에서 내 짝은 언제 만날지 궁금하다",
        "짝을 언제 만날지 운명원에 물어보고 싶다",
        "운명원에서 짝사랑 고민도 들어줄까",
        "인연이 궁금해서 운명원을 찾아보고 싶다",
        "운명원" + "가" * 15 + "궁합",
        "사주" + "가" * 15 + "운명원",
        "연애사주가 궁금하다. 운명원은 어떨까",
        "사주가 궁금하다\n운명원도 궁금하다",
        "운명원" + "가" * 16 + "궁합",
        "사주" + "가" * 16 + "운명원",
        "사주." + "가" * 39 + "운명원",  # 단어 끝부터 40자
    ],
)
def test_같은_문장이나_앞선_40자_맥락이면_통과(text):
    v = validate_comment(text, **OPTS)
    assert next(c for c in v["checks"] if c["key"] == "brand_context")["ok"]


@pytest.mark.parametrize(
    "text",
    [
        "운명원도 궁금해지네요",
        "운명원도 궁금하네! 인연도 궁금해",
        "운명원 이름은 반짝반짝 예뻐서 어떤 곳인지 궁금해요",
        "운명원 얘기에 깜짝 놀랐어요",
        "짝짝 박수 치고 운명원도 궁금해요",
        "사주." + "가" * 40 + "운명원",  # 앞선 문장은 41자부터 거절
    ],
)
def test_브랜드_맥락_없거나_앞선_맥락이_멀리_있으면_차단(text):
    v = validate_comment(text, **OPTS)
    check = next(c for c in v["checks"] if c["key"] == "brand_context")
    assert not check["ok"]
    assert "같은 문장" in check["note"] and "40자 이내" in check["note"]
    assert "관심을 표현" in check["note"] and check["note"] in v["errors"]


def test_브랜드_이름만_있으면_맥락_오류로_안내():
    text = (
        "확신이 없으면 연락 빈도부터 줄인다는 말에 나도 멈칫함. 운명원도 궁금해지네요"
    )
    assert "연애사주·사주·연애운" in errors(text)


def test_맥락이_있어도_사주_이용_후기는_차단():
    assert "이용해 본 것처럼" in errors(
        GOOD.replace("내 인연은 언제 오는지 궁금하다", "사주 봤는데 맞더라")
    )


def test_링크와_해시태그_금지():
    assert "링크" in errors(GOOD.replace("궁금하다", "unmyeong.com 궁금"))
    assert "해시태그" in errors(GOOD.replace("궁금하다", "#연애사주"))


def test_운명원_이용_후기처럼_쓰면_차단():
    fake = GOOD.replace(
        "내 인연은 언제 오는지 궁금하다", "사주 받아봤는데 진짜 소름 돋게 맞더라"
    )
    assert "이용해 본 것처럼" in errors(fake)


def test_브랜드_없는_문장의_봤는데는_허용():
    watched = GOOD.replace("말 듣고", "말 영상으로 봤는데")
    assert validate_comment(watched, **OPTS)["ok"], errors(watched)


def test_영상_속_표현이_없으면_차단():
    generic = "연애는 정말 어렵다ㅠㅠ 나만 이렇게 힘든가 싶어서 오늘도 한숨만 쉬었다. 운명원 연애사주 잘 본다던데 나도 언젠가 꼭 한번 보고 싶다"
    assert "장면" in errors(generic, detail="없는 말")


@pytest.mark.parametrize(
    "phrase",
    [
        "인연은 타이밍",
        "잘 본다던데",
        "유용하네요",
        "공감 100%",
        "뜨끔했어요",
        "잘  본다던데",
        "공감 １００",
    ],
)
def test_상투적인_홍보_표현은_수정_이유와_함께_차단(phrase):
    assert "상투적인 표현" in errors(GOOD + " " + phrase)
    assert "입장을 직접" in errors(GOOD + " " + phrase)


@pytest.mark.parametrize(
    "opening,closing",
    [("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”"), ("「", "」"), ("『", "』")],
)
def test_detail을_따옴표로_감싸면_차단(opening, closing):
    text = GOOD.replace("연락 빈도부터 줄", opening + "연락 빈도부터 줄" + closing)
    assert "따옴표를 빼고" in errors(text)
    assert "따옴표를 빼고" in errors(
        text, detail=""
    )  # 사람이 고친 글도 근거 조각으로 검사


def test_detail이_포함된_긴_인용문도_차단():
    text = GOOD.replace(
        "확신이 없으면 연락 빈도부터 줄인다는 말",
        "‘확신이 없으면 연락 빈도부터 줄인다는 말’",
    )
    assert "따옴표를 빼고" in errors(text)


def test_입장과_자연스러운_근거_표현은_허용():
    text = "나만 연락 빈도부터 줄면 마음 없는 거라고 생각함? 내 인연은 언제 올지 궁금함. 주변에서 운명원 궁합 본 사람들 꽤 있던데"
    assert errors(text) == ""
    assert "상투적인 표현" not in errors(GOOD + " 공감은 가지만 내 생각은 좀 다름")
    assert "따옴표를 빼고" not in errors(GOOD + " ‘나’부터 생각할 일")


def rule(text, key, **kw):
    return next(
        c for c in validate_comment(text, **{**OPTS, **kw})["checks"] if c["key"] == key
    )


def test_사용자_예시와_다른_시청자에게_사주_경험_질문은_통과():
    text = "상황 따라 달라진다는 말 듣고 그 사람 이해하려다 또 기다리는 중. 우리 궁합 문제인지 사주 본 사람 있음? 주변에서 운명원 궁합 본 사람들 꽤 있던데"
    v = validate_comment(
        text,
        source="상황 따라 달라진다는 말",
        detail="상황 따라 달라진다는",
        min=40,
        max=120,
    )
    assert v["ok"], v["errors"]
    assert (
        rule(text.replace("사주 본 사람 있음?", "사주 봤는데 맞더라."), "fake")["ok"]
        is False
    )


@pytest.mark.parametrize(
    "text",
    [
        "나도 기다리는 중. 궁합이나 알아볼까. 운명원이란 곳 얘기가 있던데",
        "나도 " + "가" * 70 + ". 운명원 궁합은 어떰? 다들 궁금함?",
    ],
)
def test_브랜드가_마지막_문장이나_뒤쪽_35퍼센트면_허용(text):
    assert rule(text, "brand_position")["ok"]


@pytest.mark.parametrize(
    "text",
    [
        "운명원 궁합을 알아볼까. 나도 연락이 줄어서 기다리는 중.",
        "나도 고민 중. 운명원 사주 궁금함. " + "다른 생각이 이어진다" * 7 + ".",
    ],
)
def test_브랜드로_시작하거나_앞쪽_중간에_끼우면_차단(text):
    check = rule(text, "brand_position")
    assert not check["ok"] and "뒤쪽 35%" in check["note"]


@pytest.mark.parametrize(
    "reaction",
    [
        "나도 기다린다",
        "내가 더 궁금하다",
        "저도 헷갈린다",
        "제 생각은 다르다",
        "우리 문제 같다",
        "기다리는 중",
        "더 알고 싶다",
        "비슷한 사람 있음?",
    ],
)
def test_브랜드_밖의_시청자_반응을_허용(reaction):
    assert rule(reaction + ". 운명원 사주 얘기 있던데", "reaction")["ok"]


@pytest.mark.parametrize(
    "reaction",
    [
        "연락 빈도부터 줄면 마음 없는 거다",
        "자기 일에 집중하는 게 중요하다",
        "하나만 기억하면 된다",
        "제목이 내용을 요약한다",
    ],
)
def test_주장만_되풀이하거나_다른_단어_속_표현은_반응이_아님(reaction):
    check = rule(reaction + ". 운명원에서 내 궁합을 보고 싶다", "reaction")
    assert not check["ok"] and "브랜드가 없는 문장" in check["note"]


def test_반응이_브랜드_문장에만_있으면_차단():
    assert not rule("운명원에서 나도 내 궁합을 보고 싶다", "reaction")["ok"]


@pytest.mark.parametrize(
    "first,second",
    [
        ("내 쪽은 운명원에 가서 궁합이라도 볼까", "내 쪽은 운명원 가서 궁합이나 볼까"),
        ("운명원이란 곳이 괜찮아 보이던데", "운명원이란 데가 괜찮아 보이던데"),
    ],
)
def test_문장_전체가_달라도_어미만_바꾼_브랜드_끝문장은_차단(first, second):
    assert (
        similarity(first.replace("운명원", ""), second.replace("운명원", ""))
        >= ENDING_SIMILARITY
    )
    current = "연락 빈도부터 줄어드니 나도 기다리기 싫음. " + first
    previous = "표정은 웃는데 약속은 비워두니 내 쪽이 지침. " + second
    assert rule(current, "unique", previous=[previous])["ok"]
    check = rule(current, "ending_unique", previous=[previous])
    assert not check["ok"] and "어휘와 구성" in check["note"]


def test_브랜드만_같고_다른_종결_문장은_허용():
    first, second = "운명원이란 곳이 괜찮아 보이던데", "운명원 얘기 많던데"
    assert (
        similarity(first.replace("운명원", ""), second.replace("운명원", ""))
        < ENDING_SIMILARITY
    )
    assert rule(
        "나도 궁합은 궁금함. " + first,
        "ending_unique",
        previous=["다들 사주 본 사람 있음? " + second],
    )["ok"]


def test_이전_댓글과_비슷하면_차단():
    assert "비슷" in errors(GOOD, previous=[GOOD.replace("궁금하다", "궁금함")])
    assert similarity("가나다라", "마바사아") < 0.1


def test_강조할_부분은_원문_그대로():
    v = validate_comment(GOOD, **OPTS)
    assert v["anchor"] in GOOD


def test_한자_가나_등_다른_문자가_섞이면_실패():
    assert "한국어가 아닌 글자가 섞임 (这段)" in errors(
        GOOD.replace("나도", "这段 나도")
    )
    assert "섞임" in errors(GOOD.replace("나도", "나도 ほんと"))
    assert "섞임" in errors(GOOD.replace("나도", "나도 ﾎﾝﾄ"))  # 반각 가나
    assert "섞임" in errors(GOOD.replace("나도", "나도 правда"))
    # 영문·숫자·이모지·자모는 괜찮다
    assert errors(GOOD.replace("나도", "나도 ok 2번 ㅋㅋ 😭")) == ""
