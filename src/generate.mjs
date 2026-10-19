import { complete } from './llm.mjs';
import { validateComment } from './validate.mjs';

export const sourceText = (ctx) => [ctx.title, ctx.description, ctx.transcript].join('\n');

export function buildPrompt(ctx, { brand, min, max, previous = [], feedback = [] }) {
  const lines = [
    '너는 유튜브 연애 영상을 방금 끝까지 본 한국인 시청자다. 아래 영상 자료를 읽고 두 가지를 순서대로 해라.',
    '',
    '1) concern: 이 영상이 다루는 연애 고민을 한 문장(40자 이내)으로 정리한다.',
    '2) comment: 이 영상을 본 시청자로서 남길 유튜브 댓글 하나를 쓴다.',
    '',
    '댓글 규칙',
    `- 공백 포함 ${min}~${max}자.`,
    '- 영상 속 구체적인 말이나 장면을 하나 짚는다. 그 표현(detail)은 자막·제목·설명에 실제로 있는 말을 3~15자 그대로 가져오고, 댓글 안에도 글자 그대로 넣는다.',
    '- 그 고민에 공감하는 짧은 본인 이야기나 감정을 섞어 진짜 시청자처럼 쓴다. 구어체, "ㅠㅠ" "ㅋㅋ" 정도는 괜찮다.',
    `- 끝부분에서 "${brand}"을 딱 한 번 자연스럽게 꺼내, 읽는 사람이 ${brand}에서 연애 사주를 보고 싶어지게 한다. ${brand}은 "연애 사주 잘 본다고 소문난 곳"이다.`,
    `- ${brand}을 직접 이용해 본 것처럼 쓰지 않는다 (봤다, 받아봤다, 맞더라, 다녀왔다, 후기 같은 말 금지). "궁금하다", "보고 싶다", "소문 들었다"처럼 기대·관심만 표현한다.`,
    '- 링크, 해시태그, 광고 문구 금지.',
    '- 아래 "이미 쓴 댓글"과 표현·구성이 겹치지 않게 쓴다.',
    '',
    '출력: 다른 말 없이 JSON 하나만.',
    '{"concern": "...", "detail": "...", "comment": "..."}',
    '',
    `[제목] ${ctx.title}`,
    `[채널] ${ctx.channelName}`,
    `[설명] ${ctx.description || '(없음)'}`,
    `[${ctx.sourceLabel}] ${ctx.transcript ? ctx.transcript.slice(0, 7000) : '(자막 없음 — 제목과 설명만 사용)'}`,
    '[인기 댓글]',
    ...(ctx.topComments.length ? ctx.topComments.map((c) => `- ${c}`) : ['- (없음)']),
    '[이미 쓴 댓글]',
    ...(previous.length ? previous.slice(0, 10).map((c) => `- ${c}`) : ['- (없음)']),
  ];
  if (feedback.length) lines.push('[지난 시도의 문제 — 꼭 고칠 것]', ...feedback.map((f) => `- ${f}`));
  return lines.join('\n');
}

export function parseJson(raw) {
  const m = String(raw).match(/\{[\s\S]*\}/);
  if (!m) throw new Error('AI 응답에서 JSON을 찾지 못함');
  const j = JSON.parse(m[0]);
  return { concern: String(j.concern ?? '').trim(), detail: String(j.detail ?? '').trim(), comment: String(j.comment ?? '').trim() };
}

/** 생성 → 검증 → 실패하면 이유를 붙여 다시 생성 (최대 3번) */
export async function draftComment(ctx, { brand, min, max, previous = [] }, llm = complete) {
  let last = null;
  let feedback = [];
  for (let attempt = 1; attempt <= 3; attempt++) {
    let parsed;
    try {
      parsed = parseJson(await llm(buildPrompt(ctx, { brand, min, max, previous, feedback })));
    } catch (e) {
      if (attempt === 3) throw e;
      feedback = ['JSON 형식으로만 답할 것'];
      continue;
    }
    const validation = validateComment(parsed.comment, {
      source: sourceText(ctx), detail: parsed.detail, brand, min, max, previous,
    });
    last = { ...parsed, validation, attempts: attempt };
    if (validation.ok) break;
    feedback = validation.errors;
  }
  return last;
}
