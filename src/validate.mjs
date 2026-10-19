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

// 정규화된 조각을 원문에서 다시 찾는다 (공백·문장부호를 건너뛰며). 미리보기 강조용.
function locate(text, normalized) {
  if (!normalized) return '';
  const parts = [...normalized].map((c) => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const m = text.match(new RegExp(parts.join('[^\\p{L}\\p{N}]*'), 'iu'));
  return m ? m[0] : '';
}

/**
 * @param {string} comment
 * @param {{source?: string, detail?: string, brand?: string, min?: number, max?: number, previous?: string[]}} opts
 *   source: 자막·제목·설명을 합친 글. detail: 모델이 인용했다고 밝힌 영상 속 표현.
 */
export function validateComment(comment, opts = {}) {
  const { source = '', detail = '', brand = '운명원', min = 40, max = 120, previous = [] } = opts;
  const text = String(comment ?? '').trim();
  const chars = countChars(text);
  const checks = [];
  const add = (key, label, ok, note = '') => checks.push({ key, label, ok, note });

  add('length', `${min}~${max}자`, chars >= min && chars <= max, `글자 수 ${chars}자 (기준 ${min}~${max}자)`);

  const brandCount = text.split(brand).length - 1;
  const brandNote =
    brandCount === 0 ? `"${brand}"이(가) 없음` : brandCount > 1 ? `"${brand}"이(가) ${brandCount}번 나옴 (1번만)` : '';
  add('brand', `"${brand}" 한 번`, brandCount === 1, brandNote);

  const link = LINK.test(text);
  const tag = HASHTAG.test(text);
  add('link', '링크·해시태그 없음', !link && !tag, [link && '링크 금지', tag && '해시태그 금지'].filter(Boolean).join(', '));

  const fake = text
    .split(/[.!?…\n]+/)
    .filter((s) => s.includes(brand))
    .map((s) => s.match(FAKE_USE))
    .find(Boolean);
  add('fake', '이용 후기처럼 쓰지 않음', !fake, fake ? `${brand}을(를) 이용해 본 것처럼 읽힘 ("${fake[0]}")` : '');

  // 영상 속 장면·말: 모델이 밝힌 인용구가 원문과 댓글 모두에 있거나, 원문과 6자 이상 겹쳐야 한다
  const src = norm(source);
  const body = norm(text.split(brand).join(' '));
  const d = norm(detail);
  let anchor = '';
  if (d.length >= 3 && src.includes(d) && body.includes(d)) anchor = locate(text, d) || detail;
  else {
    const common = longestCommon(body, src);
    if (common.length >= 6) anchor = locate(text, common) || common;
  }
  const anchorNote = !src ? '영상 자료가 없어 장면 확인 불가' : anchor ? '' : '영상 속 장면·말이 댓글에 없음';
  add('anchor', '영상 속 장면·말 포함', !!src && !!anchor, anchorNote);

  const dup = previous.find((p) => p && similarity(text, p) >= 0.5);
  add('unique', '이전 댓글과 다름', !dup, dup ? '이전 댓글과 너무 비슷함' : '');

  const errors = checks.filter((c) => !c.ok).map((c) => c.note);
  return { ok: errors.length === 0, errors, checks, chars, anchor };
}
