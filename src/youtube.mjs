import { execFile } from 'node:child_process';

function ytdlp(args, timeout = 120_000) {
  return new Promise((resolve, reject) => {
    execFile('yt-dlp', ['--no-warnings', ...args], { timeout, maxBuffer: 64 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) {
        const last = String(stderr || err.message).trim().split('\n').pop();
        reject(new Error(`yt-dlp 실패: ${last}`));
      } else resolve(stdout);
    });
  });
}

export function parseVideoId(input) {
  const s = String(input ?? '').trim();
  if (/^[\w-]{11}$/.test(s)) return s;
  try {
    const u = new URL(s);
    if (u.hostname.endsWith('youtu.be')) return u.pathname.slice(1, 12) || null;
    if (u.hostname.endsWith('youtube.com')) {
      const v = u.searchParams.get('v');
      if (v) return v;
      const m = u.pathname.match(/\/(shorts|live|embed)\/([\w-]{11})/);
      if (m) return m[2];
    }
  } catch {}
  return null;
}

const decode = (s) =>
  String(s ?? '')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');

/** 채널 RSS로 최신 영상 목록 (키 필요 없음) */
export async function fetchChannelFeed(channel, limit = 5) {
  const res = await fetch(`https://www.youtube.com/feeds/videos.xml?channel_id=${channel.id}`);
  if (!res.ok) throw new Error(`${channel.name} 목록 실패 (HTTP ${res.status})`);
  const xml = await res.text();
  return [...xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)]
    .map(([, e]) => ({
    videoId: e.match(/<yt:videoId>([^<]+)/)?.[1],
    title: decode(e.match(/<title>([^<]*)/)?.[1]),
    published: e.match(/<published>([^<]+)/)?.[1],
    thumbnail: e.match(/<media:thumbnail url="([^"]+)"/)?.[1],
    views: Number(e.match(/<media:statistics views="(\d+)"/)?.[1]) || null,
    channelId: channel.id,
    channelName: channel.name,
  }))
    // 라이브 방송 다시보기(유튜브 자동 제목)는 자막이 없고 장면을 짚기 어려워 뺀다
    .filter((v) => v.videoId && !/^Live streaming of /i.test(v.title))
    .slice(0, limit);
}

function pickCaption(info) {
  const tracks = [
    ['자막', info.subtitles],
    ['자동 자막', info.automatic_captions],
  ];
  for (const [label, map] of tracks) {
    if (!map) continue;
    const key = ['ko-orig', 'ko'].find((k) => map[k]) || Object.keys(map).find((k) => /^ko(-|$)/.test(k));
    const fmt = key && map[key].find((f) => f.ext === 'json3');
    if (fmt) return { label, url: fmt.url };
  }
  return null;
}

async function fetchTranscript(track) {
  try {
    const res = await fetch(track.url);
    if (!res.ok) return '';
    const data = await res.json();
    return (data.events || [])
      .flatMap((e) => (e.segs || []).map((s) => s.utf8))
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
  } catch {
    return '';
  }
}

/** 영상 메타·자막·인기 댓글 */
export async function getVideoContext(videoId, { comments = true } = {}) {
  const args = ['-J', '--skip-download'];
  if (comments) args.push('--write-comments', '--extractor-args', 'youtube:comment_sort=top;max_comments=40,40,0,0');
  const info = JSON.parse(await ytdlp([...args, `https://www.youtube.com/watch?v=${videoId}`]));

  const track = pickCaption(info);
  const transcript = track ? await fetchTranscript(track) : '';
  const topComments = (info.comments || [])
    .filter((c) => !c.parent || c.parent === 'root')
    .sort((a, b) => (b.like_count || 0) - (a.like_count || 0))
    .slice(0, 20)
    .map((c) => String(c.text || '').slice(0, 200));

  return {
    videoId,
    title: info.title || '',
    description: (info.description || '').slice(0, 1500),
    channelId: info.channel_id,
    channelName: info.channel || info.uploader || '',
    thumbnail: info.thumbnail,
    views: info.view_count ?? null,
    timestamp: info.timestamp ?? null,
    transcript,
    sourceLabel: transcript ? track.label : '제목·설명',
    topComments,
  };
}

async function mapLimit(items, n, fn) {
  const out = [];
  let i = 0;
  await Promise.all(
    Array.from({ length: Math.min(n, items.length) }, async () => {
      while (i < items.length) {
        const k = i++;
        out[k] = await fn(items[k]).catch(() => null);
      }
    }),
  );
  return out;
}

/** '연애' 오늘 올라온 영상 중 막 뜨기 시작한 영상 (초안까지만) */
export async function findRising({ query, scan, minViews, maxViews, minVph }, now = Date.now()) {
  // 검색 필터 '오늘 업로드' (sp=EgIIAg==)
  const url = `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}&sp=EgIIAg%3D%3D`;
  const list = JSON.parse(await ytdlp(['-J', '--flat-playlist', '--playlist-end', String(scan), url]));
  const ids = (list.entries || [])
    .filter((e) => e.id && (e.view_count == null || (e.view_count >= minViews && e.view_count <= maxViews)))
    .map((e) => e.id);
  const infos = await mapLimit(ids, 4, async (id) =>
    JSON.parse(await ytdlp(['-J', '--skip-download', `https://www.youtube.com/watch?v=${id}`], 60_000)),
  );
  return infos
    .filter(Boolean)
    .map((v) => {
      const hours = Math.max((now / 1000 - (v.timestamp || now / 1000)) / 3600, 0.25);
      return {
        videoId: v.id,
        title: v.title,
        channelId: v.channel_id,
        channelName: v.channel || v.uploader,
        thumbnail: v.thumbnail,
        published: v.timestamp ? new Date(v.timestamp * 1000).toISOString() : null,
        views: v.view_count,
        viewsPerHour: Math.round((v.view_count || 0) / hours),
      };
    })
    .filter((v) => v.views >= minViews && v.views <= maxViews && v.viewsPerHour >= minVph)
    .sort((a, b) => b.viewsPerHour - a.viewsPerHour);
}
