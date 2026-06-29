"""
GitHub에서 아이템 데이터를 다운로드·캐시
'모든 기초데이터는 git에서 정보를 가져온다'

우선순위:
  1. RUNTIME_DIR/data/   (GitHub에서 다운받은 최신 데이터)
  2. _internal/backend_data/ 또는 backend/data/  (번들·개발 fallback)
"""
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Callable

from config import GITHUB_DATA_URL, GITHUB_DATA_FILES

GITHUB_RAW_BASE = GITHUB_DATA_URL
DATA_FILES      = GITHUB_DATA_FILES

_VERSION_FILE = "data_version.json"


# ── 상태 조회 ──────────────────────────────────────────────────────

def is_data_ready(data_dir: Path) -> bool:
    """다운로드된 데이터가 최소한 존재하는지 확인"""
    return (data_dir / _VERSION_FILE).exists() and \
           all((data_dir / f).exists() for f in DATA_FILES)


def needs_update(data_dir: Path, max_age_days: int = 1) -> bool:
    """마지막 업데이트가 max_age_days일 이상 지났거나 파일이 없으면 True"""
    if not is_data_ready(data_dir):
        return True
    try:
        with open(data_dir / _VERSION_FILE, "r", encoding="utf-8") as f:
            info = json.load(f)
        last = datetime.fromisoformat(info.get("updated_at", "2000-01-01"))
        return (datetime.now() - last).days >= max_age_days
    except Exception:
        return True


def get_last_updated(data_dir: Path) -> str:
    """마지막 업데이트 일시 문자열 반환 (표시용)"""
    vf = data_dir / _VERSION_FILE
    if not vf.exists():
        return "없음"
    try:
        with open(vf, "r", encoding="utf-8") as f:
            info = json.load(f)
        dt = datetime.fromisoformat(info.get("updated_at", ""))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "알 수 없음"


# ── 다운로드 ───────────────────────────────────────────────────────

def download_data(
    data_dir: Path,
    status_cb: Callable[[str], None] | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """
    GitHub raw에서 DATA_FILES를 내려받아 data_dir에 저장.

    Returns:
        (success: bool, message: str)
    """
    if not force and not needs_update(data_dir):
        return True, "데이터 최신 상태"

    data_dir.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    for i, filename in enumerate(DATA_FILES):
        if status_cb:
            status_cb(f"데이터 다운로드 중... ({i + 1}/{len(DATA_FILES)}) {filename}")

        url  = GITHUB_RAW_BASE + filename
        dest = data_dir / filename
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "D2R-Tracker/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
            with open(dest, "wb") as fout:
                fout.write(content)
        except Exception as e:
            failed.append(f"{filename}({e})")

    if failed:
        return False, f"일부 파일 실패: {', '.join(failed)}"

    # 버전 정보 기록
    _write_version(data_dir)
    return True, f"데이터 업데이트 완료 ({len(DATA_FILES)}개 파일)"


def _write_version(data_dir: Path):
    info = {
        "updated_at": datetime.now().isoformat(),
        "source": GITHUB_RAW_BASE,
        "files": DATA_FILES,
    }
    with open(data_dir / _VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
