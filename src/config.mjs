import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// .env를 읽어 process.env에 없는 값만 채운다
export function loadEnv(file = path.join(ROOT, '.env')) {
  if (!existsSync(file)) return;
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && m[2] && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

export function loadConfig(file = path.join(ROOT, 'config.yaml')) {
  const raw = YAML.parse(readFileSync(file, 'utf8')) || {};
  const comment = raw.comment || {};
  const limits = raw.limits || {};
  const rising = raw.rising || {};
  const scope = raw.posting_scope === 'channels' ? 'channels' : 'test_only';
  return {
    profiles: (raw.profiles || []).map((p) =>
      typeof p === 'string'
        ? { name: p, dir: path.join(ROOT, 'profiles', p) }
        : { name: p.name, dir: path.resolve(ROOT, p.dir || path.join('profiles', p.name)) },
    ),
    channels: (raw.channels || []).map((c) => (typeof c === 'string' ? { id: c, name: c } : c)),
    testVideos: (raw.test_videos || []).map(String),
    postingScope: scope,
    comment: {
      min: comment.min_chars ?? 40,
      max: comment.max_chars ?? 120,
      brand: comment.brand ?? '운명원',
    },
    limits: {
      dailyMax: limits.daily_max_comments ?? 10,
      perChannel: limits.videos_per_channel ?? 5,
    },
    rising: {
      query: rising.query ?? '연애',
      scan: rising.scan ?? 30,
      minViews: rising.min_views ?? 1000,
      maxViews: rising.max_views ?? 5000,
      minVph: rising.min_views_per_hour ?? 150,
    },
  };
}
