"""
에러/성공 이벤트를 로컬 파일에 영구 기록.
exe로 배포된 환경은 콘솔이 없고 서버 로그도 없어서, print()나 UI 로그창만으로는
사용자에게 실제로 어떤 오류가 발생했는지 알 수 없다. 사용자가 보내주는
%LOCALAPPDATA%\\D2RTracker\\logs\\ERROR.LOG / SUCCESS.LOG 로 재현·진단한다.
"""
import os
import traceback
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) \
    / "D2RTracker" / "logs"
_ERROR_LOG = _LOG_DIR / "ERROR.LOG"
_SUCCESS_LOG = _LOG_DIR / "SUCCESS.LOG"

_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5MB 초과 시 앞부분을 잘라 무한 증식 방지


def _write(path: Path, text: str):
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _MAX_LOG_BYTES:
            kept = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-2000:]
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass  # 로그 기록 실패가 앱 동작에 영향을 주면 안 됨


def log_error(context: str, exc: Exception = None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {context}"
    if exc is not None:
        line += f" | {exc!r}\n"
        line += "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        line += "\n"
    _write(_ERROR_LOG, line)


def log_success(context: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write(_SUCCESS_LOG, f"[{ts}] {context}\n")


def get_log_dir() -> Path:
    return _LOG_DIR
