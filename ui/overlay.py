"""
게임 화면 위에 표시되는 오버레이 결과창
레이아웃: 아이템아이콘 | 아이템이름 | 최저가 XXX 최고가 XXX (유/무료 공통 양식)
배경: 투명도 85% 검정 + 회색 테두리, 텍스트: 골드 (D2R 스타일)
"""
import tkinter as tk
import webbrowser
import ctypes
import ctypes.wintypes
import time
from pathlib import Path

from PIL import Image as PILImage, ImageTk
from config import SLOT_ICONS_DIR

# ── 슬롯 아이콘 캐시 ───────────────────────────────────────────
_ICON_SIZE = 22
_icon_cache: dict[str, "ImageTk.PhotoImage | None"] = {}


def _load_slot_icon(slot: str) -> "ImageTk.PhotoImage | None":
    """슬롯 이름 → 캐시된 PhotoImage. 파일 없거나 로드 실패 시 None."""
    if not slot:
        return None
    # 성공 캐시 or 파일 자체가 없는 경우(None)만 캐시 히트 처리
    # ImageTk 생성 실패는 캐시하지 않고 재시도 (tkinter 루트 미준비 타이밍 대응)
    if slot in _icon_cache and _icon_cache[slot] is not None:
        return _icon_cache[slot]
    path = Path(SLOT_ICONS_DIR) / f"{slot}.png"
    if not path.exists():
        _icon_cache[slot] = None
        return None
    try:
        img = PILImage.open(path).convert("RGBA").resize(
            (_ICON_SIZE, _ICON_SIZE), PILImage.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        _icon_cache[slot] = photo
        return photo
    except Exception:
        # 성공 시에만 캐시 — 실패는 캐시 안 해서 다음 호출 때 재시도
        return None

# ── 팔레트 ─────────────────────────────────────────────────────
_BG      = "#111111"
_ALPHA   = 0.85
_BORDER  = "#888888"
_GOLD    = "#d4a843"
_BTN     = "#888888"
_ERROR   = "#ff5555"
_PROG_FG = "#d4a843"
_PROG_BG = "#2a2a2a"


_FONT_SIZE_BASE = 11   # 기본 글씨 크기 (pt)
_FONT_SIZE_EXTRA = 0  # 추가 크기 (0~10)


def set_overlay_colors(bg: str = None, text: str = None):
    """오버레이 배경색/글자색 변경 (다음 표시 시 적용)"""
    global _BG, _GOLD, _PROG_FG
    if bg is not None:
        _BG = bg
    if text is not None:
        _GOLD = text
        _PROG_FG = text


def set_overlay_font_extra(extra: int):
    """오버레이 글씨 추가 크기 설정 (0~10pt). 다음 표시 시 적용."""
    global _FONT_SIZE_EXTRA
    _FONT_SIZE_EXTRA = max(0, min(10, int(extra)))

# ── 레이아웃 상수 ───────────────────────────────────────────────
_TOP_OFFSET    = 60    # 위 위치: 게임 창 상단 고정 px
_BOTTOM_OFFSET = 180   # 아래 위치: 게임 창 하단 고정 px (D2R HUD 높이)
_AUTO_MS       = 5000
_FADE_STP      = 0.06
_FADE_ITV      = 40
_PROG_H        = 3

_WIDTH_SCALE   = 1.5   # 오버레이 가로 폭 = 콘텐츠 기본 폭 x 이 값

# 즐겨찾기 오버레이 쳇바퀴(트레드밀) 스크롤
_SCROLL_MS     = 450    # 한 항목이 위로 밀려 올라가는 애니메이션 시간
_SCROLL_FPS    = 30     # 애니메이션 프레임 간격(ms)
_DWELL_MS      = 2200   # 다음 항목으로 스크롤 시작 전 정지 시간

OVERLAY_POS_TOP    = "top"
OVERLAY_POS_BOTTOM = "bottom"


def _make_item_row(parent, item_name: str, min_price: str, max_price: str,
                   count: int, traderie_url: str, open_fn, close_fn,
                   slot: str = '', on_fav_fn=None, is_fav: bool = False) -> tk.Frame:
    """유/무료 공통 오버레이 행 레이아웃 (아이콘+텍스트 함께 중앙 정렬)"""
    row = tk.Frame(parent, bg=_BG)

    # ✕ 먼저 right 에 배치해야 center_frame expand 시 정확히 중앙 정렬됨
    x_btn = tk.Label(row, text="✕", bg=_BG, fg=_BTN,
                     font=("맑은 고딕", 8), cursor="hand2", padx=8)
    x_btn.pack(side="right")
    x_btn.bind("<Button-1>", lambda e: close_fn())

    # 즐찾 버튼 (✕ 왼쪽, 콜백 있을 때만 표시)
    if on_fav_fn is not None:
        _fav_state = [is_fav]
        fav_lbl = tk.Label(row, text="★" if is_fav else "☆", bg=_BG, fg=_GOLD,
                           font=("맑은 고딕", 10, "bold"), cursor="hand2", padx=8)
        fav_lbl.pack(side="right")

        def _on_fav_click(e, _lbl=fav_lbl, _st=_fav_state):
            on_fav_fn()
            _st[0] = not _st[0]
            _lbl.config(text="★" if _st[0] else "☆")

        fav_lbl.bind("<Button-1>", _on_fav_click)

    # 아이콘+텍스트를 한 덩어리로 묶어 중앙에 배치
    center_frame = tk.Frame(row, bg=_BG)
    center_frame.pack(side="left", expand=True, fill="x")

    inner = tk.Frame(center_frame, bg=_BG)
    inner.pack(anchor="center")

    # 부위 아이콘 (파일 있을 때만 표시)
    icon_img = _load_slot_icon(slot)
    if icon_img:
        icon_lbl = tk.Label(inner, image=icon_img, bg=_BG, padx=6, pady=0)
        icon_lbl.image = icon_img  # GC 방지
        icon_lbl.pack(side="left")
        if traderie_url:
            icon_lbl.bind("<Button-1>", open_fn)

    if count > 0:
        text = (f"{item_name}   |   "
                f"최저가 {min_price}   "
                f"최고가 {max_price}")
    else:
        text = f"{item_name}   |   매물 없음"

    lbl = tk.Label(inner, text=text, bg=_BG, fg=_GOLD,
                   font=("맑은 고딕", _FONT_SIZE_BASE + _FONT_SIZE_EXTRA, "bold"),
                   cursor="hand2" if traderie_url else "arrow",
                   padx=14, pady=10)
    lbl.pack(side="left")
    if traderie_url:
        lbl.bind("<Button-1>", open_fn)

    return row


def _get_window_rect(pid: int) -> tuple[int, int, int, int] | None:
    found = []

    def _cb(hwnd, _):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            p = ctypes.c_ulong(0)
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                r = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                w, h = r.right - r.left, r.bottom - r.top
                if w > 100 and h > 100:
                    found.append((r.left, r.top, w, h))
        return True

    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    ctypes.windll.user32.EnumWindows(PROC(_cb), 0)
    return max(found, key=lambda r: r[2] * r[3]) if found else None


def _get_monitor_rect(x: int, y: int) -> tuple[int, int, int, int]:
    """주어진 좌표가 속한 모니터의 (left, top, width, height) 반환.
    실패 시 (0, 0, screenwidth, screenheight)."""
    try:
        # MonitorFromPoint → MONITORINFOEX → rcMonitor
        MONITOR_DEFAULTTONEAREST = 0x00000002
        pt = ctypes.wintypes.POINT(x, y)
        hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize",    ctypes.c_ulong),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork",    ctypes.wintypes.RECT),
                ("dwFlags",   ctypes.c_ulong),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        return (0, 0, ctypes.windll.user32.GetSystemMetrics(0),
                ctypes.windll.user32.GetSystemMetrics(1))


def _place_win(win: tk.Toplevel, bottom_offset: int,
               proc_getter, root: tk.Tk, width_scale: float = _WIDTH_SCALE):
    """오버레이 위치 결정.
    1순위: 선택된 프로세스 창이 있는 모니터 중앙
    2순위: tracker(root) 창이 있는 모니터 중앙
    Y 좌표: 해당 모니터 top + bottom_offset
    """
    win.update_idletasks()
    w = int(win.winfo_reqwidth() * width_scale)
    h = win.winfo_reqheight()

    # 1순위: 게임 프로세스 창 위치
    mon_left, mon_top, mon_w, mon_h = 0, 0, 0, 0
    proc = proc_getter() if proc_getter else None
    if proc is not None:
        try:
            rect = _get_window_rect(proc.pid)
            if rect:
                gx, gy, gw, gh = rect
                # 창 중심점으로 모니터 판별
                cx, cy = gx + gw // 2, gy + gh // 2
                mon_left, mon_top, mon_w, mon_h = _get_monitor_rect(cx, cy)
        except Exception:
            pass

    # 2순위: tracker 창 위치
    if mon_w == 0:
        try:
            rx = root.winfo_rootx() + root.winfo_width() // 2
            ry = root.winfo_rooty() + root.winfo_height() // 2
            mon_left, mon_top, mon_w, mon_h = _get_monitor_rect(rx, ry)
        except Exception:
            pass

    # 최후 폴백: 시스템 기본 해상도
    if mon_w == 0:
        mon_left, mon_top = 0, 0
        mon_w = ctypes.windll.user32.GetSystemMetrics(0)

    x = mon_left + (mon_w - w) // 2
    y = mon_top + bottom_offset

    win.geometry(f"{w}x{h}+{x}+{y}")


# ── 공통 위젯 빌더 ─────────────────────────────────────────────

def _make_base_win(root: tk.Tk, on_escape) -> tk.Toplevel:
    win = tk.Toplevel(root)
    win.wm_overrideredirect(True)
    win.wm_attributes("-topmost", True)
    win.wm_attributes("-alpha", _ALPHA)
    win.configure(bg=_BORDER)
    win.bind("<Escape>", lambda e: on_escape())
    return win


def _add_progress_bar(win: tk.Toplevel, root: tk.Tk, duration_ms: int) -> tk.Canvas:
    cv = tk.Canvas(win, height=_PROG_H, bg=_PROG_BG,
                   highlightthickness=0, bd=0)
    cv.pack(fill="x", side="bottom", padx=1, pady=(0, 1))
    bar = cv.create_rectangle(0, 0, 9999, _PROG_H, fill=_PROG_FG, outline="")
    t0 = int(time.time() * 1000)

    def _tick(_cv=cv, _bar=bar, _t0=t0):
        if not _cv.winfo_exists():
            return
        ratio = max(0.0, 1.0 - (int(time.time() * 1000) - _t0) / duration_ms)
        w = _cv.winfo_width() or 300
        _cv.coords(_bar, 0, 0, w * ratio, _PROG_H)
        if ratio > 0:
            root.after(50, _tick)

    root.after(50, _tick)
    return cv


# ══════════════════════════════════════════════════════════════════
class ResultOverlay:
    def __init__(self, root: tk.Tk, proc_getter=None):
        self._root          = root
        self._proc_getter   = proc_getter or (lambda: None)
        self._bottom_offset = _BOTTOM_OFFSET
        self._win: tk.Toplevel | None  = None
        self._after_id: str | None     = None
        self._img_ref       = None
        # 멀티행 상태 (유료 전용)
        self._multi_mode    = False
        self._inner: tk.Frame | None   = None
        self._prog_canvas: tk.Canvas | None = None
        self._pending_rows: list[tuple] = []  # (id, name, url, min, max, count, slot, on_fav, is_fav)
        self._next_row_id   = 0

    def set_multi_mode(self, enabled: bool):
        self._multi_mode = enabled

    def set_bottom_offset(self, px: int):
        self._bottom_offset = px

    # ── 공개 API ─────────────────────────────────────────────────

    def show(self, item_name: str, traderie_url: str,
             min_price: str, max_price: str, count: int = 0,
             item_image: PILImage.Image | None = None,
             slot: str = '', on_fav=None, is_fav: bool = False):
        row_id = self._next_row_id
        self._next_row_id += 1
        self._pending_rows.append(
            (row_id, item_name, traderie_url, min_price, max_price,
             count, slot, on_fav, is_fav)
        )
        max_rows = 2 if self._multi_mode else 1
        if len(self._pending_rows) > max_rows:
            self._pending_rows = self._pending_rows[-max_rows:]

        if not self._win or not self._win.winfo_exists():
            self._cancel()
            self._win = _make_base_win(self._root, self._close)
            self._inner = tk.Frame(self._win, bg=_BG)
            self._inner.pack(padx=1, pady=1, fill="x", expand=True)
            self._prog_canvas = None

        self._rebuild_rows()
        # 새 항목 추가 때마다 5초 타이머 리셋
        self._cancel()
        self._after_id = self._root.after(_AUTO_MS, self._fade)

    def show_error(self, message: str):
        self._reset()
        self._win = _make_base_win(self._root, self._close)
        self._build_error(message)
        self._start_timer()

    # ── UI 구성 ──────────────────────────────────────────────────

    def _rebuild_rows(self):
        """_inner 프레임을 _pending_rows 기준으로 재구성"""
        if not self._win or not self._win.winfo_exists():
            return
        for child in self._inner.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        if self._prog_canvas:
            try:
                self._prog_canvas.destroy()
            except Exception:
                pass
            self._prog_canvas = None

        for i, row_data in enumerate(self._pending_rows):
            rid, name, url, min_p, max_p, cnt, slot, on_fav, is_fav = row_data
            if i > 0:
                tk.Frame(self._inner, bg=_BORDER, height=1).pack(fill="x")

            def _open(e=None, _u=url):
                if _u:
                    webbrowser.open(_u)

            def _close_this(_rid=rid):
                self._close_row(_rid)

            row = _make_item_row(
                self._inner, name, min_p, max_p, cnt, url,
                _open, _close_this, slot=slot, on_fav_fn=on_fav, is_fav=is_fav
            )
            row.pack(fill="x")

        self._prog_canvas = _add_progress_bar(self._win, self._root, _AUTO_MS)
        _place_win(self._win, self._bottom_offset,
                   self._proc_getter, self._root, width_scale=_WIDTH_SCALE)

    def _close_row(self, row_id: int):
        """행 하나만 닫기. 마지막 행이면 창 전체 닫기."""
        self._pending_rows = [r for r in self._pending_rows if r[0] != row_id]
        if not self._pending_rows:
            self._close()
        else:
            self._rebuild_rows()

    def _build_error(self, message: str):
        inner = tk.Frame(self._win, bg=_BG)
        inner.pack(padx=1, pady=1)

        top = tk.Frame(inner, bg=_BG)
        top.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(top, text="오류", bg=_BG, fg=_ERROR,
                 font=("맑은 고딕", 9, "bold")).pack(side="left")
        x = tk.Label(top, text="✕", bg=_BG, fg=_BTN,
                     font=("맑은 고딕", 8), cursor="hand2")
        x.pack(side="right")
        x.bind("<Button-1>", lambda e: self._close())

        tk.Frame(inner, bg=_BORDER, height=1).pack(fill="x", padx=8, pady=(4, 4))
        tk.Label(inner, text=message, bg=_BG, fg=_ERROR,
                 font=("맑은 고딕", 9), wraplength=260,
                 justify="left").pack(anchor="w", padx=8, pady=(0, 8))

        _add_progress_bar(self._win, self._root, _AUTO_MS)
        _place_win(self._win, self._bottom_offset,
                   self._proc_getter, self._root)

    # ── 타이머 / 페이드 ──────────────────────────────────────────

    def _start_timer(self):
        self._after_id = self._root.after(_AUTO_MS, self._fade)

    def _fade(self, alpha: float = _ALPHA):
        if not self._win:
            return
        alpha -= _FADE_STP
        if alpha <= 0:
            self._close()
            return
        try:
            self._win.wm_attributes("-alpha", alpha)
            self._after_id = self._root.after(
                _FADE_ITV, lambda a=alpha: self._fade(a))
        except Exception:
            self._close()

    def _cancel(self):
        if self._after_id:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _destroy(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None

    def _reset(self):
        self._pending_rows = []
        self._inner = None
        self._prog_canvas = None
        self._cancel()
        self._destroy()

    def _close(self):
        self._pending_rows = []
        self._inner = None
        self._prog_canvas = None
        self._cancel()
        self._destroy()


# ══════════════════════════════════════════════════════════════════
class FavoriteOverlay:
    """즐겨찾기 목록을 아래→위로 끊임없이 스크롤되는 쳇바퀴(트레드밀) 형태로 순환 표시 (유료 전용)"""

    def __init__(self, root: tk.Tk, proc_getter=None):
        self._root          = root
        self._proc_getter   = proc_getter or (lambda: None)
        self._bottom_offset = _BOTTOM_OFFSET
        self._items: list[dict] = []
        self._index         = 0      # 현재 보이는(맨 위) 항목의 인덱스
        self._win: tk.Toplevel | None    = None
        self._canvas: tk.Canvas | None   = None
        self._row_w          = 0
        self._row_h          = 0
        self._cur_frame: tk.Frame | None  = None
        self._next_frame: tk.Frame | None = None
        self._cur_id  = None
        self._next_id = None
        self._anim_t0       = 0.0
        self._anim_id: str | None  = None
        self._dwell_id: str | None = None
        self._running        = False
        self._dwell_ms        = _DWELL_MS
        self._max_cycles     = 0   # 0 = 무한, N = N회전 후 자동 stop
        self._cycle_count    = 0   # 완료된 회전 수
        self._on_cycle_done  = None  # 1회전 완료 콜백

    def set_bottom_offset(self, px: int):
        self._bottom_offset = px

    def set_dwell_ms(self, ms: int):
        self._dwell_ms = ms

    def set_items(self, items: list[dict]):
        self._items = items
        if self._index >= len(items):
            self._index = 0
        if self._win is not None and self._win.winfo_exists():
            self._measure_rows()
            self._canvas.config(width=self._row_w, height=self._row_h)
            if self._cur_frame is not None:
                self._cur_frame.config(width=self._row_w, height=self._row_h)
            _place_win(self._win, self._bottom_offset,
                      self._proc_getter, self._root, width_scale=1.0)

    def start(self, max_cycles: int = 0, on_cycle_done=None):
        """
        max_cycles: 0=무한, 1=1회전 후 자동 stop
        on_cycle_done: 지정한 회전 수 완료 시 호출되는 콜백
        """
        if self._running or not self._items:
            return
        self._running     = True
        self._index       = 0
        self._cycle_count = 0
        self._max_cycles  = max_cycles
        self._on_cycle_done = on_cycle_done
        self._build_window()
        self._measure_rows()
        self._show_current()
        self._schedule_dwell()

    def stop(self):
        self._running = False
        self._cancel_timers()
        self._destroy()

    def pause(self):
        """오버레이 순환을 일시정지 (창은 유지하지 않고 타이머만 중단)"""
        self._cancel_timers()
        self._destroy()

    def resume(self):
        """일시정지 후 재개"""
        if self._running and self._items:
            self._build_window()
            self._measure_rows()
            self._show_current()
            self._schedule_dwell()

    def _cancel_timers(self):
        for attr in ("_anim_id", "_dwell_id"):
            aid = getattr(self, attr)
            if aid:
                try:
                    self._root.after_cancel(aid)
                except Exception:
                    pass
                setattr(self, attr, None)

    # ── 창 / 행 구성 ─────────────────────────────────────────────

    def _build_window(self):
        self._win = _make_base_win(self._root, self.stop)
        self._canvas = tk.Canvas(self._win, bg=_BG,
                                 highlightthickness=0, bd=0)
        self._canvas.pack(padx=1, pady=1)

    def _measure_rows(self):
        """전체 항목 중 가장 넓은 행의 크기를 측정 (특정 항목의 텍스트가 캔버스 폭에 잘리는 것 방지)"""
        max_w, max_h = 0, 0
        for item in self._items:
            row = self._make_row(item)
            row.update_idletasks()
            max_w = max(max_w, row.winfo_reqwidth())
            max_h = max(max_h, row.winfo_reqheight())
            row.destroy()
        self._row_w, self._row_h = int(max_w * _WIDTH_SCALE), max_h

    def _make_row(self, item: dict) -> tk.Frame:
        """즐겨찾기 한 항목을 텍스트 한 줄로 표시 (롤링 리스트 형태)"""
        url = item.get("url", "")
        min_price = item.get("min_price", "N/A")
        max_price = item.get("max_price", "N/A")
        count = 0 if (min_price in ("N/A", "매물없음", "") and max_price in ("N/A", "-", "")) else 1
        slot = item.get("slot", "")
        alias = item.get("alias", "").strip()
        display_name = alias if alias else item.get("name", "")

        def _open(e=None):
            if url:
                webbrowser.open(url)

        return _make_item_row(self._canvas, display_name,
                              min_price, max_price, count, url, _open, self.stop,
                              slot=slot)

    def _show_current(self):
        item = self._items[self._index % len(self._items)]
        self._cur_frame = self._make_row(item)
        self._cur_frame.config(width=self._row_w, height=self._row_h)
        self._cur_frame.pack_propagate(False)
        self._canvas.config(width=self._row_w, height=self._row_h)
        self._cur_id = self._canvas.create_window(0, 0, window=self._cur_frame,
                                                   anchor="nw")
        _place_win(self._win, self._bottom_offset,
                  self._proc_getter, self._root, width_scale=1.0)

    # ── 트레드밀 스크롤 ──────────────────────────────────────────

    def _schedule_dwell(self):
        self._dwell_id = self._root.after(self._dwell_ms, self._start_scroll)

    def _start_scroll(self):
        self._dwell_id = None
        if not self._running or not self._win or not self._win.winfo_exists():
            return
        if len(self._items) <= 1:
            self._schedule_dwell()
            return

        next_index = (self._index + 1) % len(self._items)

        # 1회전 완료: 마지막 항목 dwell이 끝난 후 다음이 첫 번째(index=0)라면 stop
        if next_index == 0:
            self._cycle_count += 1
            if self._max_cycles > 0 and self._cycle_count >= self._max_cycles:
                cb = self._on_cycle_done
                self.stop()
                if cb:
                    cb()
                return

        next_item = self._items[next_index]
        self._next_frame = self._make_row(next_item)
        self._next_frame.config(width=self._row_w, height=self._row_h)
        self._next_frame.pack_propagate(False)
        self._next_id = self._canvas.create_window(
            0, self._row_h, window=self._next_frame, anchor="nw")

        self._anim_t0 = time.time() * 1000
        self._anim_step()

    def _anim_step(self):
        if not self._running or not self._win or not self._win.winfo_exists():
            return
        elapsed = time.time() * 1000 - self._anim_t0
        progress = min(1.0, elapsed / _SCROLL_MS)
        offset = self._row_h * progress
        self._canvas.coords(self._cur_id, 0, -offset)
        self._canvas.coords(self._next_id, 0, self._row_h - offset)
        if progress < 1.0:
            self._anim_id = self._root.after(_SCROLL_FPS, self._anim_step)
        else:
            self._anim_id = None
            self._finish_scroll()

    def _finish_scroll(self):
        try:
            self._cur_frame.destroy()
        except Exception:
            pass
        self._cur_frame, self._cur_id = self._next_frame, self._next_id
        self._next_frame, self._next_id = None, None
        self._index = (self._index + 1) % len(self._items)
        _place_win(self._win, self._bottom_offset,
                  self._proc_getter, self._root, width_scale=1.0)
        self._schedule_dwell()

    def _destroy(self):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win          = None
        self._canvas        = None
        self._cur_frame     = None
        self._next_frame    = None
        self._cur_id         = None
        self._next_id        = None
