# 유튜브 댓글 에이전트 대시보드

지정 채널의 영상을 불러오고, AI가 영상 맥락에 맞는 댓글 초안을 쓰고, 버튼을 누르면 크롬 프로필이 열려 한 글자씩 입력해 게시하는 로컬 대시보드.

서버는 Python(FastAPI), 화면은 HTML·CSS·순수 JavaScript다.

## 준비

필요한 것: [uv](https://docs.astral.sh/uv/), Google Chrome, AI 하나 (아래 [AI 고르기](#ai-고르기)). 무료 모델로도 된다. Python과 라이브러리(yt-dlp 포함)는 uv가 설치한다.

```bash
uv sync                                   # Playwright 브라우저는 받지 않아도 된다 (설치된 Chrome 사용)
uv run python scripts/login.py 유튜브1     # 일반 Chrome이 열린다. 테스트용 구글 계정으로 로그인하고 창을 닫는다
```

`config.yaml`의 `test_videos`에 본인 테스트 영상 ID를 넣는다.

크롬 대신 ego 브라우저(ego lite, `ego-browser` 명령)에 로그인된 유튜브 계정으로 게시하려면 `config.yaml`의 `profiles`에 `- { name: 이고, browser: ego }`를 두면 된다. 이때는 `login.py`가 필요 없다.

선택: 프로젝트 폴더에 `.env` 파일을 만들면 아래 값을 읽는다.

| 이름                 | 뜻                                                       |
| -------------------- | -------------------------------------------------------- |
| `LLM_PROVIDER`       | `claude` · `gemini` · `groq` · `openrouter`. 비우면 자동 |
| `LLM_MODEL`          | 모델 이름. 비우면 아래 표의 기본 모델                    |
| `ANTHROPIC_API_KEY`  | Claude API 키. 없으면 로컬 `claude` CLI                  |
| `GEMINI_API_KEY`     | Gemini API 키                                            |
| `GROQ_API_KEY`       | Groq API 키                                              |
| `OPENROUTER_API_KEY` | OpenRouter API 키                                        |
| `CHROME_PATH`        | Chrome 실행 파일 경로 (macOS 기본 경로가 아닐 때)        |
| `PORT`               | 기본 4310                                                |

### AI 고르기

`LLM_PROVIDER`를 비우면 이 순서로 고른다: Claude API 키 → Gemini·Groq·OpenRouter 키 → 설치된 `claude` CLI. 아무것도 없으면 Gemini를 고르고, 무료 키 받는 곳을 오류 문구로 알려 준다.

| `LLM_PROVIDER` | 기본 모델                    | 비용·키                                                    | 준비                                                               |
| -------------- | ---------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------ |
| `gemini`       | `gemini-3.5-flash`           | 무료 등급 있음. 무료 등급 입력은 Google 제품 개선에 쓰인다 | [Google AI Studio](https://aistudio.google.com/apikey)에서 키 발급 |
| `groq`         | `openai/gpt-oss-120b`        | 무료 플랜: 분당 30회, 하루 1,000회, 분당 8,000토큰         | [Groq 콘솔](https://console.groq.com/keys)에서 키 발급             |
| `openrouter`   | `google/gemma-4-31b-it:free` | `:free` 모델은 무료. 하루 요청 수 제한 있음                | [OpenRouter](https://openrouter.ai/settings/keys)에서 키 발급      |
| `claude`       | `claude-sonnet-5-5`          | 유료 API 키 또는 `claude` CLI 로그인                       | 기존 방식 그대로                                                   |

예: Gemini 무료 키로 돌리기

```bash
echo "LLM_PROVIDER=gemini" >> .env
echo "GEMINI_API_KEY=발급받은-키" >> .env
```

**자동 대체**: Gemini를 쓰는데 `GROQ_API_KEY`도 있으면, Gemini가 429(무료 한도 초과)나 503(서버 혼잡)을 돌려줄 때 Groq `openai/gpt-oss-120b`로 넘어간다. Groq 무료는 분당 8,000토큰이라 이때는 자막을 앞 5,000자만 보낸다. 화면 위쪽 AI 표시에 "(한도 초과 시 Groq · …)"가 붙는다. Gemini 무료 3.5 Flash는 하루 20회라, 두 키를 같이 넣어 두면 하루 한도에 덜 막힌다.

```bash
echo "GROQ_API_KEY=발급받은-키" >> .env   # Gemini 설정에 더한다
```

무료 한도와 모델 이름은 2026-10-20에 공식 문서로 확인했다. 바뀔 수 있다. 무료 한도를 넘으면 오류 문구에 "무료 한도 초과일 수 있음"이 붙는다.

## 실행

```bash
uv run python -m agent.server   # http://localhost:4310
uv run pytest                   # 검사기·운영 규칙·API 테스트
```

## 쓰는 법

1. **영상 불러오기**: 5개 채널의 최신 영상이 뜬다. 링크를 붙여 넣으면 채널을 확인한 뒤 허용된 영상만 받는다.
2. **영상 선택**: 자막(없으면 제목·설명)과 인기 댓글 20개를 읽고 "영상 속 고민 한 줄"과 댓글 초안을 보여 준다. 초안은 고쳐도 되고, 고친 글도 다시 검사한다.
3. **댓글 달기**: 프로필을 고르거나 자동 배정을 두고 누른다. Chrome이 열리고 댓글창 → 한 글자씩 입력 → 게시 → 내 댓글 확인까지 화면에 보인다. 실패하면 이유와 화면 캡처가 기록에 남는다.

## 규칙 (서버에서 강제)

| 규칙                                                                                                                | 위치                                |
| ------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| 불러오기·초안: 지정 채널 영상 + 테스트 영상만. 링크 입력도 yt-dlp로 실제 채널을 확인                                | `agent/rules.py` `check_load_scope` |
| 게시: `posting_scope: test_only`(기본)면 테스트 영상만                                                              | `check_post_scope`                  |
| 영상 ID는 11자리 형식만 받고, yt-dlp가 돌려준 ID와 같아야 함                                                        | `agent/server.py`, `agent/youtube.py` |
| 영상당 1개 (계정과 상관없이. "확인 안 됨"도 게시된 것으로 셈)                                                        | `check_post`                        |
| 하루 상한 (기본 10개, 한국 시간 기준, 성공과 "확인 안 됨"을 셈)                                                      | `check_post`                        |
| 로그인된 프로필만 게시·자동 배정 (`login.py`를 실행했고, 그 뒤에 "로그인 안 됨"으로 실패하지 않은 프로필)            | `check_post`, `pick_profile`        |
| `localhost`·`127.0.0.1`로 연 화면의 요청만 받음 (다른 웹사이트·DNS 리바인딩 차단)                                    | `agent/server.py` `local_only`      |
| 게시는 한 번에 하나 (동시에 두 번 눌러도 하나만 진행)                                                                | `agent/server.py`                   |
| 뜨기 직전 영상은 초안까지만                                                                                         | `agent/server.py`                   |
| 댓글 검사: 40~120자, 운명원 1회, 링크·해시태그 금지, 이용 후기처럼 쓰기 금지, 영상 속 표현 포함, 이전 댓글과 다르게 | `agent/validate.py`                 |

차단된 시도도 이유와 함께 기록한다 (`data/agent.db`).

## 구조

```
agent/server.py     FastAPI 서버와 API
agent/youtube.py    채널 RSS(실패 시 yt-dlp), yt-dlp 라이브러리 (메타·자막·인기 댓글·검색)
agent/generate.py   프롬프트, 생성 → 검사 → 이유를 붙여 재생성 (최대 3회)
agent/llm.py        AI 연결 (Claude · Gemini · Groq · OpenRouter)
agent/validate.py   댓글 검증기
agent/rules.py      운영 규칙
agent/store.py      SQLite 기록
agent/poster.py     Playwright launch_persistent_context로 게시
agent/poster_ego.py ego 브라우저(ego-browser nodejs)로 게시
agent/config.py     config.yaml, .env 읽기
scripts/login.py    프로필 첫 로그인 (일반 Chrome)
public/             대시보드 화면
tests/              pytest
```

## 알려진 한계

- 유튜브 화면 구조가 바뀌면 `agent/poster.py`의 선택자를 고쳐야 한다.
- 새 계정의 댓글은 유튜브 스팸 필터에 걸려 다른 사람에게 안 보일 수 있다. 확인 단계는 "내 화면에서 보임" 기준이다.
- 채널 RSS가 다시 요청해도 실패하면 '동영상' 탭으로 받는다. 이때 올린 날짜는 "3일 전" 같은 표시에서 계산한 근삿값이다 (날짜 단위).

## 사용한 오픈소스

FastAPI (MIT), Uvicorn (BSD-3-Clause), HTTPX (BSD-3-Clause), PyYAML (MIT), Playwright (Apache-2.0), yt-dlp (Unlicense), Pretendard (OFL, CDN).

## 더 읽기

- [기능별 구현 설명](docs/IMPLEMENTATION.md)
- [할 일](TODO.md)
