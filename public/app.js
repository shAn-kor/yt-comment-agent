const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmtDate = (iso) =>
  iso
    ? new Date(iso).toLocaleDateString("ko-KR", {
        month: "short",
        day: "numeric",
      })
    : "";
const fmtTime = (ts) =>
  new Date(ts).toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const state = {
  config: null,
  videos: [],
  selected: null,
  draft: null,
  validTimer: null,
};

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ── 설정 ───────────────────────────────────────────
async function loadConfig() {
  const c = (state.config = await api("GET", "/api/config"));
  const scope =
    c.postingScope === "test_only"
      ? `테스트 모드 (테스트 영상 ${c.testVideos.length}개에만 게시)`
      : "지정 채널 게시 허용";
  $("#meta").textContent = `AI: ${c.llm} · ${scope}`;
  $("#profile").innerHTML =
    `<option value="auto">자동 배정 (가장 오래 안 쓴 프로필)</option>` +
    c.profiles
      .map(
        (p) =>
          `<option value="${esc(p.name)}">${esc(p.name)}${p.ready ? "" : " — 로그인 필요"}</option>`,
      )
      .join("");
  $("#quota").textContent = `오늘 게시 ${c.usedToday} / ${c.dailyMax}개`;
}

// ── ① 영상 불러오기 ─────────────────────────────────
function renderList() {
  $("#list").innerHTML = state.videos
    .map(
      (
        v,
        i,
      ) => `<li data-i="${i}" class="${state.selected?.videoId === v.videoId ? "on" : ""}">
        <img src="${esc(v.thumbnail)}" alt="" loading="lazy" />
        <div>
          <div class="t">${esc(v.title)}</div>
          <div class="s">${esc(v.channelName)} · ${fmtDate(v.published)}
            ${v.commented ? '<span class="tag">댓글 완료</span>' : ""}
            ${v.draftOnly ? `<span class="tag">시간당 ${v.viewsPerHour}회 · 초안만</span>` : ""}
          </div>
        </div>
      </li>`,
    )
    .join("");
}

async function withMsg(btn, text, fn) {
  const msg = $("#listMsg");
  msg.className = "msg";
  msg.textContent = text;
  if (btn) btn.disabled = true;
  try {
    await fn();
  } catch (e) {
    msg.className = "msg bad";
    msg.textContent = e.message;
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("#load").onclick = () =>
  withMsg($("#load"), "불러오는 중…", async () => {
    const { videos, errors } = await api("POST", "/api/videos");
    state.videos = videos;
    renderList();
    $("#listMsg").textContent =
      `${videos.length}개 영상` +
      (errors.length ? ` · 실패: ${errors.join(", ")}` : "");
  });

$("#linkForm").onsubmit = (e) => {
  e.preventDefault();
  const url = $("#link").value.trim();
  if (!url) return;
  withMsg(null, "링크 확인 중…", async () => {
    const { video } = await api("POST", "/api/resolve", { url });
    state.videos = [
      video,
      ...state.videos.filter((v) => v.videoId !== video.videoId),
    ];
    renderList();
    $("#listMsg").textContent = `허용된 채널입니다: ${video.channelName}`;
    select(video);
  });
};

$("#rising").onclick = () =>
  withMsg(
    $("#rising"),
    "‘연애’ 최신 영상 조회수 확인 중… (1분 정도)",
    async () => {
      const { videos } = await api("POST", "/api/rising");
      state.videos = videos;
      renderList();
      $("#listMsg").textContent = videos.length
        ? `조건에 맞는 영상 ${videos.length}개 (조회수 1,000~5,000 · 시간당 150회 이상)`
        : "조건에 맞는 영상이 지금은 없습니다";
    },
  );

$("#list").onclick = (e) => {
  const li = e.target.closest("li[data-i]");
  if (li) select(state.videos[Number(li.dataset.i)]);
};

// ── ② 영상 선택 ─────────────────────────────────────
async function select(video) {
  state.selected = video;
  state.draft = null;
  renderList();
  resetPost();
  $("#detail").className = "";
  $("#detail").innerHTML =
    `${videoHead(video)}<p class="msg">자막과 인기 댓글을 읽고 초안을 쓰는 중… (30초~1분)</p>`;
  try {
    const d = await api("POST", "/api/draft", { videoId: video.videoId });
    if (state.selected?.videoId !== video.videoId) return;
    state.draft = d;
    renderDetail();
  } catch (e) {
    $("#detail").innerHTML =
      `${videoHead(video)}<p class="msg bad">${esc(e.message)}</p>
      <button id="retry">다시 시도</button>`;
    $("#retry").onclick = () => select(video);
  }
}

function videoHead(v) {
  return `<div class="video">
    <img src="${esc(v.thumbnail)}" alt="" />
    <div><a href="https://www.youtube.com/watch?v=${esc(v.videoId)}" target="_blank" rel="noopener">${esc(v.title)}</a>
      <div class="meta">${esc(v.channelName)} · ${fmtDate(v.published)}</div></div>
  </div>`;
}

function renderDetail() {
  const d = state.draft;
  $("#detail").innerHTML = `${videoHead(state.selected)}
    <div class="block"><div class="label">영상 속 고민 한 줄</div><div class="concern">${esc(d.concern)}</div></div>
    <div class="block"><div class="label">근거 (${esc(d.sourceLabel)} · 인기 댓글 ${d.commentCount}개 참고)</div>
      <div id="anchor">“${esc(d.validation.anchor || d.detail)}”</div></div>
    <div class="block"><div class="label">댓글 초안 — 고쳐도 됩니다</div>
      <textarea id="comment">${esc(d.comment)}</textarea>
      <div class="count"><span id="chars"></span><span>시도 ${d.attempts}회</span></div>
      <ul id="checks" class="checks"></ul>
    </div>
    <button id="regen">다시 생성</button>`;
  $("#comment").oninput = () => {
    clearTimeout(state.validTimer);
    state.validTimer = setTimeout(revalidate, 300);
  };
  $("#regen").onclick = () => select(state.selected);
  showValidation(d.validation);
}

async function revalidate() {
  const comment = $("#comment").value;
  const v = await api("POST", "/api/validate", {
    videoId: state.selected.videoId,
    comment,
    detail: state.draft.detail,
  });
  state.draft.validation = v;
  state.draft.comment = comment;
  showValidation(v);
}

function showValidation(v) {
  const { min, max } = state.config.comment;
  $("#chars").textContent = `${v.chars}자 (${min}~${max}자)`;
  $("#checks").innerHTML = v.ok
    ? '<li class="okline">검사 통과: 글자 수 · 운명원 1회 · 링크/해시태그 없음 · 후기 아님 · 영상 속 표현 포함</li>'
    : v.errors.map((e) => `<li>${esc(e)}</li>`).join("");
  if (v.anchor && $("#anchor")) $("#anchor").textContent = `“${v.anchor}”`;
  updatePostButton();
}

// ── ③ 댓글 달기 ─────────────────────────────────────
function updatePostButton() {
  const d = state.draft;
  const reason = !d
    ? ""
    : !d.post.ok
      ? d.post.reason
      : !d.validation.ok
        ? "댓글 검사를 통과해야 게시할 수 있습니다"
        : "";
  $("#post").disabled = !d || !!reason;
  $("#postReason").className = reason ? "msg bad" : "msg";
  $("#postReason").textContent = reason;
}

function resetPost() {
  document.querySelectorAll("#steps li").forEach((li) => (li.className = ""));
  $("#result").innerHTML = "";
  updatePostButton();
}

// 세부 상태를 세 단계 표시에 맞춘다
const STEP_OF = { '프로필 여는 중': 0, '영상 여는 중': 0, '댓글창 찾는 중': 0, '입력 중': 1, '게시 중': 1, '내 댓글 확인 중': 1, '게시 완료': 2 };
function showStep(status, failed) {
  const at = STEP_OF[status] ?? 0;
  const finished = status === '게시 완료';
  document.querySelectorAll('#steps li').forEach((li, i) => {
    li.className = finished || i < at ? 'done' : i === at ? (failed ? 'fail' : 'now') : '';
  });
  if (!failed && !finished) $('#postReason').textContent = status;
}

$("#post").onclick = async () => {
  const d = state.draft;
  $("#post").disabled = true;
  $("#result").innerHTML = "";
  try {
    const { jobId, profile } = await api("POST", "/api/post", {
      videoId: state.selected.videoId,
      comment: $("#comment").value,
      detail: d.detail,
      profile: $("#profile").value,
    });
    $("#postReason").className = "msg";
    $("#postReason").textContent = `${profile}로 게시합니다`;
    showStep("프로필 여는 중");
    const job = await poll(jobId);
    if (job.ok) {
      showStep("게시 완료");
      $("#result").innerHTML =
        `<a href="${esc(job.commentUrl)}" target="_blank" rel="noopener">내 댓글 보기 →</a>`;
      state.selected.commented = true;
      d.post = { ok: false, reason: "이미 댓글을 단 영상" };
      renderList();
    } else {
      showStep(job.lastStep, true);
      $("#result").innerHTML =
        `<p class="msg bad">실패: ${esc(job.error)}</p>` +
        (job.screenshot
          ? `<img src="/shots/${esc(job.screenshot)}" alt="실패 화면" />`
          : "");
    }
  } catch (e) {
    $("#postReason").className = "msg bad";
    $("#postReason").textContent = e.message;
  }
  await Promise.all([loadConfig(), loadLogs()]);
  updatePostButton();
};

async function poll(id) {
  let lastStep = "프로필 여는 중";
  for (;;) {
    await new Promise((r) => setTimeout(r, 700));
    const job = await api("GET", `/api/job?id=${id}`);
    if (job.done) return { ...job, lastStep };
    lastStep = job.status;
    showStep(job.status);
  }
}

// ── 기록 ───────────────────────────────────────────
const STATUS = { success: "성공", failed: "실패", blocked: "차단" };
async function loadLogs() {
  const { logs } = await api("GET", "/api/logs");
  $("#logs").innerHTML = logs.length
    ? logs
        .map(
          (l) => `<tr>
        <td>${fmtTime(l.ts)}</td>
        <td>${l.video_id ? `<a href="https://www.youtube.com/watch?v=${esc(l.video_id)}" target="_blank" rel="noopener">${esc(l.video_title || l.video_id)}</a><div class="meta">${esc(l.channel_name)}</div>` : ""}</td>
        <td>${esc(l.profile)}</td>
        <td class="c">${esc(l.comment)}</td>
        <td><span class="st-${l.status}">${STATUS[l.status]}</span>${l.reason ? `<div class="meta">${esc(l.reason)}</div>` : ""}
          ${l.comment_url ? `<div><a href="${esc(l.comment_url)}" target="_blank" rel="noopener">댓글 보기</a></div>` : ""}</td>
        <td>${l.screenshot ? `<a href="/shots/${esc(l.screenshot)}" target="_blank">보기</a>` : ""}</td>
      </tr>`,
        )
        .join("")
    : '<tr><td colspan="6" class="meta">아직 기록이 없습니다.</td></tr>';
}

loadConfig()
  .then(loadLogs)
  .catch((e) => ($("#meta").textContent = `서버 연결 실패: ${e.message}`));
