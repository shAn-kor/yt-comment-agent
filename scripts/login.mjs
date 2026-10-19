// 프로필 폴더로 일반 Chrome을 띄운다. 사람이 직접 구글에 로그인하면 이후 대시보드가 그 프로필을 쓴다.
// 자동 제어 창에서는 구글 로그인이 막힐 수 있어서 이 방식을 쓴다.
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { loadConfig, loadEnv } from '../src/config.mjs';

loadEnv();
const config = loadConfig();
const name = process.argv[2] || config.profiles[0]?.name;
const profile = config.profiles.find((p) => p.name === name);
if (!profile) {
  console.error(`프로필 "${name}"이 config.yaml에 없습니다. 있는 프로필: ${config.profiles.map((p) => p.name).join(', ')}`);
  process.exit(1);
}

const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
mkdirSync(profile.dir, { recursive: true });
spawn(
  chrome,
  [
    `--user-data-dir=${profile.dir}`,
    '--lang=ko-KR',
    '--no-first-run',
    '--no-default-browser-check',
    'https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fwww.youtube.com%2F%3Fhl%3Dko',
  ],
  { stdio: 'ignore', detached: true },
).unref();

console.log(`${name} 창을 열었습니다 (${profile.dir}).`);
console.log('테스트용 구글 계정으로 로그인하고, 유튜브 채널이 있는지 확인한 뒤 창을 닫으세요.');
