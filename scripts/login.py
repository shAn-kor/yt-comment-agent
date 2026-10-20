"""프로필 폴더로 일반 Chrome을 띄운다. 사람이 직접 구글에 로그인하면 이후 대시보드가 그 프로필을 쓴다.
자동 제어 창에서는 구글 로그인이 막힐 수 있어서 이 방식을 쓴다.

    uv run python scripts/login.py 유튜브1
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.config import LOGIN_MARK, load_config, load_env  # noqa: E402

load_env()
config = load_config()
name = sys.argv[1] if len(sys.argv) > 1 else config.profiles[0].name
profile = next((p for p in config.profiles if p.name == name), None)
if not profile:
    sys.exit(
        f'프로필 "{name}"이 config.yaml에 없습니다. 있는 프로필: {", ".join(p.name for p in config.profiles)}'
    )

chrome = os.environ.get(
    "CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
profile.dir.mkdir(parents=True, exist_ok=True)
# 대시보드는 이 표시가 있는 프로필만 "준비됨"으로 본다. 이 뒤에 "로그인 안 됨"으로 실패하면 다시 로그인 필요로 바뀐다
(profile.dir / LOGIN_MARK).touch()
subprocess.Popen(
    [
        chrome,
        f"--user-data-dir={profile.dir}",
        "--lang=ko-KR",
        "--no-first-run",
        "--no-default-browser-check",
        "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fwww.youtube.com%2F%3Fhl%3Dko",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
print(f"{name} 창을 열었습니다 ({profile.dir}).")
print(
    "테스트용 구글 계정으로 로그인하고, 유튜브 채널이 있는지 확인한 뒤 창을 닫으세요."
)
