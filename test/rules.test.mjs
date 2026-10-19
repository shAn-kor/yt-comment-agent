import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { checkLoadScope, checkPost, kstDate, pickProfile } from '../src/rules.mjs';
import { openStore } from '../src/store.mjs';
import { parseVideoId } from '../src/youtube.mjs';

const base = {
  profiles: [{ name: '유튜브1' }, { name: '유튜브2' }],
  channels: [{ id: 'UCallowed', name: '허용 채널' }],
  testVideos: ['testVideo01'],
  postingScope: 'test_only',
  limits: { dailyMax: 2 },
};
const channelVideo = { videoId: 'chanVideo01', channelId: 'UCallowed' };
const testVideo = { videoId: 'testVideo01', channelId: 'UCmine' };
const outside = { videoId: 'otherVid001', channelId: 'UCother' };
const emptyStore = { hasSuccess: () => false, countSuccessOn: () => 0 };

test('불러오기 범위: 지정 채널과 테스트 영상만', () => {
  assert.equal(checkLoadScope(channelVideo, base).ok, true);
  assert.equal(checkLoadScope(testVideo, base).ok, true);
  assert.equal(checkLoadScope(outside, base).ok, false);
});

test('테스트 모드에서는 테스트 영상에만 게시', () => {
  assert.equal(checkPost({ video: testVideo, profile: '유튜브1' }, base, emptyStore).ok, true);
  assert.match(checkPost({ video: channelVideo, profile: '유튜브1' }, base, emptyStore).reason, /테스트 모드/);
  const open = { ...base, postingScope: 'channels' };
  assert.equal(checkPost({ video: channelVideo, profile: '유튜브1' }, open, emptyStore).ok, true);
  assert.equal(checkPost({ video: outside, profile: '유튜브1' }, open, emptyStore).ok, false);
});

test('설정에 없는 프로필 차단', () => {
  assert.match(checkPost({ video: testVideo, profile: '유튜브9' }, base, emptyStore).reason, /프로필/);
});

test('영상당 1개 · 하루 상한 (SQLite 기록 기준)', () => {
  const store = openStore(path.join(mkdtempSync(path.join(os.tmpdir(), 'yca-')), 't.db'));
  const cfg = { ...base, testVideos: ['testVideo01', 'testVideo02', 'testVideo03'] };
  store.add({ videoId: 'testVideo01', profile: '유튜브1', status: 'success' });
  assert.match(checkPost({ video: { videoId: 'testVideo01' }, profile: '유튜브2' }, cfg, store).reason, /영상당 1개/);
  store.add({ videoId: 'testVideo02', profile: '유튜브1', status: 'failed' });
  assert.equal(checkPost({ video: { videoId: 'testVideo02' }, profile: '유튜브1' }, cfg, store).ok, true);
  store.add({ videoId: 'testVideo02', profile: '유튜브1', status: 'success' });
  assert.match(checkPost({ video: { videoId: 'testVideo03' }, profile: '유튜브1' }, cfg, store).reason, /상한/);
  // 다음 날에는 다시 가능
  const tomorrow = Date.now() + 24 * 3600e3;
  assert.equal(checkPost({ video: { videoId: 'testVideo03' }, profile: '유튜브1' }, cfg, store, tomorrow).ok, true);
});

test('자동 배정은 가장 오래 안 쓴 프로필', () => {
  const used = { 유튜브1: 200, 유튜브2: 100 };
  assert.equal(pickProfile(base, (n) => used[n] || 0), '유튜브2');
});

test('한국 시간 날짜', () => {
  assert.equal(kstDate(Date.UTC(2026, 9, 19, 15, 30)), '2026-10-20');
});

test('영상 링크 파싱', () => {
  assert.equal(parseVideoId('https://youtu.be/akn-AvCeHBI'), 'akn-AvCeHBI');
  assert.equal(parseVideoId('https://www.youtube.com/watch?v=JjY09DSdzx0&t=3'), 'JjY09DSdzx0');
  assert.equal(parseVideoId('https://www.youtube.com/shorts/DvxMfC_KjX0'), 'DvxMfC_KjX0');
  assert.equal(parseVideoId('https://example.com/watch?v=xx'), null);
});
