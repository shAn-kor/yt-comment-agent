import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildPrompt, draftComment, parseJson } from '../src/generate.mjs';
import { countChars, similarity, validateComment } from '../src/validate.mjs';

const source = '남자가 연락을 줄이는 진짜 이유. 남자는 확신이 없으면 연락 빈도부터 줄입니다. 읽씹은 관심이 식었다는 신호일 수 있어요.';
const good =
  '확신이 없으면 연락 빈도부터 줄인다는 말 듣고 뜨끔했다ㅠㅠ 나도 맨날 혼자 기다리기만 했는데. 운명원 연애사주가 그렇게 잘 본다던데 내 인연은 언제 오는지 궁금하다';
const opts = { source, detail: '연락 빈도부터 줄', brand: '운명원', min: 40, max: 120 };

test('조건을 다 지키면 통과', () => {
  const v = validateComment(good, opts);
  assert.equal(v.ok, true, v.errors.join(', '));
  assert.ok(v.anchor);
});

test('글자 수 범위', () => {
  assert.match(validateComment('운명원 궁금하다', opts).errors.join(), /글자 수/);
  assert.match(validateComment(good + good, opts).errors.join(), /글자 수/);
  assert.equal(countChars('ㅠㅠ 가나'), 5);
});

test('브랜드는 정확히 한 번', () => {
  const none = good.replace('운명원', '그곳');
  assert.match(validateComment(none, opts).errors.join(), /없음/);
  const twice = good.replace('궁금하다', '운명원 궁금하다');
  assert.match(validateComment(twice, opts).errors.join(), /2번/);
});

test('링크와 해시태그 금지', () => {
  assert.match(validateComment(good.replace('궁금하다', 'unmyeong.com 궁금'), opts).errors.join(), /링크/);
  assert.match(validateComment(good.replace('궁금하다', '#연애사주'), opts).errors.join(), /해시태그/);
});

test('운명원 이용 후기처럼 쓰면 차단', () => {
  const fake = good.replace('잘 본다던데 내 인연은 언제 오는지 궁금하다', '받아봤는데 진짜 소름 돋게 맞더라');
  assert.match(validateComment(fake, opts).errors.join(), /이용해 본 것처럼/);
});

test('브랜드 없는 문장의 "봤는데"는 허용 (영상 시청)', () => {
  const watched = good.replace('말 듣고', '말 영상으로 봤는데');
  assert.equal(validateComment(watched, opts).ok, true, validateComment(watched, opts).errors.join());
});

test('영상 속 표현이 없으면 차단', () => {
  const generic = '연애는 정말 어렵다ㅠㅠ 나만 이렇게 힘든가 싶어서 오늘도 한숨만 쉬었다. 운명원 연애사주 잘 본다던데 나도 언젠가 꼭 한번 보고 싶다';
  const v = validateComment(generic, { ...opts, detail: '없는 말' });
  assert.match(v.errors.join(), /장면/);
});

test('이전 댓글과 비슷하면 차단', () => {
  const v = validateComment(good, { ...opts, previous: [good.replace('궁금하다', '궁금함')] });
  assert.match(v.errors.join(), /비슷/);
  assert.ok(similarity('가나다라', '마바사아') < 0.1);
});

test('AI 응답 JSON 파싱', () => {
  const j = parseJson('설명 {"concern":"고민","detail":"말","comment":"댓글"} 끝');
  assert.deepEqual(j, { concern: '고민', detail: '말', comment: '댓글' });
});

test('검증 실패 시 이유를 붙여 다시 생성', async () => {
  const prompts = [];
  const answers = [
    JSON.stringify({ concern: '연락 고민', detail: '없는 말', comment: '짧음' }),
    JSON.stringify({ concern: '연락 고민', detail: '연락 빈도부터 줄', comment: good }),
  ];
  const ctx = { title: '남자가 연락을 줄이는 진짜 이유', description: '', transcript: source, sourceLabel: '자막', channelName: '테스트', topComments: [] };
  const draft = await draftComment(ctx, { brand: '운명원', min: 40, max: 120 }, async (p) => {
    prompts.push(p);
    return answers[prompts.length - 1];
  });
  assert.equal(draft.attempts, 2);
  assert.equal(draft.validation.ok, true);
  assert.match(prompts[1], /지난 시도의 문제/);
  assert.match(buildPrompt(ctx, { brand: '운명원', min: 40, max: 120 }), /운명원/);
});
