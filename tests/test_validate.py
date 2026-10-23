import pytest

from agent.validate import count_chars, similarity, validate_comment

SOURCE = "남자가 연락을 줄이는 진짜 이유. 남자는 확신이 없으면 연락 빈도부터 줄입니다. 읽씹은 관심이 식었다는 신호일 수 있어요."
GOOD = (
    "확신이 없으면 연락 빈도부터 줄인다는 말 듣고 나도 맨날 기다릴 건가 싶음. "
    "운명원에서 내 인연은 언제 오는지 궁금하다"
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
        "brand_context",
        "link",
        "fake",
        "script",
        "stock",
        "anchor",
        "quote",
        "unique",
    ]


def test_글자_수_범위():
    assert "글자 수" in errors("운명원 궁금하다")
    assert "글자 수" in errors(GOOD + GOOD)
    assert count_chars("ㅠㅠ 가나") == 5


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
    ],
)
def test_브랜드_앞뒤_같은_문장_15자_이내_맥락이면_통과(text):
    v = validate_comment(text, **OPTS)
    assert next(c for c in v["checks"] if c["key"] == "brand_context")["ok"]


@pytest.mark.parametrize(
    "text",
    [
        "운명원도 궁금해지네요",
        "연애사주가 궁금하다. 운명원은 어떨까",
        "운명원도 궁금하네! 인연도 궁금해",
        "사주가 궁금하다\n운명원도 궁금하다",
        "운명원 이름은 반짝반짝 예뻐서 어떤 곳인지 궁금해요",
        "운명원 얘기에 깜짝 놀랐어요",
        "짝짝 박수 치고 운명원도 궁금해요",
        "운명원" + "가" * 16 + "궁합",
        "사주" + "가" * 16 + "운명원",
    ],
)
def test_브랜드_맥락_없거나_다른_문장_멀리_있으면_차단(text):
    v = validate_comment(text, **OPTS)
    check = next(c for c in v["checks"] if c["key"] == "brand_context")
    assert not check["ok"]
    assert "같은 문장" in check["note"] and "15자 이내" in check["note"]
    assert "관심을 표현" in check["note"] and check["note"] in v["errors"]


def test_브랜드_이름만_있으면_맥락_오류로_안내():
    text = GOOD.replace(
        "운명원에서 내 인연은 언제 오는지 궁금하다",
        "운명원도 궁금해지네요",
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
    text = "연락 빈도부터 줄면 그냥 마음 없는 거 아닌가. 내 쪽은 운명원 가서 궁합이나 볼까 싶다"
    assert errors(text) == ""
    assert "상투적인 표현" not in errors(GOOD + " 공감은 가지만 내 생각은 좀 다름")
    assert "따옴표를 빼고" not in errors(GOOD + " ‘나’부터 생각할 일")


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
