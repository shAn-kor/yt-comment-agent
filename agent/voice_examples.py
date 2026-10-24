"""User-approved voice references, not factual sources for another video."""

VOICE_EXAMPLES = (
    {
        "videoId": "k_0c0m0Hk5k",
        "detail": "혼자 서운해",
        "comment": "기대한 모습이랑 다를 때 서운해진다는 말 듣고 할 말 없어짐. 혼자 그림 그리고 혼자 서운해한 게 나였네… 이 사람이랑 맞긴 한 건지 궁금해짐. 주변에서 운명원 궁합 보고 왔다는 사람 몇 명 있던데 나도 가 볼까",
    },
    {
        "videoId": "FE0YQTSqFuo",
        "detail": "자기 세계가 있어야",
        "comment": "자기 세계가 있어야 한다는 말 맞는 듯. 연애할 때마다 내 생활부터 줄였던 게 문제였나 봄. 다음엔 진짜 맞는 사람이 언제 오는지나 알고 싶다. 요즘 주변에서 운명원 연애사주 얘기 많이 하던데",
    },
    {
        "videoId": "Fje_-CmUoJU",
        "detail": "먼저 연락 없으면",
        "comment": "먼저 연락 없으면 접으라는데 그게 되면 이 영상 안 봤지ㅋㅋ 결국 이 사람이랑 인연인지가 문제임. 주변에서 운명원 궁합 본 사람들 꽤 있던데 나도 한번 볼까",
    },
    {
        "videoId": "hpEnIwoH_sw",
        "detail": "상황 따라 달라진다는",
        "comment": "상황 따라 달라진다는 말 듣고 그 사람 이해하려다 또 기다리는 중. 결국 우리 궁합 문제 아닌가 싶어서 연애사주 한번 보고 싶어짐. 주변에서 운명원 다녀왔다는 사람 여럿 있던데",
    },
    {
        "videoId": "xkSmLCEBvFI",
        "detail": "내 생활 다 포기했던",
        "comment": "잘해 주려다 내 생활 다 포기했던 거 생각나서 좀 씁쓸함. 다음엔 궁합 맞는 사람 만나고 싶은데 그게 언제일지… 주변에서 운명원 연애사주 보러 간 사람 몇 명 있던데 나도 알아봐야겠음",
    },
)

GOLD_IDS = frozenset(example["videoId"] for example in VOICE_EXAMPLES)


def examples_for(video_id: str) -> tuple[dict, ...]:
    """Never show the exact video's approved answer while drafting that video."""
    return tuple(
        example for example in VOICE_EXAMPLES if example["videoId"] != video_id
    )
