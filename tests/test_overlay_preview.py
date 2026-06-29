"""
즐겨찾기 오버레이(FavoriteOverlay) 시각 미리보기
실제 게임 창 없이도 화면에 오버레이를 띄워 텍스트 롤링(쳇바퀴 스크롤) 동작을 눈으로 확인할 수 있다.

실행:
    conda run -n d2r-tracker python tracker/tests/test_overlay_preview.py

종료: 오버레이의 ✕ 클릭, 콘솔 Ctrl+C, 또는 30초 후 자동 종료
"""
import sys
from pathlib import Path

_HERE    = Path(__file__).parent
_TRACKER = _HERE.parent
if str(_TRACKER) not in sys.path:
    sys.path.insert(0, str(_TRACKER))

import tkinter as tk
from ui.overlay import FavoriteOverlay

SAMPLE_FAVORITES = [
    {"name": "샤코", "url": "https://traderie.com/diablo2resurrected/product/shako",
     "min_price": "이스트룬", "max_price": "벡스룬"},
    {"name": "마라의 만화경", "url": "https://traderie.com/diablo2resurrected/product/maras-kaleidoscope",
     "min_price": "이스트룬", "max_price": "벡스룬"},
    {"name": "윈드포스", "url": "https://traderie.com/diablo2resurrected/product/windforce",
     "min_price": "펄룬", "max_price": "존룬"},
]


def main():
    root = tk.Tk()
    root.title("overlay preview")
    root.geometry("200x80+40+40")
    tk.Label(root, text="이 창을 닫으면 미리보기가 종료됩니다.").pack(padx=10, pady=10)

    overlay = FavoriteOverlay(root, proc_getter=lambda: None)
    overlay.set_items(SAMPLE_FAVORITES)
    overlay.start()

    root.after(30000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
