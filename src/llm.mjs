import { spawn } from 'node:child_process';
import os from 'node:os';

export const backendName = () => (process.env.ANTHROPIC_API_KEY ? 'Claude API' : 'claude CLI');

/** 프롬프트 하나를 보내고 글을 받는다. 키가 있으면 API, 없으면 로컬 claude CLI. */
export async function complete(prompt) {
  const model = process.env.LLM_MODEL || '';
  if (process.env.ANTHROPIC_API_KEY) {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': process.env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: model || 'claude-sonnet-5-5',
        max_tokens: 1024,
        messages: [{ role: 'user', content: prompt }],
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(`Claude API 오류: ${data.error?.message || res.status}`);
    return data.content.filter((b) => b.type === 'text').map((b) => b.text).join('');
  }

  return new Promise((resolve, reject) => {
    const args = ['-p', '--output-format', 'text', ...(model ? ['--model', model] : [])];
    // 프로젝트 지침을 읽지 않도록 임시 폴더에서 실행
    const child = spawn(process.env.CLAUDE_CLI || 'claude', args, { cwd: os.tmpdir(), stdio: ['pipe', 'pipe', 'pipe'] });
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error('claude CLI 시간 초과 (180초)'));
    }, 180_000);
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => (err += d));
    child.on('error', (e) => {
      clearTimeout(timer);
      reject(new Error(`claude CLI 실행 실패: ${e.message}`));
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) resolve(out);
      else reject(new Error(`claude CLI 오류 (${code}): ${err.slice(-300)}`));
    });
    child.stdin.end(prompt);
  });
}
