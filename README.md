# 유튜브 댓글 에이전트 대시보드

지정 채널의 영상을 불러오고, AI가 영상 맥락에 맞는 댓글 초안을 쓰고, 버튼을 누르면 크롬 프로필이 열려 한 글자씩 입력해 게시하는 로컬 대시보드.

## 준비

필요한 것: Node.js 22.5 이상 (내장 SQLite), Google Chrome, `yt-dlp`, AI 하나 (`claude` CLI 로그인 또는 Anthropic API 키).

```bash
npm install            # Playwright 브라우저는 받지 않아도 된다 (설치된 Chrome 사용)
npm run login -- 유튜브1   # 일반 Chrome이 열린다. 테스트용 구글 계정으로 로그인하고 창을 닫는다
```

`config.yaml`의 `test_videos`에 본인 테스트 영상 ID를 넣는다.

선택: 프로젝트 폴더에 `.env` 파일을 만들면 아래 값을 읽는다.

| 이름                | 뜻                                                |
| ------------------- | ------------------------------------------------- |
| `ANTHROPIC_API_KEY` | 있으면 Claude API, 없으면 로컬 `claude` CLI       |
| `LLM_MODEL`         | 모델 이름 (API 기본값 `claude-sonnet-5-5`)        |
| `CHROME_PATH`       | Chrome 실행 파일 경로 (macOS 기본 경로가 아닐 때) |
| `PORT`              | 기본 4310                                         |

## 실행

```bash
npm start              # http://localhost:4310
npm test               # 검증기·운영 규칙 단위 테스트
```

## 쓰는 법

1. **영상 불러오기**: 5개 채널의 최신 영상이 뜬다. 링크를 붙여 넣으면 채널을 확인한 뒤 허용된 영상만 받는다.
2. **영상 선택**: 자막(없으면 제목·설명)과 인기 댓글 20개를 읽고 "영상 속 고민 한 줄"과 댓글 초안을 보여 준다. 초안은 고쳐도 되고, 고친 글도 다시 검사한다.
3. **댓글 달기**: 프로필을 고르거나 자동 배정을 두고 누른다. Chrome이 열리고 댓글창 → 한 글자씩 입력 → 게시 → 내 댓글 확인까지 화면에 보인다. 실패하면 이유와 화면 캡처가 기록에 남는다.

## 규칙 (서버에서 강제)

| 규칙                                                                                                                | 위치                             |
| ------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| 불러오기·초안: 지정 채널 영상 + 테스트 영상만. 링크 입력도 yt-dlp로 실제 채널을 확인                                | `src/rules.mjs` `checkLoadScope` |
| 게시: `posting_scope: test_only`(기본)면 테스트 영상만                                                              | `checkPostScope`                 |
| 영상당 1개 (계정과 상관없이)                                                                                        | `checkPost`                      |
| 하루 상한 (기본 10개, 한국 시간 기준, 성공만 셈)                                                                    | `checkPost`                      |
| 뜨기 직전 영상은 초안까지만                                                                                         | `src/server.mjs`                 |
| 댓글 검사: 40~120자, 운명원 1회, 링크·해시태그 금지, 이용 후기처럼 쓰기 금지, 영상 속 표현 포함, 이전 댓글과 다르게 | `src/validate.mjs`               |

차단된 시도도 이유와 함께 기록한다 (`data/agent.db`).

## 구조

```
src/server.mjs     로컬 서버와 API
src/youtube.mjs    채널 RSS, yt-dlp(메타·자막·인기 댓글·검색)
src/generate.mjs   프롬프트, 생성 → 검사 → 이유를 붙여 재생성 (최대 3회)
src/validate.mjs   댓글 검증기
src/rules.mjs      운영 규칙
src/store.mjs      SQLite 기록
src/poster.mjs     Playwright launchPersistentContext로 게시
scripts/login.mjs  프로필 첫 로그인 (일반 Chrome)
public/            대시보드 화면
```

## 알려진 한계

- 유튜브 화면 구조가 바뀌면 `src/poster.mjs`의 선택자를 고쳐야 한다.
- 새 계정의 댓글은 유튜브 스팸 필터에 걸려 다른 사람에게 안 보일 수 있다. 확인 단계는 "내 화면에서 보임" 기준이다.
- 라이브 방송 다시보기("Live streaming of …")는 목록에서 뺀다.

## 사용한 오픈소스

Playwright (Apache-2.0), yaml (ISC), yt-dlp (Unlicense, 외부 실행), Pretendard (OFL, CDN).

## 더 읽기

- [기능별 구현 설명](docs/IMPLEMENTATION.md)
