"""로컬 대시보드 서버 (FastAPI). 127.0.0.1에서만 열린다.

uv run python -m agent.server
"""

import asyncio
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, load_config, load_env
from .generate import draft_comment, source_text
from .llm import backend_name
from .rules import (
    check_load_scope,
    check_post,
    check_post_scope,
    kst_date,
    pick_profile,
)
from .store import Store
from .validate import validate_comment
from .youtube import fetch_channel_feed, find_rising, get_video_context, parse_video_id

load_env()
config = load_config()
DATA = ROOT / "data"
SHOTS = DATA / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
store = Store(DATA / "agent.db")

contexts: dict[str, dict] = {}  # videoId -> 영상 자료 (자막·댓글)
rising_ids: set[str] = set()  # 뜨기 직전 영상: 초안만 허용
session_drafts: list[
    dict
] = []  # 이번 실행에서 만든 초안 {videoId, text} (영상마다 다르게)
jobs: dict[str, dict] = {}
tasks: set[asyncio.Task] = set()
busy = False

app = FastAPI(title="댓글 에이전트")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    # 화면(app.js)은 {error: "..."} 모양을 기대한다
    return JSONResponse({"error": e.message}, status_code=e.status)


@app.exception_handler(Exception)
async def unexpected(_: Request, e: Exception):
    return JSONResponse({"error": str(e)}, status_code=500)


async def context(video_id: str) -> dict:
    if video_id not in contexts:
        contexts[video_id] = await asyncio.to_thread(get_video_context, video_id)
    return contexts[video_id]


def previous(video_id: str) -> list[str]:
    """다른 영상에 쓴 댓글·초안만 비교 대상 (같은 영상의 초안을 고친 글은 비슷해도 된다)"""
    drafts = [d["text"] for d in session_drafts if d["videoId"] != video_id]
    return (store.previous_comments(30, video_id) + drafts)[:30]


def video_of(ctx: dict) -> dict:
    # 채널 이름은 설정의 한글 이름을 우선, 썸네일은 항상 있는 hqdefault
    known = next((c for c in config.channels if c.id == ctx["channelId"]), None)
    ts = ctx.get("timestamp")
    return {
        "videoId": ctx["videoId"],
        "title": ctx["title"],
        "channelId": ctx["channelId"],
        "channelName": known.name if known else ctx["channelName"],
        "thumbnail": f"https://i.ytimg.com/vi/{ctx['videoId']}/hqdefault.jpg",
        "views": ctx.get("views"),
        "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
        if ts
        else None,
    }


def draft_only(video: dict) -> bool:
    return video["videoId"] in rising_ids and not check_load_scope(video, config)["ok"]


def rules_kwargs() -> dict:
    c = config.comment
    return {"brand": c.brand, "min": c.min, "max": c.max}


def post_state(video: dict) -> dict:
    """게시 전 규칙 상태 (화면 표시용. 실제 차단은 /api/post에서 다시 검사)"""
    only_draft = draft_only(video)
    scope = check_post_scope(video, config)
    done = store.has_success(video["videoId"])
    daily = config.limits.daily_max
    left = max(daily - store.count_success_on(kst_date()), 0)
    checks = [
        {
            "key": "scope",
            "label": "본인 테스트 영상"
            if scope.get("kind") == "test"
            else "허용된 게시 범위",
            "ok": not only_draft and scope["ok"],
            "note": "뜨기 직전 영상은 초안까지만"
            if only_draft
            else scope.get("reason", ""),
        },
        {
            "key": "once",
            "label": "이 영상에 첫 댓글",
            "ok": not done,
            "note": "이미 댓글을 단 영상 (영상당 1개)" if done else "",
        },
        {
            "key": "quota",
            "label": f"오늘 남은 게시 {left}/{daily}",
            "ok": left > 0,
            "note": "" if left else "오늘 상한 도달",
        },
    ]
    failed = next((c for c in checks if not c["ok"]), None)
    return {
        "ok": not failed,
        "reason": failed["note"] if failed else "",
        "checks": checks,
    }


# ── API ─────────────────────────────────────────────


class ResolveIn(BaseModel):
    url: str = ""


class DraftIn(BaseModel):
    videoId: str


class ValidateIn(BaseModel):
    videoId: str
    comment: str = ""
    detail: str = ""


class PostIn(ValidateIn):
    profile: str = "auto"


@app.get("/api/config")
def get_config():
    return {
        "profiles": [
            {"name": p.name, "ready": p.dir.exists()} for p in config.profiles
        ],
        "channels": [{"id": c.id, "name": c.name} for c in config.channels],
        "postingScope": config.posting_scope,
        "testVideos": config.test_videos,
        "comment": {
            "min": config.comment.min,
            "max": config.comment.max,
            "brand": config.comment.brand,
        },
        "dailyMax": config.limits.daily_max,
        "usedToday": store.count_success_on(kst_date()),
        "llm": backend_name(),
    }


@app.post("/api/videos")
async def videos():
    commented = store.commented_ids()
    results = await asyncio.gather(
        *(
            asyncio.to_thread(fetch_channel_feed, c, config.limits.per_channel)
            for c in config.channels
        ),
        return_exceptions=True,
    )
    found = [v for r in results if not isinstance(r, Exception) for v in r]
    found.sort(key=lambda v: v["published"] or "", reverse=True)
    return {
        "videos": [{**v, "commented": v["videoId"] in commented} for v in found],
        "errors": [str(r) for r in results if isinstance(r, Exception)],
    }


@app.post("/api/resolve")
async def resolve(body: ResolveIn):
    video_id = parse_video_id(body.url)
    if not video_id:
        raise ApiError(400, "유튜브 영상 링크가 아닙니다")
    video = video_of(await context(video_id))
    scope = check_load_scope(video, config)
    if not scope["ok"]:
        store.add(
            {**video, "status": "blocked", "reason": f"링크 입력: {scope['reason']}"}
        )
        raise ApiError(403, f"{scope['reason']} ({video['channelName']})")
    return {"video": {**video, "commented": store.has_success(video_id)}}


@app.post("/api/draft")
async def draft(body: DraftIn):
    ctx = await context(body.videoId)
    video = video_of(ctx)
    if not check_load_scope(video, config)["ok"] and body.videoId not in rising_ids:
        raise ApiError(403, "허용 범위 밖 영상")
    d = await asyncio.to_thread(
        draft_comment, ctx, **rules_kwargs(), previous=previous(body.videoId)
    )
    if d and d["comment"]:
        session_drafts.insert(0, {"videoId": body.videoId, "text": d["comment"]})
    return {
        "video": video,
        "sourceLabel": ctx["sourceLabel"],
        "commentCount": len(ctx["topComments"]),
        "concern": d["concern"],
        "detail": d["detail"],
        "comment": d["comment"],
        "attempts": d["attempts"],
        "validation": d["validation"],
        "post": post_state(video),
    }


@app.post("/api/validate")
async def validate(body: ValidateIn):
    ctx = await context(body.videoId)
    return validate_comment(
        body.comment,
        source=source_text(ctx),
        detail=body.detail,
        **rules_kwargs(),
        previous=previous(body.videoId),
    )


@app.post("/api/post")
async def post(body: PostIn):
    global busy
    if busy:
        raise ApiError(409, "다른 댓글을 게시하는 중입니다")
    ctx = await context(body.videoId)
    video = video_of(ctx)  # 채널은 화면이 보낸 값이 아니라 yt-dlp 결과로 확인
    name = (
        pick_profile(config, store.last_used)
        if body.profile in ("", "auto")
        else body.profile
    )
    row = {**video, "profile": name, "comment": body.comment}

    def block(status: int, reason: str, log_reason: str | None = None):
        store.add({**row, "status": "blocked", "reason": log_reason or reason})
        raise ApiError(status, reason)

    if draft_only(video):
        block(403, "뜨기 직전 영상은 초안까지만")
    v = validate_comment(
        body.comment,
        source=source_text(ctx),
        detail=body.detail,
        **rules_kwargs(),
        previous=previous(body.videoId),
    )
    if not v["ok"]:
        block(422, ", ".join(v["errors"]), f"검증 실패: {', '.join(v['errors'])}")
    rule = check_post(video, name, config, store)
    if not rule["ok"]:
        block(403, rule["reason"])

    from .poster import PostError, post_comment  # Playwright는 게시할 때만 불러온다

    job_id = str(int(time.time() * 1000))
    job = jobs[job_id] = {
        "id": job_id,
        "profile": name,
        "status": "대기",
        "done": False,
    }
    busy = True
    profile_dir = next(p.dir for p in config.profiles if p.name == name)

    async def run():
        global busy
        try:
            out = await post_comment(
                profile_dir=profile_dir,
                video_id=body.videoId,
                text=body.comment,
                shot_dir=SHOTS,
                on_status=lambda s: job.update(status=s),
            )
            store.add({**row, "status": "success", **out})
            job.update(status="게시 완료", done=True, ok=True, **out)
        except Exception as e:
            shot = getattr(e, "screenshot", None) if isinstance(e, PostError) else None
            store.add({**row, "status": "failed", "reason": str(e), "screenshot": shot})
            job.update(
                status="실패", done=True, ok=False, error=str(e), screenshot=shot
            )
        finally:
            busy = False

    task = asyncio.create_task(run())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return {"jobId": job_id, "profile": name}


@app.get("/api/job")
def job(id: str):
    if id not in jobs:
        raise ApiError(404, "작업 없음")
    return jobs[id]


@app.get("/api/logs")
def logs():
    return {"logs": store.list()}


@app.get("/api/post-state")
async def get_post_state(videoId: str):
    return post_state(video_of(await context(videoId)))


@app.post("/api/rising")
async def rising():
    found = await asyncio.to_thread(find_rising, config.rising)
    rising_ids.update(v["videoId"] for v in found)
    return {"videos": [{**v, "draftOnly": True} for v in found]}


# 정적 파일. StaticFiles가 ../ 같은 경로 탈출을 막는다.
app.mount("/shots", StaticFiles(directory=SHOTS), name="shots")
app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="public")


def main():
    import uvicorn

    port = int(os.environ.get("PORT") or 4310)
    print(f"대시보드: http://localhost:{port}", flush=True)
    print(
        f"AI: {backend_name()} · 게시 범위: {config.posting_scope} · 테스트 영상 {len(config.test_videos)}개",
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
