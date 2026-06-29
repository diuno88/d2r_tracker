"""
유료 키 인증
GitHub에 공개된 SHA-256 해시값과 사용자가 입력한 키의 해시를 비교한다.
원본 키는 절대 GitHub에 올리지 않고, 해시값만 공개로 호스팅한다.
"""
import hashlib
import json
import urllib.request
from typing import Optional

from config import GITHUB_PREMIUM_KEY_URL


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def fetch_remote_hash(timeout: int = 10) -> Optional[str]:
    """GitHub premium_keys.json에서 현재 유효한 해시값을 가져온다"""
    try:
        req = urllib.request.Request(
            GITHUB_PREMIUM_KEY_URL, headers={"User-Agent": "D2R-Tracker/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("hash") or "").strip().lower() or None
    except Exception:
        return None


def verify_key(input_key: str) -> tuple[bool, str]:
    """
    입력된 키를 해시하여 GitHub의 해시값과 비교.
    Returns: (인증 성공 여부, 메시지)
    """
    if not input_key:
        return False, "키를 입력하세요"

    remote_hash = fetch_remote_hash()
    if remote_hash is None:
        return False, "인증 서버에 연결할 수 없습니다"

    if hash_key(input_key) == remote_hash:
        return True, "인증 성공"
    return False, "키가 올바르지 않거나 만료되었습니다"
