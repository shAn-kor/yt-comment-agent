// 댓글 검증기. 생성된 초안과 사람이 고친 글 모두 게시 전에 여기를 통과해야 한다.

export const norm = (s) =>
  String(s ?? '')
    .normalize('NFC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]/gu, '');

export const countChars = (s) => [...String(s ?? '').trim()].length;

const LINK = /(https?:\/\/|www\.|[a-z0-9-]+\.(com|net|org|kr|co|me|io|ly|gg|link|site|shop)\b)/i;
const HASHTAG = /#[^\s#]/;
// 브랜드를 직접 이용해 본 것처럼 읽히는 표현 (브랜드가 들어간 문장에서만 검사)
const FAKE_USE =
  /(봤는데|봤더니|봤어요|봤음|봤다|받아\s?봤|받았는데|받았어|다녀왔|다녀옴|가\s?봤|상담\s?받|맞더라|맞았|맞추더|용하더|소름|후기)/;

function bigrams(s) {
  const n = norm(s);
  const set = new Set();
  for (let i = 0; i < n.length - 1; i++) set.add(n.slice(i, i + 2));
  return set;
}

export function similarity(a, b) {
  const A = bigrams(a);
  const B = bigrams(b);
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return inter / (A.size + B.size - inter);
}

// a의 부분 문자열 중 b에도 있는 가장 긴 것
export function longestCommon(a, b) {
  let best = '';
  for (let i = 0; i < a.length; i++) {
    for (let j = i + best.length + 1; j <= a.length; j++) {
      const sub = a.slice(i, j);
      if (b.includes(sub)) best = sub;
      else break;
    }
  }
  return best;
}

/**
 * @param {string} comment
 * @param {{source?: string, detail?: string, brand?: string, min?: number, max?: number, previous?: string[]}} opts
 *   source: 자막·제목·설명을 합친 글. detail: 모델이 인용했다고 밝힌 영상 속 표현.
 */
export function validateComment(comment, opts = {}) {
  const { source = '', detail = '', brand = '운명원', min = 40, max = 120, previous = [] } = opts;
  const text = String(comment ?? '').trim();
  const errors = [];
  const chars = countChars(text);

  if (chars < min || chars > max) errors.push(`글자 수 ${chars}자 (기준 ${min}~${max}자)`);

  const brandCount = text.split(brand).length - 1;
  if (brandCount === 0) errors.push(`"${brand}"이(가) 없음`);
  if (brandCount > 1) errors.push(`"${brand}"이(가) ${brandCount}번 나옴 (1번만)`);

  if (LINK.test(text)) errors.push('링크 금지');
  if (HASHTAG.test(text)) errors.push('해시태그 금지');

  const fake = text
    .split(/[.!?…\n]+/)
    .filter((s) => s.includes(brand))
    .map((s) => s.match(FAKE_USE))
    .find(Boolean);
  if (fake) errors.push(`${brand}을(를) 이용해 본 것처럼 읽힘 ("${fake[0]}")`);

  // 영상 속 장면·말: 모델이 밝힌 인용구가 원문과 댓글 모두에 있거나, 원문과 6자 이상 겹쳐야 한다
  const src = norm(source);
  const body = norm(text.split(brand).join(' '));
  const d = norm(detail);
  let anchor = '';
  if (d.length >= 3 && src.includes(d) && body.includes(d)) anchor = detail;
  else {
    const common = longestCommon(body, src);
    if (common.length >= 6) anchor = common;
  }
  if (!src) errors.push('영상 자료가 없어 장면 확인 불가');
  else if (!anchor) errors.push('영상 속 장면·말이 댓글에 없음');

  const dup = previous.find((p) => p && similarity(text, p) >= 0.5);
  if (dup) errors.push('이전 댓글과 너무 비슷함');

  return { ok: errors.length === 0, errors, chars, anchor };
}
