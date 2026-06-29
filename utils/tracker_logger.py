"""
로그 파일 작성
형식: 최종 확정 아이템이름  | 시간 | 트레더리 url | 최저가 | 최고가
"""
import os
from datetime import datetime
from config import LOG_DEFAULT_ROOT


class TrackerLogger:
    def __init__(self, log_dir: str = None):
        self.enabled = False
        self.log_dir = log_dir or LOG_DEFAULT_ROOT
        self._current_log_path: str | None = None

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def set_log_dir(self, log_dir: str):
        self.log_dir = log_dir
        self._current_log_path = None  # 날짜 바뀌면 새 파일 생성

    def _get_log_path(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        filename = f"d2r_tracker_{today}.txt"
        return os.path.join(self.log_dir, filename)

    def write(self, item_name: str, traderie_url: str,
              min_price: str, max_price: str):
        """로그 한 줄 기록"""
        if not self.enabled:
            return

        try:
            os.makedirs(self.log_dir, exist_ok=True)
            log_path = self._get_log_path()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            line = f"{item_name} | {timestamp} | {traderie_url} | {min_price} | {max_price}\n"

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)

            print(f"[Logger] 기록됨: {log_path}")

        except Exception as e:
            print(f"[Logger] 로그 기록 실패: {e}")

    def get_log_path_display(self) -> str:
        """현재 로그 파일 경로 (UI 표시용)"""
        return self._get_log_path()
