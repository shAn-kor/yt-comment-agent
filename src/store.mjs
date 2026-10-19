import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { kstDate } from './rules.mjs';

export function openStore(file) {
  mkdirSync(path.dirname(file), { recursive: true });
  const db = new DatabaseSync(file);
  db.exec(`CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    day TEXT NOT NULL,
    video_id TEXT, video_title TEXT, channel_id TEXT, channel_name TEXT,
    profile TEXT, comment TEXT,
    status TEXT NOT NULL,          -- success | failed | blocked
    reason TEXT, screenshot TEXT, comment_url TEXT
  )`);

  const insert = db.prepare(`INSERT INTO logs
    (ts, day, video_id, video_title, channel_id, channel_name, profile, comment, status, reason, screenshot, comment_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);

  return {
    add(row, now = Date.now()) {
      insert.run(
        now, kstDate(now),
        row.videoId ?? null, row.title ?? null, row.channelId ?? null, row.channelName ?? null,
        row.profile ?? null, row.comment ?? null,
        row.status, row.reason ?? null, row.screenshot ?? null, row.commentUrl ?? null,
      );
    },
    hasSuccess: (videoId) =>
      !!db.prepare(`SELECT 1 FROM logs WHERE video_id = ? AND status = 'success' LIMIT 1`).get(videoId),
    countSuccessOn: (day) =>
      db.prepare(`SELECT COUNT(*) AS n FROM logs WHERE day = ? AND status = 'success'`).get(day).n,
    commentedIds: () =>
      new Set(db.prepare(`SELECT video_id FROM logs WHERE status = 'success'`).all().map((r) => r.video_id)),
    previousComments: (n = 30, exceptVideoId = '') =>
      db.prepare(`SELECT comment FROM logs WHERE status = 'success' AND video_id IS NOT ? ORDER BY ts DESC LIMIT ?`).all(exceptVideoId, n).map((r) => r.comment),
    lastUsed: (profile) =>
      db.prepare(`SELECT MAX(ts) AS t FROM logs WHERE profile = ? AND status IN ('success','failed')`).get(profile).t || 0,
    list: (limit = 200) => db.prepare(`SELECT * FROM logs ORDER BY ts DESC LIMIT ?`).all(limit),
  };
}
