// 운영 규칙. 게시 직전에 서버에서 검사한다 (화면에서 버튼을 숨기는 것과 별개).

export const kstDate = (t = Date.now()) => new Date(t + 9 * 3600e3).toISOString().slice(0, 10);

const fail = (reason) => ({ ok: false, reason });

/** 불러오기·초안 허용 범위: 지정 채널 영상 또는 본인 테스트 영상 */
export function checkLoadScope(video, config) {
  if (config.testVideos.includes(video.videoId)) return { ok: true, kind: 'test' };
  if (config.channels.some((c) => c.id === video.channelId)) return { ok: true, kind: 'channel' };
  return fail('허용 범위 밖 채널');
}

/** 게시 허용 범위: test_only면 테스트 영상만 */
export function checkPostScope(video, config) {
  if (config.testVideos.includes(video.videoId)) return { ok: true, kind: 'test' };
  if (config.postingScope !== 'channels') return fail('테스트 모드: 본인 테스트 영상에만 게시');
  return checkLoadScope(video, config);
}

/**
 * @param {{video: {videoId: string, channelId: string}, profile: string}} req
 * @param {{hasSuccess(id: string): boolean, countSuccessOn(day: string): number}} store
 */
export function checkPost({ video, profile }, config, store, now = Date.now()) {
  if (!config.profiles.some((p) => p.name === profile)) return fail(`설정에 없는 프로필 (${profile})`);
  const scope = checkPostScope(video, config);
  if (!scope.ok) return scope;
  if (store.hasSuccess(video.videoId)) return fail('이미 댓글을 단 영상 (영상당 1개)');
  const used = store.countSuccessOn(kstDate(now));
  if (used >= config.limits.dailyMax) return fail(`오늘 게시 상한 ${config.limits.dailyMax}개 도달`);
  return { ok: true };
}

/** 자동 배정: 가장 오래 안 쓴 프로필 */
export function pickProfile(config, lastUsed) {
  return [...config.profiles].sort((a, b) => lastUsed(a.name) - lastUsed(b.name))[0]?.name;
}
