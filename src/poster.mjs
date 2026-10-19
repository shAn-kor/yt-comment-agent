import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

export class PostError extends Error {
  constructor(message, screenshot) {
    super(message);
    this.screenshot = screenshot;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * 크롬 프로필을 화면에 띄우고 한 글자씩 입력해 댓글을 게시한 뒤, 내 댓글이 보이는지 확인한다.
 * 유튜브 한국어 화면(hl=ko) 기준.
 */
export async function postComment({ profileDir, videoId, text, shotDir, onStatus = () => {} }) {
  mkdirSync(shotDir, { recursive: true });
  const shot = async (page, tag) => {
    const file = `${Date.now()}-${videoId}-${tag}.png`;
    await page.screenshot({ path: path.join(shotDir, file) }).catch(() => {});
    return file;
  };

  onStatus('프로필 여는 중');
  const ctx = await chromium.launchPersistentContext(profileDir, {
    channel: process.env.CHROME_PATH ? undefined : 'chrome',
    executablePath: process.env.CHROME_PATH || undefined,
    headless: false,
    viewport: null,
    locale: 'ko-KR',
    args: ['--lang=ko-KR', '--window-size=1280,900'],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());

  try {
    onStatus('영상 여는 중');
    await page.goto(`https://www.youtube.com/watch?v=${videoId}&hl=ko`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('ytd-watch-flexy', { timeout: 30_000 });

    const signedOut = await page.locator('ytd-masthead a[href*="accounts.google.com/ServiceLogin"]').first().isVisible().catch(() => false);
    if (signedOut) throw new PostError(`로그인 안 됨 — npm run login -- <프로필 이름> 으로 먼저 로그인하세요`, await shot(page, 'signed-out'));

    onStatus('댓글창 찾는 중');
    const placeholder = page.locator('ytd-comments ytd-comment-simplebox-renderer #placeholder-area');
    for (let i = 0; i < 15 && !(await placeholder.count()); i++) {
      if (await page.locator('ytd-comments ytd-message-renderer').isVisible().catch(() => false)) {
        throw new PostError('댓글 사용이 중지된 영상', await shot(page, 'comments-off'));
      }
      await page.mouse.wheel(0, 700);
      await sleep(800);
    }
    if (!(await placeholder.count())) throw new PostError('댓글 입력창을 찾지 못함', await shot(page, 'no-box'));
    await placeholder.scrollIntoViewIfNeeded();
    await placeholder.click();

    const box = page.locator('ytd-commentbox #contenteditable-root');
    await box.waitFor({ state: 'visible', timeout: 10_000 });
    await box.click();

    onStatus('입력 중');
    for (const ch of text) {
      await page.keyboard.type(ch);
      await sleep(60 + Math.random() * 110);
    }
    await sleep(600);

    onStatus('게시 중');
    await page.locator('ytd-commentbox #submit-button button, ytd-commentbox #submit-button').first().click();

    onStatus('내 댓글 확인 중');
    const head = text.slice(0, 18);
    const mine = page
      .locator('ytd-comment-thread-renderer')
      .filter({ has: page.locator('#content-text', { hasText: head }) })
      .first();
    await mine.waitFor({ state: 'visible', timeout: 20_000 }).catch(async () => {
      throw new PostError('게시 후 내 댓글이 보이지 않음', await shot(page, 'not-visible'));
    });
    await mine.scrollIntoViewIfNeeded();

    const href = await mine.locator('#published-time-text a').first().getAttribute('href').catch(() => null);
    const commentUrl = href ? new URL(href, 'https://www.youtube.com').toString() : `https://www.youtube.com/watch?v=${videoId}`;
    const screenshot = await shot(page, 'posted');
    onStatus('게시 완료');
    await sleep(2500); // 시연 화면에서 결과를 볼 시간
    return { commentUrl, screenshot };
  } catch (e) {
    if (e instanceof PostError) throw e;
    throw new PostError(e.message.split('\n')[0], await shot(page, 'error'));
  } finally {
    await ctx.close().catch(() => {});
  }
}
