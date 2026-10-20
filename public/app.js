const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const icon = (id) => `<svg><use href="#i-${id}"/></svg>`;

function ago(iso) {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${Math.max(m, 1)}분 전`;
  if (m < 60 * 24) return `${Math.round(m / 60)}시간 전`;
  if (m < 60 * 24 * 30) return `${Math.round(m / 1440)}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
const fmtTime = (ts) =>
  new Date(ts).toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const num = (n) => (n == null ? "" : Number(n).toLocaleString("ko-KR"));

const state = {
  config: null,
  videos: [],
  mode: "channels", // channels | rising
  channel: "all",
  selected: null,
  draft: null,
  profile: "auto",
  posted: false,
  logFilter: "all",
  timer: null,
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

// ── 단계 표시 ──────────────────────────────────────
function renderSteps() {
  const s1 = state.videos.length > 0;
  const s2 = !!state.draft?.validation?.ok;
  const s3 = state.posted;
  const status = [
    s1 ? "done" : "now",
    s2 ? "done" : s1 ? "now" : "wait",
    s3 ? "done" : s2 ? "now" : "wait",
  ];
  $$("#stepper li").forEach(
    (li, i) => (li.className = status[i] === "wait" ? "" : status[i]),
  );
  $$(".step-badge").forEach((b) => {
    const st = status[Number(b.dataset.for) - 1];
    b.className = `step-badge ${st}`;
    b.innerHTML =
      st === "done" ? `${icon("check")}완료` : st === "now" ? "지금" : "대기";
  });
}

// ── 설정 ───────────────────────────────────────────
async function loadConfig() {
  const c = (state.config = await api("GET", "/api/config"));
  $("#llm").textContent = `AI · ${c.llm}`;
  const mode = $("#mode");
  mode.textContent =
    c.postingScope === "test_only"
      ? `테스트 모드 · 테스트 영상 ${c.testVideos.length}개`
      : "지정 채널 게시 허용";
  mode.className = `capsule ${c.postingScope === "test_only" ? "test" : ""}`;
  $("#quotaText").textContent = `오늘 ${c.usedToday}/${c.dailyMax}`;
  $("#quotaFill").style.width =
    `${Math.min(100, (c.usedToday / c.dailyMax) * 100)}%`;
  renderProfiles();
}

function renderProfiles() {
  const c = state.config;
  const rows = [
    {
      name: "auto",
      label: "자동 배정",
      state: "가장 오래 안 쓴 계정",
      ready: true,
    },
  ].concat(
    c.profiles.map((p) => ({
      name: p.name,
      label: p.name,
      state: p.ready ? "준비됨" : "로그인 필요",
      ready: p.ready,
    })),
  );
  $("#profiles").innerHTML = rows
    .map(
      (r) => `<label class="radio">
        <input type="radio" name="profile" value="${esc(r.name)}" ${state.profile === r.name ? "checked" : ""} />
        <span class="mark"></span><span class="name">${esc(r.label)}</span>
        <span class="state ${r.ready ? "" : "off"}">${esc(r.state)}</span>
      </label>`,
    )
    .join("");
  $$("#profiles input").forEach(
    (i) => (i.onchange = () => (state.profile = i.value)),
  );
}

// ── ① 영상 불러오기 ─────────────────────────────────
function renderChips() {
  if (state.mode === "rising") {
    $("#chips").innerHTML =
      `<button class="chip on" disabled>뜨기 직전 · 초안만</button><button class="chip" id="backToChannels">채널 영상으로</button>`;
    $("#backToChannels").onclick = () => $("#load").click();
    return;
  }
  if (!state.videos.length) return ($("#chips").innerHTML = "");
  const names = ["all", ...new Set(state.videos.map((v) => v.channelName))];
  $("#chips").innerHTML = names
    .map(
      (n) =>
        `<button class="chip ${state.channel === n ? "on" : ""}" data-ch="${esc(n)}" role="tab">${n === "all" ? "전체" : esc(n)}</button>`,
    )
    .join("");
  $$("#chips .chip").forEach(
    (b) =>
      (b.onclick = () => (
        (state.channel = b.dataset.ch),
        renderChips(),
        renderList()
      )),
  );
}

function renderList() {
  const list = state.videos.filter(
    (v) => state.channel === "all" || v.channelName === state.channel,
  );
  $("#list").innerHTML = list
    .map(
      (
        v,
      ) => `<li role="option" data-id="${esc(v.videoId)}" aria-selected="${state.selected?.videoId === v.videoId}">
        <img class="thumb" src="${esc(v.thumbnail)}" alt="" loading="lazy" />
        <div>
          <div class="t">${esc(v.title)}</div>
          <div class="meta">${esc(v.channelName)} · ${ago(v.published)}</div>
          <div class="meta">
            ${v.commented ? '<span class="tag">댓글 완료</span>' : ""}
            ${v.draftOnly ? `<span class="tag hot">조회수 ${num(v.views)} · 시간당 ${num(v.viewsPerHour)}</span>` : ""}
          </div>
        </div>
      </li>`,
    )
    .join("");
}

function listMsg(text, bad = false) {
  $("#listMsg").className = `note ${bad ? "bad" : ""}`;
  $("#listMsg").textContent = text;
}

async function busy(btn, label, fn) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = label;
  try {
    await fn();
  } catch (e) {
    listMsg(e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

$("#load").onclick = () =>
  busy($("#load"), "불러오는 중…", async () => {
    const { videos, errors } = await api("POST", "/api/videos");
    Object.assign(state, { videos, mode: "channels", channel: "all" });
    renderChips();
    renderList();
    renderSteps();
    // RSS가 실패해 '동영상' 탭으로 받은 채널은 올린 날짜가 근삿값이다
    const fallback = [
      ...new Set(
        videos.filter((v) => v.via === "tab").map((v) => v.channelName),
      ),
    ];
    listMsg(
      `${videos.length}개 영상 · 5개 채널` +
        (fallback.length ? ` · 날짜 어림값: ${fallback.join(", ")}` : "") +
        (errors.length ? ` · 실패: ${errors.join(", ")}` : ""),
    );
  });

$("#linkForm").onsubmit = async (e) => {
  e.preventDefault();
  const url = $("#link").value.trim();
  if (!url) return;
  listMsg("링크의 채널을 확인하는 중…");
  try {
    const { video } = await api("POST", "/api/resolve", { url });
    state.mode = "channels";
    state.channel = "all";
    state.videos = [
      video,
      ...state.videos.filter((v) => v.videoId !== video.videoId),
    ];
    renderChips();
    renderList();
    listMsg(`허용된 채널입니다 · ${video.channelName}`);
    $("#link").value = "";
    select(video);
  } catch (err) {
    listMsg(err.message, true);
  }
};

$("#rising").onclick = () =>
  busy($("#rising"), "오늘 올라온 영상 확인 중… (1분 정도)", async () => {
    const { videos } = await api("POST", "/api/rising");
    Object.assign(state, { videos, mode: "rising", channel: "all" });
    renderChips();
    renderList();
    renderSteps();
    listMsg(
      videos.length
        ? `조회수 1,000~5,000 · 시간당 150회 이상 · ${videos.length}개`
        : "지금은 조건에 맞는 영상이 없습니다.",
    );
  });

$("#list").onclick = (e) => {
  const li = e.target.closest("li[data-id]");
  if (li) select(state.videos.find((v) => v.videoId === li.dataset.id));
};

// ── ② 영상 선택 ─────────────────────────────────────
function videoCard(v) {
  const stats = [
    v.channelName,
    v.views != null ? `조회수 ${num(v.views)}회` : "",
    ago(v.published),
  ]
    .filter(Boolean)
    .join(" · ");
  return `<div class="video-card">
    <img class="thumb" src="${esc(v.thumbnail)}" alt="" />
    <div>
      <a href="https://www.youtube.com/watch?v=${esc(v.videoId)}" target="_blank" rel="noopener">${esc(v.title)}</a>
      <div class="meta">${esc(stats)}</div>
    </div>
  </div>`;
}

async function select(video) {
  clearInterval(state.timer);
  Object.assign(state, { selected: video, draft: null, posted: false });
  renderList();
  renderSteps();
  resetPost();
  const started = Date.now();
  const paint = () => {
    const sec = Math.round((Date.now() - started) / 1000);
    $("#detail").innerHTML = `${videoCard(video)}
      <div class="loading">
        <p>자막과 인기 댓글을 읽고 초안을 쓰는 중 · ${sec}초</p>
        <p class="note">보통 15초~1분 걸립니다. 규칙에 맞지 않으면 이유를 알려 주고 다시 씁니다.</p>
      </div>`;
  };
  paint();
  state.timer = setInterval(paint, 1000);
  try {
    const d = await api("POST", "/api/draft", { videoId: video.videoId });
    if (state.selected?.videoId !== video.videoId) return;
    state.draft = d;
    state.selected = {
      ...video,
      ...d.video,
      commented: video.commented,
      draftOnly: video.draftOnly,
    };
    clearInterval(state.timer);
    renderDetail();
  } catch (e) {
    clearInterval(state.timer);
    $("#detail").innerHTML = `${videoCard(video)}
      <div class="loading"><p class="note bad">${esc(e.message)}</p><button class="btn" id="retry">${icon("reload")}다시 시도</button></div>`;
    $("#retry").onclick = () => select(video);
  }
}

function renderDetail() {
  const d = state.draft;
  $("#detail").innerHTML = `${videoCard(state.selected)}
    <div class="group">
      <div class="group-title">영상 속 고민 한 줄</div>
      <div class="concern">${esc(d.concern)}</div>
      <p class="evidence">근거 · ${esc(d.sourceLabel)}, 인기 댓글 ${d.commentCount}개를 읽음</p>
    </div>

    <div class="group">
      <div class="group-title">댓글 초안 · 직접 고쳐도 됩니다</div>
      <div class="editor">
        <textarea id="comment" aria-label="댓글 초안">${esc(d.comment)}</textarea>
        <div class="editor-foot">
          <span id="chars"></span>
          <span class="meter" id="meter"><span class="range"></span><span class="pos"></span></span>
          <button class="btn" id="regen">${icon("reload")}다시 쓰기</button>
        </div>
      </div>
    </div>

    <div class="group">
      <div class="group-title">규칙 검사</div>
      <ul class="list-group checks grid" id="checks"></ul>
      <ul class="fixes" id="fixes"></ul>
    </div>

    <div class="group">
      <div class="group-title">미리보기</div>
      <div class="preview">
        <span class="avatar">나</span>
        <div><div class="who">@시청자<span>방금 전</span></div><div class="text" id="previewText"></div></div>
      </div>
      <div class="legend"><span><i class="a"></i>영상에서 가져온 말</span><span><i class="b"></i>${esc(state.config.comment.brand)}</span></div>
    </div>`;

  let t;
  $("#comment").oninput = () => {
    renderPreview($("#comment").value, d.validation.anchor);
    clearTimeout(t);
    t = setTimeout(revalidate, 300);
  };
  $("#regen").onclick = () => select(state.selected);
  showValidation(d.validation);
}

function renderPreview(text, anchor) {
  const brand = state.config.comment.brand;
  const marks = [];
  const at = anchor ? text.indexOf(anchor) : -1;
  if (at >= 0) marks.push([at, at + anchor.length, ""]);
  for (
    let i = text.indexOf(brand);
    i >= 0;
    i = text.indexOf(brand, i + brand.length)
  ) {
    if (!marks.some(([s, e]) => i < e && i + brand.length > s))
      marks.push([i, i + brand.length, "brand"]);
  }
  marks.sort((a, b) => a[0] - b[0]);
  let html = "";
  let pos = 0;
  for (const [s, e, cls] of marks) {
    html +=
      esc(text.slice(pos, s)) +
      `<mark class="${cls}">${esc(text.slice(s, e))}</mark>`;
    pos = e;
  }
  $("#previewText").innerHTML = html + esc(text.slice(pos));
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
  const top = max + 40;
  $("#chars").textContent = `${v.chars}자`;
  $("#meter").className =
    `meter ${v.chars < min || v.chars > max ? "out" : ""}`;
  $("#meter .range").style.cssText =
    `left:${(min / top) * 100}%;width:${((max - min) / top) * 100}%`;
  $("#meter .pos").style.left = `${Math.min(v.chars / top, 1) * 100}%`;
  $("#checks").innerHTML = v.checks
    .map(
      (c) =>
        `<li class="${c.ok ? "ok" : "bad"}" title="${esc(c.note)}">${icon(c.ok ? "check" : "x")}<span>${esc(c.label)}</span></li>`,
    )
    .join("");
  $("#fixes").innerHTML = v.errors.map((e) => `<li>${esc(e)}</li>`).join("");
  renderPreview($("#comment").value, v.anchor);
  renderSteps();
  renderPostChecks();
}

// ── ③ 댓글 달기 ─────────────────────────────────────
function renderPostChecks() {
  const d = state.draft;
  if (!d) {
    $("#postChecks").innerHTML =
      '<li class="muted">영상을 고르면 확인합니다.</li>';
    $("#post").disabled = true;
    $("#postReason").textContent = "";
    return;
  }
  const items = [
    {
      label: "댓글 규칙 검사 통과",
      ok: d.validation.ok,
      note: d.validation.ok
        ? ""
        : `${d.validation.errors.length}개 항목을 고쳐 주세요`,
    },
    ...d.post.checks,
  ];
  $("#postChecks").innerHTML = items
    .map(
      (c) =>
        `<li class="${c.ok ? "ok" : "bad"}">${icon(c.ok ? "check" : "x")}<span>${esc(c.label)}</span>${c.ok ? "" : `<span class="why">${esc(c.note)}</span>`}</li>`,
    )
    .join("");
  const blocked = items.find((c) => !c.ok);
  $("#post").disabled = !!blocked || state.posted;
  $("#postReason").className = "note center";
  $("#postReason").textContent = blocked
    ? ""
    : "누르면 크롬 창이 열리고 화면에서 직접 입력합니다.";
}

function resetPost() {
  $$("#steps li").forEach((li) => {
    li.className = "";
    li.querySelector("svg").innerHTML = '<use href="#i-dot"/>';
    li.querySelector("time").textContent = "";
  });
  $("#result").innerHTML = "";
  renderPostChecks();
}

const STEP_OF = {
  "프로필 여는 중": 0,
  "영상 여는 중": 0,
  "댓글창 찾는 중": 1,
  "입력 중": 2,
  "게시 중": 3,
  "내 댓글 확인 중": 3,
  "게시 완료": 4,
};
function showStep(status, started, failed = false) {
  const at = STEP_OF[status] ?? 0;
  $$("#steps li").forEach((li, i) => {
    const st = i < at ? "done" : i === at ? (failed ? "fail" : "now") : "";
    if (li.className !== st && (st === "now" || st === "fail"))
      li.querySelector("time").textContent =
        `${Math.round((Date.now() - started) / 1000)}초`;
    li.className = st;
    li.querySelector("svg").innerHTML =
      `<use href="#i-${st === "done" ? "check" : st === "fail" ? "x" : st === "now" ? "now" : "dot"}"/>`;
  });
}

$("#post").onclick = async () => {
  const d = state.draft;
  $("#post").disabled = true;
  resetPost();
  $("#post").disabled = true;
  const started = Date.now();
  try {
    const { jobId, profile } = await api("POST", "/api/post", {
      videoId: state.selected.videoId,
      comment: $("#comment").value,
      detail: d.detail,
      profile: state.profile,
    });
    $("#postReason").textContent = `${profile} 계정으로 게시합니다.`;
    showStep("프로필 여는 중", started);
    const job = await poll(jobId, started);
    if (job.ok) {
      showStep("게시 완료", started);
      state.posted = true;
      state.selected.commented = true;
      const v = state.videos.find((x) => x.videoId === state.selected.videoId);
      if (v) v.commented = true;
      $("#result").innerHTML =
        `<div class="result ok"><strong>게시 완료</strong>
        <p>${esc(profile)} 계정 · ${Math.round((Date.now() - started) / 1000)}초</p>
        <p><a href="${esc(job.commentUrl)}" target="_blank" rel="noopener">유튜브에서 내 댓글 보기 →</a></p>
        ${job.screenshot ? `<img src="/shots/${esc(job.screenshot)}" alt="게시 직후 화면" />` : ""}</div>`;
    } else {
      showStep(job.lastStep, started, true);
      $("#result").innerHTML =
        `<div class="result bad"><strong>실패</strong><p>${esc(job.error)}</p>
        ${job.screenshot ? `<img src="/shots/${esc(job.screenshot)}" alt="실패 순간 화면" />` : ""}</div>`;
    }
  } catch (e) {
    $("#postReason").className = "note center bad";
    $("#postReason").textContent = e.message;
  }
  d.post = await api(
    "GET",
    `/api/post-state?videoId=${encodeURIComponent(state.selected.videoId)}`,
  ).catch(() => d.post);
  renderList();
  renderSteps();
  renderPostChecks();
  await Promise.all([loadConfig(), loadLogs()]);
};

async function poll(id, started) {
  let lastStep = "프로필 여는 중";
  for (;;) {
    await new Promise((r) => setTimeout(r, 600));
    const job = await api("GET", `/api/job?id=${id}`);
    if (job.done) return { ...job, lastStep };
    lastStep = job.status;
    showStep(job.status, started);
  }
}

// ── 기록 ───────────────────────────────────────────
const STATUS = {
  success: ["성공", "check"],
  failed: ["실패", "x"],
  blocked: ["차단", "x"],
};
let logs = [];
async function loadLogs() {
  ({ logs } = await api("GET", "/api/logs"));
  renderLogs();
}
function renderLogs() {
  const rows = logs.filter(
    (l) => state.logFilter === "all" || l.status === state.logFilter,
  );
  $("#logs").innerHTML = rows.length
    ? rows
        .map((l) => {
          const [label, ic] = STATUS[l.status];
          return `<tr>
            <td class="time">${fmtTime(l.ts)}</td>
            <td><span class="pill ${l.status}">${icon(ic)}${label}</span>${l.reason ? `<div class="why-row">${esc(l.reason)}</div>` : ""}</td>
            <td>${l.video_id ? `<a href="https://www.youtube.com/watch?v=${esc(l.video_id)}" target="_blank" rel="noopener">${esc(l.video_title || l.video_id)}</a><div class="why-row">${esc(l.channel_name)}</div>` : ""}</td>
            <td>${esc(l.profile)}</td>
            <td class="c">${esc(l.comment)}</td>
            <td>${[l.comment_url ? `<a href="${esc(l.comment_url)}" target="_blank" rel="noopener">댓글</a>` : "", l.screenshot ? `<a href="/shots/${esc(l.screenshot)}" target="_blank">캡처</a>` : ""].filter(Boolean).join(" · ")}</td>
          </tr>`;
        })
        .join("")
    : '<tr class="empty-row"><td colspan="6">기록이 없습니다.</td></tr>';
}
$$("#logFilter button").forEach(
  (b) =>
    (b.onclick = () => {
      state.logFilter = b.dataset.f;
      $$("#logFilter button").forEach((x) => x.classList.toggle("on", x === b));
      renderLogs();
    }),
);

loadConfig()
  .then(() => (renderSteps(), loadLogs()))
  .catch((e) => listMsg(`서버 연결 실패: ${e.message}`, true));
