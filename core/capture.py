"""
D2R 화면 캡처 모듈
- 실행 중인 윈도우 프로세스 목록 조회
- 특정 프로세스 창 타겟 캡처
- 마우스 주변 캡처 + D2R 툴팁 자동 감지
"""
import mss
import numpy as np
from PIL import Image
import tempfile
import os
import ctypes
import ctypes.wintypes
from pathlib import Path
from typing import Optional


# ── 프로세스 / 윈도우 목록 ────────────────────────────────────

class ProcessInfo:
    def __init__(self, pid: int, proc_name: str, window_title: str):
        self.pid = pid
        self.proc_name = proc_name
        self.window_title = window_title

    def display_name(self) -> str:
        if self.window_title:
            return f"{self.window_title}  [{self.proc_name}]"
        return self.proc_name

    def __repr__(self):
        return f"<ProcessInfo pid={self.pid} {self.proc_name}>"


def get_window_processes() -> list[ProcessInfo]:
    results = []
    seen_pids = set()

    try:
        import psutil
        hwnd_pid_map: dict[int, int] = {}

        def enum_callback(hwnd, _):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                pid = ctypes.c_ulong(0)
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    hwnd_pid_map[int(hwnd)] = pid.value
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        for hwnd, pid in hwnd_pid_map.items():
            if pid in seen_pids:
                continue
            title_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 256)
            title = title_buf.value.strip()
            if not title:
                continue
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if proc_name.lower() in ('explorer.exe', 'taskhostw.exe', 'svchost.exe',
                                      'system', 'registry', 'smss.exe', 'csrss.exe',
                                      'wininit.exe', 'services.exe', 'lsass.exe',
                                      'winlogon.exe', 'fontdrvhost.exe', 'dwm.exe',
                                      'searchhost.exe', 'runtimebroker.exe'):
                continue
            seen_pids.add(pid)
            results.append(ProcessInfo(pid, proc_name, title))

    except ImportError:
        try:
            import pygetwindow as gw
            for w in gw.getAllWindows():
                if w.title and w.width > 0 and w.height > 0:
                    results.append(ProcessInfo(0, "", w.title))
        except Exception:
            pass
    except Exception as e:
        print(f"[Capture] 프로세스 목록 오류: {e}")

    results.sort(key=lambda p: p.window_title.lower())
    return results


def find_window_by_process(proc_info: ProcessInfo) -> Optional[tuple]:
    try:
        import pygetwindow as gw
        if proc_info.window_title:
            windows = gw.getWindowsWithTitle(proc_info.window_title)
            if windows:
                win = windows[0]
                if win.width > 0 and win.height > 0:
                    return (win.left, win.top, win.width, win.height)
        if proc_info.pid:
            hwnd = _find_hwnd_by_pid(proc_info.pid)
            if hwnd:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 0 and h > 0:
                    return (rect.left, rect.top, w, h)
    except Exception as e:
        print(f"[Capture] 창 위치 탐색 오류: {e}")
    return None


def _find_hwnd_by_pid(pid: int) -> Optional[int]:
    result = [None]

    def callback(hwnd, _):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        p = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            result[0] = int(hwnd)
            return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result[0]


# ── 마우스 위치 ───────────────────────────────────────────────

def get_mouse_pos() -> tuple[int, int]:
    """현재 마우스 스크린 좌표 반환"""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def find_cursor_in_image(img: Image.Image) -> Optional[tuple[int, int]]:
    """
    테스트 이미지에서 흰색 원형 아이템 아이콘(마우스 위치 마커) 중심 좌표 감지.
    - 채워진 원: circularity >= 0.55
    - 도넛형 링/아뮬렛 아이콘: 외접원 커버리지 + 정방형 바운딩박스 검사
    하단 15%(UI 바)는 제외하고 탐색.
    """
    try:
        import cv2
        arr = np.array(img.convert("RGB"))
        h, w = arr.shape[:2]
        game_h = int(h * 0.85)
        roi = arr[:game_h, :, :]

        # 흰색 픽셀 마스크 (RGB 모두 230 이상)
        white_mask = (
            (roi[:, :, 0] >= 230) &
            (roi[:, :, 1] >= 230) &
            (roi[:, :, 2] >= 230)
        ).astype(np.uint8) * 255

        # 노이즈 제거 후 윤곽선 탐색
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best = None
        best_score = -1.0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 80 or area > 50000:
                continue
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue

            circularity = 4 * np.pi * area / (perimeter ** 2)

            # 외접원 커버리지 및 바운딩박스 정방형 검사
            _, radius = cv2.minEnclosingCircle(cnt)
            circle_area = np.pi * radius ** 2
            coverage = area / circle_area if circle_area > 0 else 0
            bx, by, bw_r, bh_r = cv2.boundingRect(cnt)
            aspect = min(bw_r, bh_r) / max(bw_r, bh_r) if max(bw_r, bh_r) > 0 else 0

            # 채워진 원: circularity >= 0.55
            is_filled_circle = circularity >= 0.55
            # 도넛형 아이콘: 정방형 + 외접원 커버리지 + 최소 반지름
            is_ring_icon = (coverage >= 0.12 and aspect >= 0.65 and radius >= 8)

            if not (is_filled_circle or is_ring_icon):
                continue

            # 둥글수록, 클수록 높은 점수
            shape_score = circularity if is_filled_circle else (coverage * 0.6 + aspect * 0.4)
            score = shape_score * area
            if score > best_score:
                best_score = score
                M = cv2.moments(cnt)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    best = (cx, cy)

        return best
    except Exception:
        return None


# ── 화면 캡처 ────────────────────────────────────────────────

def capture_screen(region=None) -> Image.Image:
    with mss.mss() as sct:
        if region:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def capture_around_mouse(proc_info: Optional[ProcessInfo] = None,
                          padding_x: int = 500,
                          padding_y: int = 600,
                          padding_down: int = 350) -> tuple[Image.Image, tuple, tuple]:
    """
    마우스가 위치한 모니터 전체를 캡처.
    툴팁은 항상 마우스와 같은 모니터에 있으므로, 창 탐색 없이 모니터 기준으로 캡처.
    Returns: (PIL Image, (left,top,w,h) region, (mx,my) mouse screen pos)
    """
    mx, my = get_mouse_pos()

    try:
        with mss.mss() as sct:
            # 마우스가 속한 모니터 찾기 (monitors[0]은 전체 합성 영역)
            target_mon = None
            for mon in sct.monitors[1:]:
                if (mon["left"] <= mx < mon["left"] + mon["width"] and
                        mon["top"] <= my < mon["top"] + mon["height"]):
                    target_mon = mon
                    break
            if target_mon is None:
                target_mon = sct.monitors[1]  # 폴백: 첫 번째 모니터

        region = (target_mon["left"], target_mon["top"],
                  target_mon["width"], target_mon["height"])
        img = capture_screen(region)
        return img, region, (mx, my)

    except Exception:
        img, region = _capture_fallback(proc_info)
        mx, my = get_mouse_pos()
        return img, region, (mx, my)


def _capture_fallback(proc_info):
    region = find_window_by_process(proc_info) if proc_info else None
    img = capture_screen(region)
    if region is None:
        with mss.mss() as sct:
            m = sct.monitors[1]
            region = (m["left"], m["top"], m["width"], m["height"])
    return img, region


# ── 툴팁 자동 감지 ────────────────────────────────────────────
#
# 알고리즘 (claude-tooltip.md):
# 시스템 문구(마지막 줄)의 bbox x범위 = 툴팁 x범위
# 같은 x범위 내 모든 OCR bbox를 수집 → y범위 결정
# 픽셀 스캔 없이 OCR bbox만으로 4좌표 확정

# paddle_ocr_bridge가 라인 단위로 병합 후 반환하므로 라인 텍스트에서 부분 매칭.
# 시스템 문구는 반드시 "Shift" 또는 "Ctrl"을 포함 (오탐 방지)
_SYS_KEYWORDS = ['Shift', 'Ctrl', 'shift', 'ctrl']

# "Shift"/"Ctrl" 영문이 OCR 오류로 완전히 깨지는 경우의 한글 폴백 키워드.
# 시스템 문구 줄에 흔히 남는 한글 단어들 — 2개 이상 매칭되어야 인정(오탐 방지)
_SYS_KEYWORDS_KOR_FALLBACK = [
    '왼쪽', '클릭', '착용', '이동', '비교', '소지품', '떨어뜨리기', '해제',
]
# OCR이 시스템 문구를 짧게 쪼갤 때 단독으로도 확실한 식별이 가능한 단어
# "소지품"은 소지품 창 타이틀에도 등장하므로 제외 — 반드시 다른 키워드와 함께
_SYS_KEYWORDS_KOR_ALONE = ['떨어뜨리기']
_PAD = 10   # 크롭 여백 (px)
# 툴팁 x범위 판정: 시스템 문구 x중심 기준 이내에 있는 bbox만 같은 툴팁으로 간주
_TOOLTIP_X_MARGIN = 60



def _bbox_to_rect(bbox) -> Optional[tuple[int, int, int, int]]:
    """PaddleOCR bbox ([[x0,y0],[x1,y0],[x1,y1],[x0,y1]]) → (x0,y0,x1,y1)"""
    try:
        if bbox is None:
            return None
        pts = [(int(p[0]), int(p[1])) for p in bbox]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None



def find_tooltip(img: Image.Image,
                 mouse_screen: tuple[int, int],
                 img_offset: tuple[int, int],
                 lines_with_bbox: Optional[list] = None
                 ) -> tuple[Optional[Image.Image], Optional[tuple], str]:
    """
    D2R 툴팁 감지 (claude-tooltip.md 알고리즘).
    lines_with_bbox: [(text, bbox), ...] — PaddleOCR 전체화면 OCR 결과

    1. 시스템 문구 bbox 찾기 → x범위 확정
    2. 같은 x범위 내 모든 bbox의 y범위로 툴팁 y 확정
    3. 4좌표 크롭

    Returns: (tooltip_image, crop_rect, dbg_msg)
    """
    if not lines_with_bbox:
        return None, None, "툴팁감지[실패] OCR bbox 없음"

    try:
        ox, oy = img_offset
        iw, ih = img.size
        # 이미지 내 마우스 좌표
        mx = max(0, min(iw - 1, mouse_screen[0] - ox))
        my = max(0, min(ih - 1, mouse_screen[1] - oy))

        # ── 1. 시스템 문구 라인 찾기 ────────────────────────────
        # paddle_ocr_bridge._merge_to_lines이 단어를 라인 단위로 합쳐 반환하므로
        # 라인 텍스트에 키워드가 포함되면 시스템 문구 라인으로 판정
        # "Shift"/"Ctrl" 영문이 OCR로 완전히 깨진 경우, 한글 키워드 2개 이상
        # 매칭되면 폴백으로 시스템 문구로 인정 (오탐 방지를 위해 1개는 부족)
        sys_candidates = []
        for text, bbox in lines_with_bbox:
            has_eng_kw = any(kw in text for kw in _SYS_KEYWORDS)
            kor_alone = any(kw in text for kw in _SYS_KEYWORDS_KOR_ALONE)
            kor_hits = sum(1 for kw in _SYS_KEYWORDS_KOR_FALLBACK if kw in text)
            if not has_eng_kw and not kor_alone and kor_hits < 2:
                continue
            rect = _bbox_to_rect(bbox)
            if rect is None:
                continue
            bx0, by0, bx1, by1 = rect
            cx = (bx0 + bx1) // 2
            cy = (by0 + by1) // 2
            bbox_w = bx1 - bx0
            # 비정상적으로 넓은 bbox는 다른 요소와 잘못 병합된 것 → 스킵
            # 화면 너비의 30% 이상이면 제외
            if bbox_w > iw * 0.30:
                print(f"[Tooltip] 시스템문구 후보 스킵(너무 넓음 {bbox_w}px): '{text[:30]}'")
                continue
            # x거리: 마우스가 bbox x범위 안에 있으면 0, 밖이면 가장자리까지 거리
            x_dist = 0 if bx0 <= mx <= bx1 else min(abs(mx - bx0), abs(mx - bx1))
            # 마우스와 x거리가 화면 너비의 20% 이상이면 다른 UI 요소(소지품창 등) → 스킵
            if x_dist > iw * 0.20:
                print(f"[Tooltip] 시스템문구 후보 스킵(x거리 너무 멈 {x_dist}px): '{text[:30]}'")
                continue
            y_dist = abs(cy - my)
            # x거리에 3배 가중치 (x가 크게 벗어난 시스템 문구 우선순위 낮춤)
            dist = x_dist * 3 + y_dist
            sys_candidates.append((dist, bx0, by0, bx1, by1, text))

        if not sys_candidates:
            # 폴백: 마우스 x를 anchor로 삼아 기존 step3와 동일한 방식으로 bbox 수집
            # y_end만 이미지 하단(ih)으로 확장 (시스템 문구가 캡쳐 밖으로 잘린 경우)
            fix_cx = mx
            half_w = max(150, (fix_cx - 0) // 4)
            fall_bboxes = []
            for text, bbox in lines_with_bbox:
                rect = _bbox_to_rect(bbox)
                if rect is None:
                    continue
                bx0, by0, bx1, by1 = rect
                bcx = (bx0 + bx1) // 2
                if not (fix_cx - half_w - _TOOLTIP_X_MARGIN <= bcx
                        <= fix_cx + half_w + _TOOLTIP_X_MARGIN):
                    continue
                fall_bboxes.append((bx0, by0, bx1, by1))

            if not fall_bboxes:
                return None, None, f"툴팁감지[실패] 시스템문구 없음 mouse=({mx},{my})"

            fx0 = min(b[0] for b in fall_bboxes)
            fx1 = max(b[2] for b in fall_bboxes)
            fy0 = min(b[1] for b in fall_bboxes)
            x1 = max(0,  fx0 - _PAD)
            x2 = min(iw, fx1 + _PAD)
            y1 = max(0,  fy0 - _PAD)
            y2 = ih
            dbg = f"툴팁감지[폴백] x={x1}~{x2} y={y1}~{y2} mouse=({mx},{my})"
            print(f"[Tooltip] {dbg}")
            return img.crop((x1, y1, x2, y2)), (x1, y1, x2, y2), dbg

        sys_candidates.sort(key=lambda c: c[0])
        _, sx0, sby0, sx1, sby1, sys_text_dbg = sys_candidates[0]
        sys_cx = (sx0 + sx1) // 2
        sys_cy_val = (sby0 + sby1) // 2

        print(f"[Tooltip] 시스템문구: '{sys_text_dbg}' bbox=({sx0},{sby0})~({sx1},{sby1})")

        # ── 2. 툴팁 x범위 = 시스템 문구 x범위 (고정, 확장 안 함) ──
        fix_x0 = sx0
        fix_x1 = sx1
        fix_cx = sys_cx  # 중심 기준

        # ── 3. 시스템 문구 x중심 기준으로 bbox 필터링 → y범위 수집 ──
        # x범위는 고정(연쇄 확장 금지), y범위만 수집
        tip_bboxes = []
        for text, bbox in lines_with_bbox:
            rect = _bbox_to_rect(bbox)
            if rect is None:
                continue
            bx0, by0, bx1, by1 = rect
            bcx = (bx0 + bx1) // 2
            # bbox x중심이 시스템 문구 x중심 ± (시스템문구 너비 + 여백) 안에 있어야 함
            half_w = max((fix_x1 - fix_x0) // 2, 80)
            if not (fix_cx - half_w - _TOOLTIP_X_MARGIN <= bcx <= fix_cx + half_w + _TOOLTIP_X_MARGIN):
                continue
            tip_bboxes.append((bx0, by0, bx1, by1))

        if not tip_bboxes:
            tip_bboxes = [(sx0, sby0, sx1, sby1)]

        tip_x0 = min(b[0] for b in tip_bboxes)
        tip_x1 = max(b[2] for b in tip_bboxes)
        tip_y0 = min(b[1] for b in tip_bboxes)
        tip_y1 = max(b[3] for b in tip_bboxes)

        # ── 4. 크롭 좌표 확정 ────────────────────────────────────
        x1 = max(0,  tip_x0 - _PAD)
        x2 = min(iw, tip_x1 + _PAD)
        y1 = max(0,  tip_y0 - _PAD)
        y2 = min(ih, tip_y1 + _PAD)

        dbg = (f"툴팁감지[OCR] x={x1}~{x2} y={y1}~{y2} "
               f"sys='{sys_text_dbg[:30]}' sys_xy=({sys_cx},{sys_cy_val}) mouse=({mx},{my})")
        print(f"[Tooltip] {dbg}")
        return img.crop((x1, y1, x2, y2)), (x1, y1, x2, y2), dbg

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, None, f"툴팁 감지 오류: {e}"


def filter_ocr_lines_in_crop(lines_with_bbox: list,
                               crop_rect: tuple) -> tuple[list, list]:
    """
    full-screen OCR 결과에서 crop_rect(x1,y1,x2,y2) 안에 있는 항목만 필터링.
    Returns: (lines, lines_with_bbox_crop) — crop 내 텍스트/bbox 목록
    """
    if not crop_rect or not lines_with_bbox:
        return [], []
    cx1, cy1, cx2, cy2 = crop_rect
    filtered_text = []
    filtered_bbox = []
    for text, bbox in lines_with_bbox:
        rect = _bbox_to_rect(bbox)
        if rect is None:
            continue
        bx0, by0, bx1, by1 = rect
        bcx = (bx0 + bx1) // 2
        bcy = (by0 + by1) // 2
        if cx1 <= bcx <= cx2 and cy1 <= bcy <= cy2:
            filtered_text.append(text)
            try:
                shifted = [[p[0] - cx1, p[1] - cy1] for p in bbox]
            except Exception:
                shifted = bbox
            filtered_bbox.append((text, shifted))
    return filtered_text, filtered_bbox


# ── 희귀도 감지 ───────────────────────────────────────────────

_REQ_LEVEL_KW = ['요구 레벨', '요구레벨', '착용 가능한 레벨', 'Required Level', 'Req Level']


def detect_rarity_from_image(img: Image.Image,
                              ocr_lines: list = None) -> str:
    """
    '요구 레벨' 기준 위쪽(아이템 이름 영역)의 색상으로 희귀도 판별.
    ocr_lines: OCR 결과 라인 목록 — 요구 레벨 라인 위치로 이름 영역 y 범위 계산.
    ocr_lines 없으면 상단 20% 폴백.
    Returns: 'unique' | 'set' | 'rare' | 'magic' | 'base'
    """
    try:
        import cv2

        arr = np.array(img)
        h, w = arr.shape[:2]

        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

        # ── '요구 레벨' 위치로 이름 영역 높이 계산 ──────────────
        name_h = max(40, int(h * 0.20))  # 폴백: 상단 20%
        if ocr_lines:
            total = len(ocr_lines)
            for i, line in enumerate(ocr_lines):
                lower = line.lower()
                if any(kw.lower() in lower for kw in _REQ_LEVEL_KW):
                    # 요구 레벨 라인 인덱스 비율로 이미지 y 위치 추정
                    ratio = i / total if total > 0 else 0.4
                    name_h = max(40, int(h * ratio))
                    print(f"[Rarity] 요구레벨 라인={i}/{total} → name_h={name_h}px")
                    break

        # ── 테두리 영역 (외곽 5px) ───────────────────────────────
        BORDER = 5
        border_mask = np.zeros((h, w), dtype=np.uint8)
        border_mask[:BORDER, :]  = 255
        border_mask[-BORDER:, :] = 255
        border_mask[:, :BORDER]  = 255
        border_mask[:, -BORDER:] = 255

        # ── 이름 영역 (요구 레벨 위쪽) ──────────────────────────
        text_mask = np.zeros((h, w), dtype=np.uint8)
        text_mask[:name_h, :] = 255

        def count_color(hsv_img, mask, h_lo, h_hi, s_lo, s_hi, v_lo, v_hi):
            color_mask = cv2.inRange(
                hsv_img,
                np.array([h_lo, s_lo, v_lo]),
                np.array([h_hi, s_hi, v_hi])
            )
            return int(np.sum(cv2.bitwise_and(color_mask, mask) > 0))

        scores = {}

        # Unique / Runeword (금색) - 테두리 우선
        scores['unique'] = (
            count_color(hsv, border_mask, 15, 35, 120, 255, 130, 255) * 3 +
            count_color(hsv, text_mask,   15, 35, 100, 255, 130, 255)
        )

        # Set (초록) - 테두리 우선
        scores['set'] = (
            count_color(hsv, border_mask, 40, 85, 80, 255, 60, 255) * 3 +
            count_color(hsv, text_mask,   40, 85, 60, 255, 60, 255)
        )

        # Rare (노란)
        scores['rare'] = (
            count_color(hsv, border_mask, 18, 45, 80, 255, 100, 255) * 3 +
            count_color(hsv, text_mask,   18, 45, 60, 255,  80, 255)
        )

        # Magic (파란)
        scores['magic'] = (
            count_color(hsv, border_mask, 100, 130, 60, 255, 80, 255) * 3 +
            count_color(hsv, text_mask,   100, 130, 40, 255, 60, 255)
        )

        THRESHOLD = 15
        valid = {k: v for k, v in scores.items() if v >= THRESHOLD}
        if not valid:
            return 'base'

        result = max(valid, key=valid.get)
        print(f"[Capture] 희귀도 감지: {result}  scores={scores}")
        return result

    except Exception as e:
        print(f"[Capture] 희귀도 감지 오류: {e}")
        return 'base'


# ── 유틸 ─────────────────────────────────────────────────────

def save_temp_image(img: Image.Image) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    img.save(tmp.name, "PNG")
    return tmp.name
