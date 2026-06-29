"""공통 UI 헬퍼 — clam 테마 X-indicator 대신 ☐/✓ 체크박스"""
import tkinter as tk

BG   = "#2b2b2b"
FG2  = "#aaaaaa"
GOLD = "#d4a843"


def mk_check(parent, variable: tk.BooleanVar, text: str = "",
             command=None, font: tuple = ("맑은 고딕", 10)) -> tk.Label:
    """
    ☐/✓ 스타일 체크박스 레이블 반환.
    반환값은 tk.Label — .grid() / .pack() 그대로 사용 가능.
    """
    def _text(v): return ("✓ " if v else "☐ ") + text
    def _fg(v):   return GOLD if v else FG2

    lbl = tk.Label(parent, text=_text(variable.get()),
                   fg=_fg(variable.get()),
                   bg=BG, font=font, cursor="hand2", anchor="w")

    def _refresh(*_):
        v = variable.get()
        lbl.config(text=_text(v), fg=_fg(v))

    def _toggle(e=None):
        variable.set(not variable.get())
        if command:
            command()

    lbl.bind("<Button-1>", _toggle)
    variable.trace_add("write", _refresh)
    return lbl
