"""
글로벌 핫키 리스너
D2R에 포커스가 있어도 키 입력 감지
"""
import keyboard
import threading
from typing import Callable

_MODIFIERS = {
    'shift', 'ctrl', 'alt', 'windows',
    'left shift', 'right shift',
    'left ctrl', 'right ctrl',
    'left alt', 'right alt',
    'left windows', 'right windows',
}

_KEY_DISPLAY = {
    "print_screen": "Print Screen",
    "scroll_lock":  "Scroll Lock",
    "pause":        "Pause",
    "page_up":      "Page Up",
    "page_down":    "Page Down",
    "caps_lock":    "Caps Lock",
    "num_lock":     "Num Lock",
    "insert":       "Insert",
    "delete":       "Delete",
    "home":         "Home",
    "end":          "End",
    "left":         "←",
    "right":        "→",
    "up":           "↑",
    "down":         "↓",
    "enter":        "Enter",
    "space":        "Space",
    "backspace":    "Backspace",
    "tab":          "Tab",
    "escape":       "Esc",
}


def hotkey_display_name(hotkey_value: str) -> str:
    """내부 핫키 값 → 표시명  (예: ctrl+f1 → Ctrl+F1)"""
    parts = [p.strip().lower() for p in hotkey_value.split("+")]
    result = []
    for p in parts:
        if p in _KEY_DISPLAY:
            result.append(_KEY_DISPLAY[p])
        elif p in ("ctrl", "alt", "shift"):
            result.append(p.capitalize())
        elif p.startswith("f") and p[1:].isdigit():
            result.append(p.upper())
        elif p.startswith("numpad"):
            result.append("Numpad " + p[6:].upper())
        else:
            result.append(p.capitalize())
    return "+".join(result)


def capture_next_key(callback: Callable[[str], None]) -> list:
    """
    다음 키 입력(조합 포함)을 캡처해 callback(key_str)으로 전달.
    반환된 hook_ref[0] 을 keyboard.unhook()에 넘기면 취소 가능.
    """
    hook_ref = [None]

    def _handler(event: keyboard.KeyboardEvent):
        name = event.name.lower()
        if name in _MODIFIERS:
            return
        modifiers = []
        if keyboard.is_pressed("ctrl"):
            modifiers.append("ctrl")
        if keyboard.is_pressed("alt"):
            modifiers.append("alt")
        if keyboard.is_pressed("shift"):
            modifiers.append("shift")
        combo = "+".join(modifiers + [name]) if modifiers else name
        # on_press가 반환한 wrapper(hook_ref[0])를 unhook해야 정상 해제됨
        if hook_ref[0] is not None:
            try:
                keyboard.unhook(hook_ref[0])
            except Exception:
                pass
            hook_ref[0] = None
        callback(combo)

    hook_ref[0] = keyboard.on_press(_handler)
    return hook_ref


class HotkeyListener:
    def __init__(self):
        self._callback: Callable | None = None
        self._current_hotkey: str = "print_screen"
        self._registered = False
        self._lock = threading.Lock()

    def set_hotkey(self, hotkey: str, callback: Callable):
        with self._lock:
            self._unregister()
            self._current_hotkey = hotkey
            self._callback = callback
            self._register()

    def _register(self):
        if self._callback and self._current_hotkey:
            try:
                keyboard.add_hotkey(self._current_hotkey, self._on_hotkey)
                self._registered = True
            except Exception as e:
                print(f"[HotkeyListener] 핫키 등록 실패: {e}")

    def _unregister(self):
        if self._registered:
            try:
                keyboard.remove_hotkey(self._current_hotkey)
            except Exception:
                pass
            self._registered = False

    def _on_hotkey(self):
        if self._callback:
            threading.Thread(target=self._callback, daemon=True).start()

    def stop(self):
        with self._lock:
            self._unregister()
            self._callback = None

    @property
    def current_hotkey(self) -> str:
        return self._current_hotkey
