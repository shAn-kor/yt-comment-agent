"""댓글 검증기. 생성된 초안과 사람이 고친 글 모두 게시 전에 여기를 통과해야 한다."""

import re
import unicodedata


def norm(s) -> str:
    """NFC로 맞추고 소문자로 바꾼 뒤 글자·숫자만 남긴다."""
    s = unicodedata.normalize("NFC", str(s or "")).lower()
    return "".join(c for c in s if c.isalnum())


def count_chars(s) -> int:
    return len(str(s or "").strip())


# 링크·해시태그 검사는 NFKC로 바꾼 글에 한다 (전각 ｗｗｗ．, ＃ 같은 글자도 잡는다)
LINK = re.compile(
    r"(https?://|www\."
    r"|[a-z0-9-]+\s*\.\s*[a-z]{2,6}(?![a-z])"  # 영문 도메인, 점 앞뒤 띄어쓰기 포함 (umw . com)
    r"|[a-z0-9가-힣-]+\.(한국|[a-z]{2,6}(?![a-z]))"  # 붙여 쓴 한글 도메인 (사주.한국, 운명.kr)
    r"|(닷|dot|쩜)\s*(컴|com|넷|net|kr|케이알)|(?<![가-힣])점\s*(com|net|kr)(?![a-z]))",  # 말로 쓴 도메인 (umw 닷 com)
    re.I,
)
HASHTAG = re.compile(r"#[^\s#]")
# 브랜드를 직접 이용해 본 것처럼 읽히는 표현 (브랜드가 들어간 문장에서만 검사)
FAKE_USE = re.compile(
    r"(봤는데|봤더니|봤어요|봤음|봤다|봤던|봤었|봤거든|받아\s?봤|받아\s?보니|받았는데|받았어|받고\s?왔"
    r"|보고\s?왔|해\s?봤|해봄|다녀왔|다녀옴|가\s?봤|갔었|갔는데|갔다|상담\s?받|맞더라|맞았|맞추더|용하더"
    r"|소름|후기|추천|강추)"
)
# 사주·점을 본 경험담. 브랜드가 없는 문장으로 떼어 써도 잡도록 글 전체에서 검사한다
FORTUNE_USE = re.compile(
    r"(사주|타로|궁합|신점|운세|철학관|상담)\S{0,4}\s?"
    r"(봤|받았|받아\s?봤|해\s?봤|보고\s?왔|다녀|맞더|맞았|맞췄|용하)"
)
# 한국어 댓글에 섞이면 안 되는 문자: 한자, 가나, 키릴, 태국·아랍·데바나가리 문자.
# 일부 무료 모델(Qwen 등)이 这段, 演 같은 한자를 섞어도 다른 검사는 통과했다
FOREIGN_SCRIPT = re.compile(
    "[\u0400-\u04ff\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f"
    "\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff"
    "\uf900-\ufaff\uff66-\uff9f\U00020000-\U0003ffff]"
)
ANCHOR_MIN = 5  # 인용구로 인정하는 최소 글자 수 (공백·문장부호 제외)
# 짝은 낱말 첫머리일 때만 인정한다 (반짝반짝·깜짝·짝짝 속 짝은 연애 맥락이 아니다)
BRAND_CONTEXT = re.compile(r"연애사주|사주|연애운|궁합|운세|(?<![가-힣])짝(?!짝)|인연")
BRAND_CONTEXT_DISTANCE = 40  # 앞 문장에 있는 맥락 표현 끝부터 브랜드까지
ENDING_SIMILARITY = 0.45  # 짧은 종결 문장의 어미만 바꾼 반복도 잡는다
REACTION = re.compile(
    r"(?<![가-힣])(?:나|내|저|제|우리)(?:는|도|가|만|를|랑|한테|에게|의)?(?![가-힣])"
    r"|(?<![가-힣])중(?![가-힣])|싶|있음\s*[?？]"
)
SENTENCE_END = ".!?…\n。！？"
STOCK_PHRASES = ("인연은 타이밍", "잘 본다던데", "유용하네요", "공감 100", "뜨끔했")
QUOTE_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
    ("«", "»"),
)


def _quoted_detail(text: str, detail: str, anchor: str) -> bool:
    targets = [
        norm(value) for value in (detail, anchor) if len(norm(value)) >= ANCHOR_MIN
    ]
    return any(
        target in norm(match[1])
        or len(longest_common(norm(match[1]), target)) >= ANCHOR_MIN
        for opening, closing in QUOTE_PAIRS
        for match in re.finditer(
            re.escape(opening) + r"([^\n]*?)" + re.escape(closing), text
        )
        for target in targets
    )


def _sentences(text: str) -> list[str]:
    return [
        s.strip()
        for s in re.findall(r"[^.!?…\n。！？]+(?:[.!?…\n。！？]+|$)", text)
        if s.strip(SENTENCE_END + " \t\r")
    ]


def _brand_sentence(text: str, brand: str) -> str:
    return " ".join(s for s in _sentences(text) if brand in s)


def _has_brand_context(text: str, brand: str) -> bool:
    if any(
        brand in sentence and BRAND_CONTEXT.search(sentence)
        for sentence in _sentences(text)
    ):
        return True
    return any(
        name.start() - context.end() <= BRAND_CONTEXT_DISTANCE
        for name in re.finditer(re.escape(brand), text)
        for context in BRAND_CONTEXT.finditer(text[: name.start()])
    )


def _brand_is_late(text: str, brand: str) -> bool:
    at = text.find(brand)
    sentences = _sentences(text)
    return bool(
        at > 0
        and text[:at].strip()
        and sentences
        and (brand in sentences[-1] or at >= len(text) * 0.65)
    )


def _bigrams(s) -> set[str]:
    n = norm(s)
    return {n[i : i + 2] for i in range(len(n) - 1)}


def similarity(a, b) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    return inter / (len(A) + len(B) - inter)


def longest_common(a: str, b: str) -> str:
    """a의 부분 문자열 중 b에도 있는 가장 긴 것"""
    best = ""
    for i in range(len(a)):
        j = i + len(best) + 1
        while j <= len(a) and a[i:j] in b:
            best = a[i:j]
            j += 1
    return best


def _locate(text: str, normalized: str) -> str:
    """정규화된 조각을 원문에서 다시 찾는다 (공백·문장부호를 건너뛰며). 미리보기 강조용."""
    if not normalized:
        return ""
    pattern = r"[\W_]*".join(re.escape(c) for c in normalized)
    m = re.search(pattern, unicodedata.normalize("NFC", text), re.I)
    return m[0] if m else ""


def validate_comment(
    comment,
    *,
    source: str = "",
    detail: str = "",
    brand: str = "운명원",
    min: int = 40,
    max: int = 120,
    previous: list[str] | None = None,
) -> dict:
    """source: 자막·장면·제목·설명을 합친 글. detail: 모델이 인용했다고 밝힌 영상 속 표현."""
    text = str(comment or "").strip()
    chars = count_chars(text)
    checks: list[dict] = []

    def add(key, label, ok, note=""):
        checks.append({"key": key, "label": label, "ok": bool(ok), "note": note})

    add(
        "length",
        f"{min}~{max}자",
        min <= chars <= max,
        f"글자 수 {chars}자 (기준 {min}~{max}자)",
    )

    n = text.count(brand)
    brand_note = (
        f'"{brand}"이(가) 없음'
        if n == 0
        else f'"{brand}"이(가) {n}번 나옴 (1번만)'
        if n > 1
        else ""
    )
    add("brand", f'"{brand}" 한 번', n == 1, brand_note)

    plain = unicodedata.normalize("NFKC", text)
    add(
        "brand_context",
        f"{brand}에 연애사주 맥락",
        n == 0 or _has_brand_context(plain, brand),
        f'"{brand}"과 같은 문장 또는 앞선 40자 이내에 연애사주·사주·연애운·궁합·운세·짝·인연 중 하나를 넣어 관심을 표현하세요 (이용 후기 금지)',
    )
    add(
        "brand_position",
        "브랜드는 끝부분에",
        n == 0 or _brand_is_late(plain, brand),
        "브랜드로 시작하지 말고 마지막 문장 또는 댓글의 뒤쪽 35%에 브랜드를 넣으세요",
    )
    reaction = any(
        REACTION.search(sentence)
        for sentence in _sentences(plain)
        if brand not in sentence
    )
    add(
        "reaction",
        "브랜드 앞에 시청자 반응",
        reaction,
        "브랜드가 없는 문장에 나·내·저·제·우리·중·싶·있음? 같은 시청자 반응을 넣으세요. 영상 주장만 되풀이하지 마세요",
    )
    link, tag = bool(LINK.search(plain)), bool(HASHTAG.search(plain))
    add(
        "link",
        "링크·해시태그 없음",
        not link and not tag,
        ", ".join(x for x in [link and "링크 금지", tag and "해시태그 금지"] if x),
    )

    fake = FORTUNE_USE.search(plain) or next(
        (
            m
            for s in re.split(r"[.!?…\n]+", plain)
            if brand in s and (m := FAKE_USE.search(s))
        ),
        None,
    )
    add(
        "fake",
        "이용 후기처럼 쓰지 않음",
        not fake,
        f'{brand}을(를) 이용해 본 것처럼 읽힘 ("{fake[0]}")' if fake else "",
    )

    foreign = "".join(dict.fromkeys(FOREIGN_SCRIPT.findall(text)))
    add(
        "script",
        "한글로만 씀",
        not foreign,
        f"한국어가 아닌 글자가 섞임 ({foreign[:10]})" if foreign else "",
    )

    stock = [phrase for phrase in STOCK_PHRASES if norm(phrase) in norm(plain)]
    add(
        "stock",
        "상투적인 홍보 문구 없음",
        not stock,
        f'상투적인 표현 "{", ".join(stock)}"을 빼고 영상의 구체적인 주장에 대한 입장을 직접 쓰세요'
        if stock
        else "",
    )

    # 영상 속 장면·말: 모델이 밝힌 인용구(5자 이상)가 원문과 댓글 모두에 있거나, 원문과 6자 이상 겹쳐야 한다.
    # detail은 화면이 보내는 값이라 "오늘은" 같은 흔한 짧은 말로는 통과하지 못하게 한다
    src = norm(source)
    body = norm(" ".join(text.split(brand)))
    d = norm(detail)
    anchor = ""
    if len(d) >= ANCHOR_MIN and d in src and d in body:
        anchor = _locate(text, d) or detail
    else:
        common = longest_common(body, src)
        if len(common) >= 6:
            anchor = _locate(text, common) or common
    anchor_note = (
        "영상 자료가 없어 장면 확인 불가"
        if not src
        else ""
        if anchor
        else "영상 속 장면·말이 댓글에 없음"
    )
    add("anchor", "영상 속 장면·말 포함", src and anchor, anchor_note)

    quoted = _quoted_detail(plain, detail, anchor)
    add(
        "quote",
        "영상 속 표현을 따옴표 없이 씀",
        not quoted,
        "영상 속 표현을 감싼 따옴표를 빼고 문장에 자연스럽게 섞으세요"
        if quoted
        else "",
    )

    dup = next((p for p in previous or [] if p and similarity(text, p) >= 0.5), None)
    add("unique", "이전 댓글과 다름", not dup, "이전 댓글과 너무 비슷함" if dup else "")
    ending = _brand_sentence(plain, brand).replace(brand, "")
    repeated_ending = next(
        (
            p
            for p in previous or []
            if ending
            and p
            and brand in p
            and similarity(
                ending,
                _brand_sentence(unicodedata.normalize("NFKC", p), brand).replace(
                    brand, ""
                ),
            )
            >= ENDING_SIMILARITY
        ),
        None,
    )
    add(
        "ending_unique",
        "브랜드 문장도 영상마다 다르게",
        not repeated_ending,
        "이전 댓글과 브랜드 문장이 너무 비슷합니다. 영상 고민에 맞춰 마지막 문장의 어휘와 구성을 바꾸세요"
        if repeated_ending
        else "",
    )

    errors = [c["note"] for c in checks if not c["ok"]]
    return {
        "ok": not errors,
        "errors": errors,
        "checks": checks,
        "chars": chars,
        "anchor": anchor,
    }
