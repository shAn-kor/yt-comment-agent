import { createReadStream, existsSync, statSync } from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { loadConfig, loadEnv, ROOT } from './config.mjs';
import { draftComment, sourceText } from './generate.mjs';
import { backendName } from './llm.mjs';
import { checkLoadScope, checkPost, checkPostScope, kstDate, pickProfile } from './rules.mjs';
import { openStore } from './store.mjs';
import { validateComment } from './validate.mjs';
import { fetchChannelFeed, findRising, getVideoContext, parseVideoId } from './youtube.mjs';

loadEnv();
const config = loadConfig();
const DATA = path.join(ROOT, 'data');
const SHOTS = path.join(DATA, 'shots');
const store = openStore(path.join(DATA, 'agent.db'));

const contexts = new Map(); // videoId -> 영상 자료 (자막·댓글)
const risingIds = new Set(); // 뜨기 직전 영상: 초안만 허용
const sessionDrafts = []; // 이번 실행에서 만든 초안 (영상마다 다르게)
const jobs = new Map();
let busy = false;

async function context(videoId) {
  if (!contexts.has(videoId)) contexts.set(videoId, await getVideoContext(videoId));
  return contexts.get(videoId);
}

const previous = () => [...store.previousComments(), ...sessionDrafts].slice(0, 30);

function videoOf(ctx) {
  return {
    videoId: ctx.videoId, title: ctx.title, channelId: ctx.channelId, channelName: ctx.channelName,
    thumbnail: ctx.thumbnail, views: ctx.views,
    published: ctx.timestamp ? new Date(ctx.timestamp * 1000).toISOString() : null,
  };
}

function postState(video) {
  if (risingIds.has(video.videoId) && checkLoadScope(video, config).ok === false) return { ok: false, reason: '뜨기 직전 영상은 초안까지만' };
  const scope = checkPostScope(video, config);
  if (!scope.ok) return scope;
  if (store.hasSuccess(video.videoId)) return { ok: false, reason: '이미 댓글을 단 영상' };
  return { ok: true };
}

// ── API ─────────────────────────────────────────────
const routes = {
  'GET /api/config': () => ({
    profiles: config.profiles.map((p) => ({ name: p.name, ready: existsSync(p.dir) })),
    channels: config.channels,
    postingScope: config.postingScope,
    testVideos: config.testVideos,
    comment: config.comment,
    dailyMax: config.limits.dailyMax,
    usedToday: store.countSuccessOn(kstDate()),
    llm: backendName(),
  }),

  'POST /api/videos': async () => {
    const commented = store.commentedIds();
    const results = await Promise.allSettled(config.channels.map((c) => fetchChannelFeed(c, config.limits.perChannel)));
    const videos = results
      .flatMap((r) => (r.status === 'fulfilled' ? r.value : []))
      .sort((a, b) => String(b.published).localeCompare(String(a.published)))
      .map((v) => ({ ...v, commented: commented.has(v.videoId) }));
    const errors = results.filter((r) => r.status === 'rejected').map((r) => r.reason.message);
    return { videos, errors };
  },

  'POST /api/resolve': async ({ url }) => {
    const videoId = parseVideoId(url);
    if (!videoId) return { status: 400, error: '유튜브 영상 링크가 아닙니다' };
    const ctx = await context(videoId);
    const video = videoOf(ctx);
    const scope = checkLoadScope(video, config);
    if (!scope.ok) {
      store.add({ ...video, status: 'blocked', reason: `링크 입력: ${scope.reason}` });
      return { status: 403, error: `${scope.reason} (${video.channelName})` };
    }
    return { video: { ...video, commented: store.hasSuccess(videoId) } };
  },

  'POST /api/draft': async ({ videoId }) => {
    const ctx = await context(videoId);
    const video = videoOf(ctx);
    if (!checkLoadScope(video, config).ok && !risingIds.has(videoId)) return { status: 403, error: '허용 범위 밖 영상' };
    const draft = await draftComment(ctx, { ...config.comment, previous: previous() });
    if (draft?.comment) sessionDrafts.unshift(draft.comment);
    return {
      video,
      sourceLabel: ctx.sourceLabel,
      commentCount: ctx.topComments.length,
      concern: draft.concern,
      detail: draft.detail,
      comment: draft.comment,
      attempts: draft.attempts,
      validation: draft.validation,
      post: postState(video),
    };
  },

  'POST /api/validate': async ({ videoId, comment, detail }) => {
    const ctx = await context(videoId);
    const prev = previous().filter((c) => c !== comment);
    return validateComment(comment, { source: sourceText(ctx), detail, ...config.comment, previous: prev });
  },

  'POST /api/post': async ({ videoId, comment, profile, detail }) => {
    if (busy) return { status: 409, error: '다른 댓글을 게시하는 중입니다' };
    const ctx = await context(videoId);
    const video = videoOf(ctx); // 채널은 클라이언트 값이 아니라 yt-dlp 결과로 확인
    const name = profile === 'auto' || !profile ? pickProfile(config, store.lastUsed) : profile;
    const row = { ...video, profile: name, comment };

    if (risingIds.has(videoId) && !checkLoadScope(video, config).ok) {
      store.add({ ...row, status: 'blocked', reason: '뜨기 직전 영상은 초안까지만' });
      return { status: 403, error: '뜨기 직전 영상은 초안까지만' };
    }
    const v = validateComment(comment, {
      source: sourceText(ctx), detail, ...config.comment, previous: previous().filter((c) => c !== comment),
    });
    if (!v.ok) {
      store.add({ ...row, status: 'blocked', reason: `검증 실패: ${v.errors.join(', ')}` });
      return { status: 422, error: v.errors.join(', ') };
    }
    const rule = checkPost({ video, profile: name }, config, store);
    if (!rule.ok) {
      store.add({ ...row, status: 'blocked', reason: rule.reason });
      return { status: 403, error: rule.reason };
    }

    const id = String(Date.now());
    const job = { id, profile: name, status: '대기', done: false };
    jobs.set(id, job);
    busy = true;
    const { postComment } = await import('./poster.mjs');
    const profileDir = config.profiles.find((p) => p.name === name).dir;
    postComment({ profileDir, videoId, text: comment, shotDir: SHOTS, onStatus: (s) => (job.status = s) })
      .then(({ commentUrl, screenshot }) => {
        store.add({ ...row, status: 'success', commentUrl, screenshot });
        Object.assign(job, { status: '게시 완료', done: true, ok: true, commentUrl, screenshot });
      })
      .catch((e) => {
        store.add({ ...row, status: 'failed', reason: e.message, screenshot: e.screenshot });
        Object.assign(job, { status: '실패', done: true, ok: false, error: e.message, screenshot: e.screenshot });
      })
      .finally(() => (busy = false));
    return { jobId: id, profile: name };
  },

  'GET /api/job': (_, q) => jobs.get(q.get('id')) || { status: 404, error: '작업 없음' },

  'GET /api/logs': () => ({ logs: store.list() }),

  'POST /api/rising': async () => {
    const videos = await findRising(config.rising);
    videos.forEach((v) => risingIds.add(v.videoId));
    return { videos: videos.map((v) => ({ ...v, draftOnly: true })) };
  },
};

// ── 서버 ────────────────────────────────────────────
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png' };

function serveFile(res, file) {
  if (!existsSync(file) || !statSync(file).isFile()) {
    res.writeHead(404).end('not found');
    return;
  }
  res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
  createReadStream(file).pipe(res);
}

function safeJoin(base, rel) {
  const p = path.resolve(base, '.' + path.posix.normalize('/' + rel));
  return p.startsWith(base) ? p : null;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const handler = routes[`${req.method} ${url.pathname}`];
  if (handler) {
    let body = {};
    if (req.method === 'POST') {
      let raw = '';
      for await (const chunk of req) raw += chunk;
      try { body = raw ? JSON.parse(raw) : {}; } catch { body = {}; }
    }
    try {
      const out = await handler(body, url.searchParams);
      const status = out?.status && out.error ? out.status : 200;
      res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' }).end(JSON.stringify(out));
    } catch (e) {
      console.error(e);
      res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' }).end(JSON.stringify({ error: e.message }));
    }
    return;
  }
  if (url.pathname.startsWith('/shots/')) {
    const f = safeJoin(SHOTS, decodeURIComponent(url.pathname.slice(7)));
    return f ? serveFile(res, f) : res.writeHead(400).end();
  }
  const pub = path.join(ROOT, 'public');
  const f = safeJoin(pub, url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname));
  return f ? serveFile(res, f) : res.writeHead(400).end();
});

const PORT = Number(process.env.PORT) || 4310;
server.listen(PORT, '127.0.0.1', () => {
  console.log(`대시보드: http://localhost:${PORT}`);
  console.log(`AI: ${backendName()} · 게시 범위: ${config.postingScope} · 테스트 영상 ${config.testVideos.length}개`);
});
