"""Prepare transcript-only, non-gold contexts through the application's readers."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import load_config, load_env
from agent.voice_examples import GOLD_IDS
from agent.youtube import fetch_channel_feed, get_video_context

CACHED_IDS = ("c5vYhdNbkdk", "c-QzU4kuu90", "_KG56fTIBFM")
ROMANCE = re.compile(r"연애|사랑|썸|이별|재회|남자친구|여자친구|커플|연인")


def prepare(
    config,
    cached,
    *,
    fetch=get_video_context,
    feed=fetch_channel_feed,
    fresh_limit=5,
    max_fetches=12,
):
    allowed = {channel.id for channel in config.channels}
    by_id = {ctx["videoId"]: ctx for ctx in cached}
    contexts = [by_id[video_id] for video_id in CACHED_IDS]
    if any(
        ctx.get("channelId") not in allowed
        or not ctx.get("transcript", "").strip()
        or not ctx.get("description", "").strip()
        for ctx in contexts
    ):
        raise ValueError("캐시 홀드아웃의 채널·자막·설명 확인 필요")
    seen = set(by_id) | GOLD_IDS
    groups, events = [], []
    if fresh_limit == 0 or max_fetches == 0:
        return contexts, events
    for channel in config.channels:
        try:
            groups.append(feed(channel, limit=5))
        except (RuntimeError, ValueError, OSError) as error:
            events.append(
                {
                    "stage": "feed",
                    "channel": channel.name,
                    "error_type": type(error).__name__,
                }
            )
    attempts = 0
    for offset in range(5):
        for group in groups:
            if (
                len(contexts) >= len(CACHED_IDS) + fresh_limit
                or attempts >= max_fetches
            ):
                return contexts, events
            if offset >= len(group):
                continue
            video_id = group[offset]["videoId"]
            if video_id in seen:
                continue
            seen.add(video_id)
            attempts += 1
            try:
                # Same metadata/caption/comment path; no unused vision calls for captionless rejects.
                ctx = fetch(video_id, include_scene=False)
                if ctx.get("channelId") not in allowed:
                    reason = "off-channel"
                elif not ctx.get("transcript", "").strip():
                    reason = "no-transcript"
                elif not ctx.get("description", "").strip():
                    reason = "no-description"
                elif not ROMANCE.search(ctx.get("title", "") + ctx["transcript"]):
                    reason = "no-romance-signal"
                else:
                    contexts.append(ctx)
                    reason = "included"
                events.append({"videoId": video_id, "result": reason})
                print(f"holdout {video_id}: {reason}", flush=True)
            except (RuntimeError, ValueError, OSError) as error:
                events.append({"videoId": video_id, "error_type": type(error).__name__})
                print(f"holdout {video_id}: {type(error).__name__}", flush=True)
    return contexts, events


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cached", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    load_env()
    contexts, events = prepare(load_config(), json.loads(args.cached.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(contexts, ensure_ascii=False, indent=2))
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "cached_ids": CACHED_IDS,
                "excluded_gold_ids": sorted(GOLD_IDS),
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"prepared {len(contexts)} transcript-bearing non-gold contexts", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
