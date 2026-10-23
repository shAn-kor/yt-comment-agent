"""Compare one-shot old/new drafts on real configured-channel videos. Never posts.

uv run python scripts/compare_voice.py --count 8 --contexts /path/to/contexts.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from agent.config import load_config, load_env
from agent.generate import build_prompt, parse_json, source_text, voice_comments
from agent.llm import backend_name, complete
from agent.validate import validate_comment
from agent.youtube import fetch_channel_feed, get_video_context
from scripts.voice_baseline import build_prompt as old_build_prompt

BASE_REVISION = "b53e4f7"
RESEARCH = Path.home() / "ai-workspace/scratch/comment-research"


def baseline_builder():
    """Use the frozen prompt, without its original generation/retry loop."""
    return old_build_prompt


def _has_video_material(ctx: dict) -> bool:
    return isinstance(ctx.get("description"), str) and any(
        isinstance(ctx.get(key), str) and ctx[key].strip()
        for key in ("transcript", "scene")
    )


def select_contexts(config, count: int, cache: Path | None = None) -> list[dict]:
    allowed = {channel.id for channel in config.channels}
    if cache is not None:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        groups = [
            [ctx for ctx in cached if ctx.get("channelId") == channel.id]
            for channel in config.channels
        ]
        candidates = [
            group[i]
            for i in range(max((len(g) for g in groups), default=0))
            for group in groups
            if i < len(group)
        ]
    else:
        feeds = [
            fetch_channel_feed(channel, limit=count) for channel in config.channels
        ]
        entries = [feed[i] for i in range(count) for feed in feeds if i < len(feed)][
            :count
        ]
        candidates = [get_video_context(entry["videoId"]) for entry in entries]
    selected, seen = [], set()
    for ctx in candidates:
        if ctx.get("channelId") not in allowed or ctx.get("videoId") in seen:
            continue
        seen.add(ctx["videoId"])
        if cache is not None and not _has_video_material(ctx):
            ctx = get_video_context(ctx["videoId"])
        if ctx.get("channelId") not in allowed or not _has_video_material(ctx):
            continue
        selected.append(dict(ctx))
        if len(selected) == count:
            break
    if len(selected) < count:
        raise ValueError(
            f"설정 채널의 실제 영상이 {len(selected)}개뿐임 (요청 {count}개)"
        )
    return selected


def attach_likes(contexts: list[dict], comments_file: Path | None) -> None:
    if comments_file is None or not comments_file.exists():
        return
    grouped = {}
    # JSON 문자열의 U+2028 등은 레코드 구분자가 아니다. 물리적인 줄만 나눈다.
    for line in comments_file.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        row = json.loads(line)
        grouped.setdefault(row["video_id"], []).append(
            {"text": row["text"], "likes": row.get("likes", 0)}
        )
    for ctx in contexts:
        if ctx["videoId"] in grouped:
            ctx["topComments"] = grouped[ctx["videoId"]]


def safe_error(error: Exception) -> str:
    text = str(error)
    for name, value in os.environ.items():
        if value and any(word in name for word in ("KEY", "TOKEN", "SECRET")):
            text = text.replace(value, "[REDACTED]")
    return f"{type(error).__name__}: {text}"


def md(text) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#+|])", r"\\\1", re.sub(r"\s+", " ", str(text)))


def save_sheet(output: Path, record: dict) -> None:
    lines = [
        "# 댓글 비교",
        "",
        "영상 내용에 맞고 광고 말투가 덜한 쪽을 고른다. 검증 결과와 버전 정보는 key.json에 따로 저장한다.",
        "각 초안은 단발 생성(single-shot)이며, 검사 결과를 붙여 다시 쓰는 재작성 루프는 사용하지 않았다. 영상 자료는 실제 자막 또는 장면 설명과 영상 설명을 포함한다.",
        "",
    ]
    recovered = sum(
        len(d.get("error_history", []))
        for row in record["rows"]
        for d in row["drafts"].values()
    )
    if recovered:
        lines += [
            f"응답을 받지 못한 오류 {recovered}건은 추가 요청했으며, 이력은 key.json에 보존했다.",
            "",
        ]
    for index, row in enumerate(record["rows"], 1):
        ref = row["reference"]
        lines += [
            f"## {index}. {md(row['title'])}",
            "",
            f"영상: `{row['videoId']}`",
            "",
            f"실제 최다 좋아요 댓글 ({ref['likes']}개, 최대 200자): {md(ref['text'])}",
            "",
        ]
        for label in ("A", "B"):
            result = row["drafts"].get(row["labels"][label])
            if result is None:
                lines += [f"### {label}", "", "(미생성)", ""]
            elif result.get("error"):
                lines += [f"### {label}", "", "(생성 실패)", ""]
            else:
                lines += [
                    f"### {label} · {result['chars']}자",
                    "",
                    md(result["comment"]) or "(초안 거절)",
                    "",
                ]
        lines += ["선택: A / B / 비슷함", ""]
    output.mkdir(parents=True, exist_ok=True)
    (output / "sheet.md").write_text("\n".join(lines), encoding="utf-8")
    temporary = output / "key.json.tmp"
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output / "key.json")


def compare(
    contexts,
    rules,
    output: Path,
    *,
    old_builder,
    llm=complete,
    seed=None,
    backend="",
    delay=0,
    sleep=time.sleep,
) -> dict:
    if (output / "key.json").exists() or (output / "sheet.md").exists():
        raise ValueError("비교 결과가 이미 있음. 다른 --output 폴더를 지정하세요")
    seed = random.SystemRandom().getrandbits(64) if seed is None else seed
    rng = random.Random(seed)
    record = {
        "baseline_revision": BASE_REVISION,
        "backend": backend,
        "seed": seed,
        "delay_seconds": delay,
        "stop_reason": "",
        "rows": [],
    }
    for ctx in contexts:
        versions = ["old", "new"]
        rng.shuffle(versions)
        refs = voice_comments(ctx.get("topComments", []), brand=rules.brand)
        record["rows"].append(
            {
                "videoId": ctx["videoId"],
                "title": ctx["title"],
                "reference": refs[0]
                if refs
                else {"text": "(필터 후 댓글 없음)", "likes": 0},
                "labels": dict(zip(("A", "B"), versions)),
                "drafts": {},
            }
        )
    save_sheet(output, record)
    generated = 0
    for ctx, row in zip(contexts, record["rows"]):
        versions = ["old", "new"]
        rng.shuffle(versions)  # generation order is independent of blind display order
        for version in versions:
            if generated and delay:
                sleep(delay)
            generated += 1
            print(f"generate {ctx['videoId']} {version}", flush=True)
            prompt_ctx = dict(ctx)
            if version == "old":
                # The frozen prompt expects strings and retains the original raw order.
                prompt_ctx["topComments"] = [
                    (str(c.get("text", "")) if isinstance(c, dict) else str(c))[:200]
                    for c in ctx.get("topComments", [])
                ][:20]
            builder = old_builder if version == "old" else build_prompt
            try:
                prompt = builder(
                    prompt_ctx, brand=rules.brand, min=rules.min, max=rules.max
                )
                parsed = parse_json(
                    llm(prompt)
                )  # exactly one generation, no validation-driven retries
                validation = validate_comment(
                    parsed["comment"],
                    source=source_text(ctx),
                    detail=parsed["detail"],
                    brand=rules.brand,
                    min=rules.min,
                    max=rules.max,
                )
                if not parsed["relevant"]:
                    validation["ok"] = False
                    validation["errors"].append("연애와 관련 없는 영상으로 초안 거절")
                row["drafts"][version] = {
                    **parsed,
                    "validation": validation,
                    "chars": validation["chars"],
                }
                print(
                    f"result {version}: {validation['chars']} chars, ok={validation['ok']}",
                    flush=True,
                )
            except (
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                OSError,
                httpx.HTTPError,
            ) as error:
                message = safe_error(error)
                row["drafts"][version] = {
                    "error": message,
                    "chars": 0,
                    "validation": {"ok": False, "errors": [message]},
                }
                print(message, flush=True)
                if re.search(
                    r"\b(?:429|503)\b|quota|한도 초과", message, re.IGNORECASE
                ):
                    record["stop_reason"] = message
            save_sheet(output, record)
            if record["stop_reason"]:
                return record
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument(
        "--contexts", type=Path, help="cached get_video_context JSON list"
    )
    parser.add_argument("--comments", type=Path, default=RESEARCH / "comments.jsonl")
    parser.add_argument("--output", type=Path, default=RESEARCH / "blind")
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help="seconds between generations (65 for Groq TPM limits)",
    )
    args = parser.parse_args(argv)
    if args.count < 1 or args.delay < 0:
        parser.error("--count must be positive and --delay nonnegative")
    if (args.output / "key.json").exists() or (args.output / "sheet.md").exists():
        print("비교 결과가 이미 있음. 다른 --output 폴더를 지정하세요", flush=True)
        return 1
    load_env()
    config = load_config()
    try:
        contexts = select_contexts(config, args.count, args.contexts)
        attach_likes(contexts, args.comments)
        result = compare(
            contexts,
            config.comment,
            args.output,
            old_builder=baseline_builder(),
            seed=args.seed,
            backend=backend_name(),
            delay=args.delay,
        )
    except (
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        httpx.HTTPError,
    ) as error:
        print(safe_error(error), flush=True)
        return 1
    print(f"sheet: {args.output / 'sheet.md'}", flush=True)
    print(f"key: {args.output / 'key.json'}", flush=True)
    failed = any(
        draft.get("error") for row in result["rows"] for draft in row["drafts"].values()
    )
    return 2 if result["stop_reason"] else 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
