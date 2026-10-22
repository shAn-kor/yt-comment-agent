"""ego 브라우저(ego lite)로 댓글을 게시한다. 크롬 프로필 대신 ego에 이미 로그인된 유튜브 계정을 쓴다.

`ego-browser nodejs`에 스크립트를 넘겨 실행한다. ego 실행기는 화면 출력을 끝날 때 한꺼번에 내보내므로,
스크립트는 진행 상태와 결과를 파일에도 한 줄씩 덧붙이고, 서버는 그 파일을 읽어 진행 단계를 바로 보여 준다.
입력 방식과 확인 순서는 poster.py와 같다 (한 글자씩 입력 → 게시 → 내 댓글이 보이는지 확인).
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from .poster import PostError

EGO = "ego-browser"
TIMEOUT = 180  # 초. 입력 120자 기준 약 20초 + 페이지 로드·확인 여유

SCRIPT = r"""
const A = __ARGS__;
const fs = await import("node:fs");
const say = (kind, v) => {
  const line = "@@" + kind + " " + JSON.stringify(v);
  console.log(line);
  if (A.statusFile) fs.appendFileSync(A.statusFile, line + "\n");
};
const task = await taskSpace("yt-comment-agent " + A.videoId + " " + A.stamp);
const page = task.page("p1");
// 시연 녹화: recordDir가 있으면 단계마다, 입력 중에는 세 글자마다 화면을 저장한다
const frame = async () => {
  if (!A.recordDir) return;
  try { await page.screenshot({ path: A.recordDir + "/" + Date.now() + "-post.png" }); } catch {}
};
let submitted = false;
const shot = async (tag) => {
  const file = A.stamp + "-" + A.videoId + "-" + tag + ".png";
  try { await page.screenshot({ path: A.shotDir + "/" + file }); return file; } catch { return null; }
};
const fail = async (message, tag) => { say("error", { message, screenshot: await shot(tag), submitted }); };
try {
  say("status", "영상 여는 중");
  await page.cdp("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await page.goto("https://www.youtube.com/watch?v=" + A.videoId + "&hl=ko");
  await page.waitForSelector("loc=css:ytd-watch-flexy", { timeout: 30000 });
  await page.waitForTimeout(1500);
  await frame();
  const signedOut = await page.evaluate(() => window.ytcfg?.get?.("LOGGED_IN") === false
    || !!document.querySelector('ytd-masthead a[href*="ServiceLogin"]'));
  if (signedOut) {
    await fail("로그인 안 됨 — ego 브라우저에서 유튜브에 로그인하세요", "signed-out");
  } else {
    say("status", "댓글창 찾는 중");
    let state = "none";
    for (let i = 0; i < 15 && state === "none"; i++) {
      state = await page.evaluate(() =>
        document.querySelector("ytd-comments ytd-comment-simplebox-renderer #placeholder-area") ? "box"
        : document.querySelector("ytd-comments ytd-message-renderer") ? "off" : "none");
      if (state === "none") { await page.evaluate(() => window.scrollBy(0, 700)); await page.waitForTimeout(800); }
    }
    if (state === "off") await fail("댓글 사용이 중지된 영상", "comments-off");
    else if (state === "none") await fail("댓글 입력창을 찾지 못함", "no-box");
    else {
      await frame();
      await page.click("ytd-comments ytd-comment-simplebox-renderer #placeholder-area", { label: "댓글 입력창 열기" });
      await page.waitForSelector("loc=css:ytd-commentbox #contenteditable-root", { state: "visible", timeout: 10000 });
      await page.click("ytd-commentbox #contenteditable-root", { label: "댓글 입력칸" });
      say("status", "입력 중");
      let typedCount = 0;
      for (const ch of A.text) {
        await page.keyboard.insertText(ch);
        await page.waitForTimeout(60 + Math.random() * 110);
        if (++typedCount % 3 === 0) await frame();
      }
      await frame();
      await page.waitForTimeout(600);
      const typed = await page.evaluate(() => document.querySelector("ytd-commentbox #contenteditable-root")?.innerText ?? "");
      if (typed.trim() !== A.text.trim()) {
        await fail("입력된 글이 초안과 다름", "typed-mismatch");
      } else {
        say("status", "게시 중");
        await page.click("ytd-commentbox #submit-button button", { label: "댓글 게시" });
        submitted = true;
        await frame();
        say("status", "내 댓글 확인 중");
        const head = A.text.slice(0, 18);
        let href = null, seen = false;
        for (let i = 0; i < 40 && !seen; i++) {
          const r = await page.evaluate((head) => {
            for (const t of document.querySelectorAll("ytd-comment-thread-renderer")) {
              if ((t.querySelector("#content-text")?.innerText ?? "").includes(head)) {
                t.scrollIntoView({ block: "center" });
                return { seen: true, href: t.querySelector("#published-time-text a")?.getAttribute("href") ?? null };
              }
            }
            return { seen: false };
          }, head);
          seen = r.seen; href = r.href ?? null;
          if (!seen) await page.waitForTimeout(500);
        }
        if (!seen) await fail("게시 후 내 댓글이 보이지 않음 (스팸 필터에 숨겨졌을 수 있음)", "not-visible");
        else {
          await frame();
          await page.waitForTimeout(1500);
          await frame();
          const screenshot = await shot("posted");
          say("status", "게시 완료");
          say("result", { href, screenshot });
        }
      }
    }
  }
} catch (e) {
  await fail(String(e?.message ?? e).split("\n")[0], "error");
}
await task.finish({ keep: [] });
"""


def build_script(
    video_id: str,
    text: str,
    shot_dir: Path,
    stamp: str,
    status_file: str = "",
    record_dir: str = "",
) -> str:
    args = {
        "videoId": video_id,
        "text": text,
        "shotDir": str(shot_dir.resolve()),
        "stamp": stamp,
        "statusFile": status_file,
        "recordDir": record_dir,
    }
    # JSON은 그대로 JavaScript 값이 된다. 글 안의 따옴표·줄바꿈이 스크립트를 깨지 않는다
    return SCRIPT.replace("__ARGS__", json.dumps(args, ensure_ascii=False))


def parse_line(line: str) -> tuple[str, object] | None:
    if not line.startswith("@@"):
        return None
    kind, _, rest = line[2:].partition(" ")
    try:
        return kind, json.loads(rest)
    except json.JSONDecodeError:
        return None


async def post_comment(
    *,
    profile_dir: Path
    | None = None,  # 크롬 방식과 같은 모양을 맞추기 위한 자리. 쓰지 않는다
    video_id: str,
    text: str,
    shot_dir: Path,
    on_status: Callable[[str], None] = lambda s: None,
) -> dict:
    shot_dir.mkdir(parents=True, exist_ok=True)
    exe = shutil.which(EGO)
    if not exe:
        raise PostError("ego 브라우저(ego-browser)를 찾지 못함")
    # 시연 녹화용. 비어 있으면 화면을 저장하지 않는다
    record_dir = os.environ.get("POSTER_RECORD_DIR", "")
    if record_dir:
        record_dir = str(Path(record_dir).resolve())
        Path(record_dir).mkdir(parents=True, exist_ok=True)
    fd, status_name = tempfile.mkstemp(prefix="ego-post-", suffix=".log")
    os.close(fd)
    status_path = Path(status_name)
    script = build_script(
        video_id,
        text,
        shot_dir,
        str(int(time.time() * 1000)),
        status_name,
        record_dir,
    )
    on_status("ego 브라우저 여는 중")
    proc = await asyncio.create_subprocess_exec(
        exe,
        "nodejs",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    proc.stdin.write(script.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    result = error = None
    submitted = False
    tail: list[str] = []
    out: list[str] = []
    used = 0  # 상태 파일에서 처리한 글자 수

    def take(lines: list[str]):
        nonlocal result, error, submitted
        for line in lines:
            msg = parse_line(line.rstrip())
            if not msg:
                continue
            kind, v = msg
            if kind == "status":
                on_status(str(v))
                submitted = submitted or v == "내 댓글 확인 중"
            elif kind == "result":
                result = v
            elif kind == "error":
                error = v

    def poll():
        nonlocal used
        try:
            data = status_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        whole = data[: data.rfind("\n") + 1]  # 다 쓴 줄만 읽는다
        take(whole[used:].splitlines())
        used = len(whole)

    async def read():
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                out.append(line)

    async def run():
        reader = asyncio.ensure_future(read())
        while not reader.done():
            poll()
            await asyncio.wait([reader], timeout=0.3)
        await proc.wait()
        poll()
        if used == 0:
            take(out)  # 상태 파일을 못 쓴 경우: 끝에 한꺼번에 온 화면 출력에서 읽는다

    try:
        await asyncio.wait_for(run(), TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise PostError("ego 브라우저 응답 시간 초과", submitted=submitted)
    finally:
        status_path.unlink(missing_ok=True)
    tail[:] = [ln for ln in out if not ln.startswith("@@")][-5:]

    if result:
        href = result.get("href")
        return {
            "commentUrl": f"https://www.youtube.com{href}"
            if href
            else f"https://www.youtube.com/watch?v={video_id}",
            "screenshot": result.get("screenshot"),
        }
    if error:
        raise PostError(
            error.get("message") or "게시 실패",
            error.get("screenshot"),
            bool(error.get("submitted")) or submitted,
        )
    raise PostError(
        "ego 브라우저 실행 실패: "
        + (" / ".join(tail) or f"종료 코드 {proc.returncode}"),
        submitted=submitted,
    )
