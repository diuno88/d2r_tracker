"""
D2R Traderie Tracker
메인 UI (tkinter) + 앱 진입점
"""
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser
import threading
import queue
import json
import os
import sys
import ctypes
import webbrowser
from datetime import datetime
from pathlib import Path

from config import (load_config, save_config, load_ai_keys, save_ai_keys,
                    DATA_DIR, LOG_DEFAULT_ROOT, CAPTURES_SUBDIR,
                    CAPTURES_FILENAME, ICON_FILE)
from core.data_updater import download_data, get_last_updated, needs_update
from core.capture import (capture_around_mouse, save_temp_image,
                     detect_rarity_from_image, find_tooltip,
                     get_window_processes, ProcessInfo, find_cursor_in_image)
from core.hotkey import HotkeyListener, hotkey_display_name, capture_next_key
from core.premium_auth import verify_key
import psutil
import pystray
from PIL import Image as PILImage, ImageDraw, ImageTk
from ocr.ai_vision_bridge import AIVisionBridge, PROVIDER_NAMES
from ocr.paddle_ocr_bridge import PaddleOCRBridge, is_paddle_installed, is_model_ready
from item.item_parser import ItemParser
from utils.price_fetcher import fetch_price_stats
from utils.ui_helpers import mk_check
from ui.overlay import (ResultOverlay, FavoriteOverlay, set_overlay_colors, set_overlay_font_extra)
from ui.price_search_tab import PriceSearchTab
from utils.tracker_logger import TrackerLogger


BG    = "#2b2b2b"
FG    = "#e0e0e0"
FG2   = "#aaaaaa"
GOLD  = "#d4a843"
RED   = "#ff6666"
GREEN = "#66ff66"


class TrackerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("D2R Traderie Tracker")
        self.root.resizable(True, True)
        self.root.configure(bg=BG)

        self.config = load_config()
        if not self.config.get("premium_key"):
            # 키 없이 is_premium=True가 남아있는 경우(예: 구버전 잔여 데이터) 무료로 교정
            self.config["is_premium"] = False
        save_config(self.config)
        self.is_tracking = False
        self.is_processing = False
        # 유료 전용 연속 캡처 큐 (최대 5개 대기)
        self._capture_queue: queue.Queue = queue.Queue(maxsize=5)
        self._queue_worker_running: bool = False

        self._selected_proc: ProcessInfo | None = None
        self._proc_map: dict[str, ProcessInfo] = {}

        self._tray_icon: pystray.Icon | None = None
        self._tray_thread: threading.Thread | None = None

        self.hotkey_listener = HotkeyListener()
        self.ai_bridge = AIVisionBridge()
        self.paddle_bridge = PaddleOCRBridge()
        self.item_parser = ItemParser()
        self.logger = TrackerLogger(self.config.get("log_path"))

        self.overlay = ResultOverlay(self.root, proc_getter=lambda: self._selected_proc)
        self.fav_overlay = FavoriteOverlay(self.root, proc_getter=lambda: self._selected_proc)

        # 즐겨찾기 목록: [{name, url, min_price, max_price, options: {k:v}}]
        self._favorites: list[dict] = list(self.config.get("favorites", []))

        self._preview_img_tk = None
        self._is_premium = self.config.get("is_premium", False)
        self._is_admin = False  # 관리자 모드 (내부 전용)
        # dev_mode: tracker_config.json에 "dev_mode": true 추가 시 모든 기능 활성화 (비빌드 환경 전용)
        if self.config.get("dev_mode") and not getattr(sys, 'frozen', False):
            self._is_admin = True
            self._is_premium = True
        self._free_scan_count = 0
        self._fav_overlay_paused = False
        self._fav_refresh_after_id = None
        self._fav_overlay_cycle_id = None
        self._fav_overlay_show_id = None
        self._proc_check_after_id = None
        self._fav_countdown_id = None
        self._fav_countdown_secs = 0
        self._overlay_sample_preview: FavoriteOverlay | None = None

        # 래더 시즌 데이터 로드
        self._ladder_seasons: list[dict] = []
        try:
            with open(DATA_DIR / "ladderSeason.json", encoding="utf-8") as _f:
                self._ladder_seasons = json.load(_f)
        except Exception:
            pass

        self._build_ui()
        self._apply_config()
        self._refresh_processes()

        def _ai_status(msg: str):
            self.root.after(0, lambda m=msg: self._append_log(m, "info"))
            self.root.after(0, self._update_ai_provider_label)

        def _paddle_status(msg: str):
            self.root.after(0, lambda m=msg: self._append_log(m, "info"))
            self.root.after(0, lambda m=msg: self._set_status(m))

        self.ai_bridge.set_status_callback(_ai_status)
        self.paddle_bridge.set_status_callback(_paddle_status)
        self._auto_update_data()
        self._auto_verify_premium()
        self.overlay.set_multi_mode(self._is_premium)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ────────────────────────── UI 구성 ──────────────────────────
    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel",       background=BG, foreground=FG,  font=("맑은 고딕", 11))
        style.configure("TCheckbutton", background=BG, foreground=FG,  font=("맑은 고딕", 11),
                        indicatorcolor="#2b2b2b", indicatorrelief="flat")
        style.map("TCheckbutton",
                  indicatorcolor=[("selected", "#4caf50"), ("!selected", "#555555")],
                  background=[("active", BG)])
        style.configure("TCombobox",    font=("맑은 고딕", 11))
        style.configure("TFrame",       background=BG)
        style.configure("TSeparator",   background="#444")
        style.configure("TNotebook",    background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
                        background="#333", foreground=FG2,
                        font=("맑은 고딕", 11), padding=(14, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", GOLD)],
                  padding=[("selected", (20, 10))],
                  font=[("selected", ("맑은 고딕", 12, "bold"))])
        style.configure("Treeview",
                        background="#1e1e1e", foreground=FG,
                        fieldbackground="#1e1e1e", font=("맑은 고딕", 11),
                        rowheight=26)
        style.configure("Treeview.Heading",
                        background="#333", foreground=FG2,
                        font=("맑은 고딕", 10, "bold"))
        style.map("Treeview", background=[("selected", "#3d3d3d")],
                              foreground=[("selected", FG)])

        # ── 하단 배너 (root에 먼저 pack해야 잘리지 않음) ──
        self._build_banner(self.root)

        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        # ── 상단 고정 바 ──
        topbar = ttk.Frame(outer, padding=(12, 8))
        topbar.grid(row=0, column=0, sticky="ew")
        self._build_topbar(topbar)

        tk.Frame(outer, bg="#444", height=1).grid(row=1, column=0, sticky="ew")

        # ── 탭 ──
        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        tab1 = ttk.Frame(self.notebook)
        tab2 = ttk.Frame(self.notebook)
        tab3 = ttk.Frame(self.notebook)
        tab_search = ttk.Frame(self.notebook)
        self._tab4 = ttk.Frame(self.notebook)
        self.notebook.add(tab1,      text="  시세확인  ")
        self.notebook.add(tab_search,text="  시세찾기  ")
        self.notebook.add(tab3,      text="  ★ 즐겨찾기  ")
        self.notebook.add(tab2,      text="  설정  ")
        # 미리보기 탭: 관리자 모드일 때만 추가 (초기에는 숨김)

        self._build_tab_result(tab1)
        self._build_tab_settings(tab2)
        self._build_tab_favorites(tab3)
        self._build_tab_preview(self._tab4)
        self._price_search_tab = PriceSearchTab(
            tab_search,
            toggle_fav_cb=self._toggle_fav_from_search,
            is_in_fav_cb=self._is_in_fav,
            get_ladder_cb=lambda: self.config.get("ladder", "Ladder"),
            get_mode_cb=lambda: self.config.get("mode", "Softcore"),
            get_season_dates_cb=self._get_season_dates,
        )

        # 즐겨찾기 탭 유료 잠금 표시 업데이트
        self._update_fav_tab_state()
        # 저장된 즐겨찾기 복원
        if self._favorites:
            self._refresh_fav_tree()

        self._setting_widgets = [
            self.proc_combo,
            self.btn_refresh,
            self.btn_hotkey_change,
            self.log_check,
            self.btn_log_path,
            self.btn_ai_keys,
            self.season_combo,
            self.mode_combo,
            self.game_season_combo,
            self.rb_paddle,
            self.rb_ai,
            self.btn_overlay_bg_color,
            self.btn_overlay_text_color,
            self.btn_overlay_color_reset,
        ]

    def _build_topbar(self, parent):
        parent.columnconfigure(3, weight=1)

        ttk.Label(parent, text="D2R Traderie Tracker",
                  font=("맑은 고딕", 11, "bold"),
                  foreground=GOLD).grid(row=0, column=0, padx=(0, 10))

        ttk.Label(parent, text="캡처:", foreground=FG2).grid(
            row=0, column=1, padx=(0, 4))
        self.proc_var = tk.StringVar()
        self.proc_combo = ttk.Combobox(parent, textvariable=self.proc_var,
                                        state="readonly", width=50)
        self.proc_combo.grid(row=0, column=2)
        self.proc_combo.bind("<<ComboboxSelected>>", self._on_proc_change)

        self.btn_refresh = tk.Button(parent, text="↻",
                                      bg="#444", fg=FG,
                                      font=("맑은 고딕", 11),
                                      relief="flat", cursor="hand2", width=2,
                                      command=self._refresh_processes)
        self.btn_refresh.grid(row=0, column=3, padx=(4, 0), sticky="w")

        self.lbl_status = ttk.Label(parent, text="대기 중",
                                     foreground="#888",
                                     font=("맑은 고딕", 10))
        self.lbl_status.grid(row=0, column=4, padx=(10, 10))

        self.btn_start = tk.Button(parent, text="시작",
                                    width=6, bg="#4a7c4e", fg="white",
                                    font=("맑은 고딕", 10, "bold"),
                                    relief="flat", cursor="hand2",
                                    command=self._on_start)
        self.btn_start.grid(row=0, column=5, padx=(0, 4))

        self.btn_stop = tk.Button(parent, text="종료",
                                   width=6, bg="#555", fg="#777",
                                   font=("맑은 고딕", 10, "bold"),
                                   relief="flat", cursor="hand2",
                                   state="disabled",
                                   command=self._on_stop)
        self.btn_stop.grid(row=0, column=6)

    def _build_tab_result(self, parent):
        parent.columnconfigure(0, weight=3)
        # parent.columnconfigure(2, weight=2)  # 미리보기/추출텍스트 패널 비활성화 (주석처리)
        parent.rowconfigure(0, weight=1)

        # ── 좌측: 스캔 목록 ──
        left = ttk.Frame(parent, padding=(10, 10, 6, 10))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        hdr = ttk.Frame(left)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(hdr, text="스캔된 목록",
                  font=("맑은 고딕", 12, "bold"),
                  foreground=GOLD).pack(side="left")
        tk.Button(hdr, text="지우기",
                  bg="#444", fg=FG2, font=("맑은 고딕", 9),
                  relief="flat", cursor="hand2",
                  command=self._clear_scan_list).pack(side="right")

        # ── 게임 정보 (시즌 / 모드 / 버전) — 가로 배치 ──
        game_info_bar = ttk.Frame(left)
        game_info_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(game_info_bar, text="시즌:", foreground=FG2).pack(side="left")
        self.season_var = tk.StringVar()
        self.season_combo = ttk.Combobox(game_info_bar, textvariable=self.season_var,
                                          values=["Ladder", "Non Ladder"],
                                          state="readonly", width=10)
        self.season_combo.pack(side="left", padx=(4, 14))
        self.season_combo.bind("<<ComboboxSelected>>", self._on_game_info_change)

        ttk.Label(game_info_bar, text="모드:", foreground=FG2).pack(side="left")
        self.mode_var = tk.StringVar()
        self.mode_combo = ttk.Combobox(game_info_bar, textvariable=self.mode_var,
                                        values=["Softcore", "Hardcore"],
                                        state="readonly", width=10)
        self.mode_combo.pack(side="left", padx=(4, 14))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_game_info_change)

        ttk.Label(game_info_bar, text="버전:", foreground=FG2).pack(side="left")
        self.ver_classic_var = tk.BooleanVar()
        self.ver_lod_var     = tk.BooleanVar()
        self.ver_d2r_var     = tk.BooleanVar()
        mk_check(game_info_bar, variable=self.ver_classic_var, text="클래식",
                 command=self._on_game_info_change).pack(side="left", padx=(4, 0))
        mk_check(game_info_bar, variable=self.ver_lod_var, text="파괴의군주",
                 command=self._on_game_info_change).pack(side="left", padx=(4, 0))
        mk_check(game_info_bar, variable=self.ver_d2r_var, text="악마술사군림",
                 command=self._on_game_info_change).pack(side="left", padx=(4, 0))

        ttk.Label(game_info_bar, text="가격시즌:", foreground=FG2).pack(side="left", padx=(14, 0))
        self.game_season_var = tk.StringVar()
        _gs_labels = ["전체"] + [f"시즌 {s['season']}" for s in reversed(self._ladder_seasons)]
        self.game_season_combo = ttk.Combobox(game_info_bar, textvariable=self.game_season_var,
                                               values=_gs_labels,
                                               state="readonly", width=8)
        self.game_season_combo.pack(side="left", padx=(4, 0))
        self.game_season_combo.bind("<<ComboboxSelected>>", self._on_game_info_change)

        cols = ("sel", "name", "min", "max", "fav", "requery")
        self.tree = ttk.Treeview(left, columns=cols, show="headings",
                                  selectmode="browse")
        self.tree.heading("sel",     text="선택")
        self.tree.heading("name",    text="아이템이름")
        self.tree.heading("min",     text="최저가")
        self.tree.heading("max",     text="최고가")
        self.tree.heading("fav",     text="즐겨찾기")
        self.tree.heading("requery", text="재조회")
        self.tree.column("sel",     width=40,  stretch=False, anchor="center")
        self.tree.column("name",    width=160, stretch=True,  anchor="w")
        self.tree.column("min",     width=80,  stretch=False, anchor="center")
        self.tree.column("max",     width=80,  stretch=False, anchor="center")
        self.tree.column("fav",     width=80,  stretch=False, anchor="center")
        self.tree.column("requery", width=60,  stretch=False, anchor="center")
        self.tree.grid(row=2, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-1>", self._on_tree_click)

        tree_scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=2, column=1, sticky="ns")
        self.tree.config(yscrollcommand=tree_scroll.set)

        ttk.Label(left, text="더블클릭 → 트레더리 링크 열기",
                  foreground="#555", font=("맑은 고딕", 9)).grid(
                      row=3, column=0, sticky="w", pady=(4, 0))

        self._scan_urls: dict[str, str] = {}
        self._scan_data: dict[str, dict] = {}
        self._scan_counter = 0
        self._scan_selected: set[str] = set()

        # ── 우측: OCR 미리보기 / 추출 텍스트 (주석처리 — 추후 테스트 시 다시 활성화 가능) ──
        # tk.Frame(parent, bg="#444", width=1).grid(row=0, column=1, sticky="ns")
        #
        # right = ttk.Frame(parent, padding=(8, 10, 10, 10))
        # right.grid(row=0, column=2, sticky="nsew")
        # right.columnconfigure(0, weight=1)
        # right.rowconfigure(1, weight=1)
        #
        # ttk.Label(right, text="OCR 미리보기",
        #           font=("맑은 고딕", 11, "bold"),
        #           foreground=GOLD).grid(row=0, column=0, sticky="w", pady=(0, 6))
        #
        # self.preview_label = tk.Label(right, bg="#111111",
        #                                text="캡처 대기 중",
        #                                fg="#444444",
        #                                font=("맑은 고딕", 10),
        #                                relief="flat")
        # self.preview_label.grid(row=1, column=0, sticky="nsew")
        #
        # ttk.Label(right, text="추출 텍스트",
        #           foreground=FG2, font=("맑은 고딕", 9)).grid(
        #               row=2, column=0, sticky="w", pady=(8, 2))
        #
        # self.ocr_text = tk.Text(right, height=7,
        #                          bg="#111111", fg=FG2,
        #                          font=("Consolas", 9),
        #                          relief="flat", state="disabled", wrap="word")
        # self.ocr_text.grid(row=3, column=0, sticky="ew")
        # self.ocr_text.tag_config("highlight", foreground=GOLD,
        #                           font=("Consolas", 9, "bold"))

    def _build_tab_preview(self, parent):
        """개발용 OCR 미리보기 탭: 캡처 이미지 + 추출 텍스트 확인"""
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(1, weight=1)

        ttk.Label(parent, text="OCR 미리보기 (개발용)",
                  font=("맑은 고딕", 12, "bold"),
                  foreground=GOLD).grid(row=0, column=0,
                                        sticky="w", padx=10, pady=(10, 6))

        ttk.Button(parent, text="이미지 파일 불러오기",
                   command=self._on_load_image).grid(
                       row=0, column=1, sticky="e", padx=10, pady=(10, 6))

        left = ttk.Frame(parent, padding=(10, 0, 6, 10))
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        ttk.Label(left, text="캡처 이미지",
                  foreground=FG2, font=("맑은 고딕", 9)).grid(
                      row=0, column=0, sticky="w", pady=(0, 4))

        self.preview_label = tk.Label(left, bg="#111111",
                                       text="캡처 대기 중",
                                       fg="#444444",
                                       font=("맑은 고딕", 10),
                                       relief="flat")
        self.preview_label.grid(row=1, column=0, sticky="nsew")

        right = ttk.Frame(parent, padding=(6, 0, 10, 10))
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(right, text="추출 텍스트",
                  foreground=FG2, font=("맑은 고딕", 9)).grid(
                      row=0, column=0, sticky="w", pady=(0, 4))

        self.ocr_text = tk.Text(right, bg="#111111", fg=FG2,
                                 font=("Consolas", 9),
                                 relief="flat", state="disabled", wrap="word")
        self.ocr_text.grid(row=1, column=0, sticky="nsew")
        self.ocr_text.tag_config("highlight", foreground=GOLD,
                                  font=("Consolas", 9, "bold"))

        text_scroll = ttk.Scrollbar(right, orient="vertical", command=self.ocr_text.yview)
        text_scroll.grid(row=1, column=1, sticky="ns")
        self.ocr_text.config(yscrollcommand=text_scroll.set)

    def _build_banner(self, parent):
        _LINK = "https://link.coupang.com/a/exl17g"
        _IMG  = ("https://ads-partners.coupang.com/banners/960524"
                 "?subId=&traceId=V0-301-879dd1202e5c73b2-I960524&w=728&h=90")

        tk.Frame(parent, bg="#333", height=1).pack(side="bottom", fill="x")

        frame = tk.Frame(parent, bg="#1a1a1a")
        frame.pack(side="bottom", fill="x")

        self._banner_img_ref = None
        self._banner_btn = tk.Label(
            frame, bg="#1a1a1a", cursor="hand2",
            text="🛒  쿠팡에서 쇼핑하기  (클릭)",
            fg=GOLD, font=("맑은 고딕", 10),
        )
        self._banner_btn.pack(pady=(6, 2))
        self._banner_btn.bind("<Button-1>", lambda e: webbrowser.open(_LINK))

        tk.Label(
            frame,
            text="이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
            bg="#1a1a1a", fg="#666", font=("맑은 고딕", 8),
        ).pack(pady=(0, 5))

        threading.Thread(
            target=self._load_banner_image, args=(_IMG, _LINK), daemon=True
        ).start()

    def _load_banner_image(self, url: str, link: str):
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            from io import BytesIO
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                "Referer": "https://link.coupang.com/",
            }
            resp = requests.get(url, timeout=6, headers=headers, verify=False)
            resp.raise_for_status()
            img = PILImage.open(BytesIO(resp.content))
            # 창 너비에 맞게 축소 (최대 원본 728)
            win_w = self.root.winfo_width() or 500
            max_w = min(win_w - 8, img.width)
            h = int(img.height * max_w / img.width)
            img = img.resize((max_w, h), PILImage.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._banner_img_ref = photo  # GC 방지
            self.root.after(0, lambda: self._banner_btn.config(image=photo, text=""))
        except Exception:
            pass  # 네트워크 오류 시 텍스트 버튼 유지

    def _add_settings_section(self, sf, row, title, default_open=False):
        """접고 펴기 가능한 설정 섹션(▶ 접힘 / ▼ 펼침) 헤더를 만들고 콘텐츠 프레임을 반환"""
        header = tk.Frame(sf, bg=BG, cursor="hand2")
        header.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 2))

        arrow_var = tk.StringVar(value="▼" if default_open else "▶")
        arrow_lbl = tk.Label(header, textvariable=arrow_var, bg=BG, fg=FG2,
                              font=("맑은 고딕", 10), width=2)
        arrow_lbl.pack(side="left")
        title_lbl = tk.Label(header, text=title, bg=BG, fg=FG,
                              font=("맑은 고딕", 10, "bold"))
        title_lbl.pack(side="left", padx=(2, 0))

        content = ttk.Frame(sf, padding=(20, 2, 0, 4))
        content.columnconfigure(1, weight=1)
        if default_open:
            content.grid(row=row + 1, column=0, columnspan=3, sticky="ew")

        def _toggle(event=None):
            if content.winfo_manager():
                content.grid_remove()
                arrow_var.set("▶")
            else:
                content.grid(row=row + 1, column=0, columnspan=3, sticky="ew")
                arrow_var.set("▼")

        for w in (header, arrow_lbl, title_lbl):
            w.bind("<Button-1>", _toggle)

        return content

    def _build_tab_settings(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=3)
        parent.rowconfigure(2, weight=2)

        # ── 설정 영역 (스크롤 가능) ──
        scroll_outer = ttk.Frame(parent)
        scroll_outer.grid(row=0, column=0, sticky="nsew")
        scroll_outer.columnconfigure(0, weight=1)
        scroll_outer.rowconfigure(0, weight=1)

        settings_canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0, bd=0)
        settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll = ttk.Scrollbar(scroll_outer, orient="vertical",
                                         command=settings_canvas.yview)
        settings_scroll.grid(row=0, column=1, sticky="ns")
        settings_canvas.config(yscrollcommand=settings_scroll.set)

        sf = ttk.Frame(settings_canvas, padding=(14, 6))
        sf_id = settings_canvas.create_window((0, 0), window=sf, anchor="nw")
        sf.columnconfigure(1, weight=1)

        def _on_sf_configure(event=None):
            settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
        sf.bind("<Configure>", _on_sf_configure)

        def _on_canvas_configure(event):
            settings_canvas.itemconfig(sf_id, width=event.width)
        settings_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            settings_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_wheel(event):
            settings_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_wheel(event):
            settings_canvas.unbind_all("<MouseWheel>")

        settings_canvas.bind("<Enter>", _bind_wheel)
        settings_canvas.bind("<Leave>", _unbind_wheel)

        row = 0

        # 추출 키
        c = self._add_settings_section(sf, row, "추출 키")
        row += 2
        ttk.Label(c, text="추출 키:", foreground=FG2).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.lbl_hotkey_val = ttk.Label(c, text="", foreground=FG,
                                         font=("맑은 고딕", 11))
        self.lbl_hotkey_val.grid(row=0, column=1, sticky="w")
        self.btn_hotkey_change = tk.Button(c, text="변경",
                                            bg="#444", fg=FG2,
                                            font=("맑은 고딕", 9),
                                            relief="flat", cursor="hand2",
                                            command=self._open_hotkey_capture)
        self.btn_hotkey_change.grid(row=0, column=2, sticky="e")

        # OCR 설정
        c = self._add_settings_section(sf, row, "OCR 설정")
        row += 2
        ttk.Label(c, text="OCR 방식:", foreground=FG2).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.ocr_mode_var = tk.StringVar(value=self.config.get("ocr_mode", "paddle"))
        ocr_mode_frame = ttk.Frame(c)
        ocr_mode_frame.grid(row=0, column=1, columnspan=2, sticky="w")
        self.rb_paddle = tk.Radiobutton(
            ocr_mode_frame, text="PaddleOCR (무료·로컬)",
            variable=self.ocr_mode_var, value="paddle",
            bg=BG, fg=FG, selectcolor="#333",
            activebackground=BG, activeforeground=FG,
            font=("맑은 고딕", 10),
            command=self._on_ocr_mode_change)
        self.rb_paddle.pack(side="left")
        self.rb_ai = tk.Radiobutton(
            ocr_mode_frame, text="AI API",
            variable=self.ocr_mode_var, value="ai",
            bg=BG, fg=FG, selectcolor="#333",
            activebackground=BG, activeforeground=FG,
            font=("맑은 고딕", 10),
            command=self._on_ocr_mode_change)
        self.rb_ai.pack(side="left", padx=(12, 0))

        ttk.Label(c, text="AI OCR:", foreground=FG2).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.lbl_ai_provider = ttk.Label(c, text="", foreground="#888",
                                          font=("맑은 고딕", 10))
        self.lbl_ai_provider.grid(row=1, column=1, sticky="w")
        self.btn_ai_keys = tk.Button(c, text="API 키",
                                      bg="#444", fg=FG2,
                                      font=("맑은 고딕", 9),
                                      relief="flat", cursor="hand2",
                                      command=self._open_api_key_dialog)
        self.btn_ai_keys.grid(row=1, column=2, padx=(4, 0))

        ttk.Label(c, text="최대값 여유:", foreground=FG2).grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self.max_offset_var = tk.IntVar(value=self.config.get("option_max_offset", 0))
        self.max_offset_spin = ttk.Spinbox(
            c, from_=0, to=9999, textvariable=self.max_offset_var,
            width=7, command=self._on_max_offset_change)
        self.max_offset_spin.grid(row=2, column=1, sticky="w")
        self.max_offset_spin.bind("<FocusOut>", self._on_max_offset_change)
        self.max_offset_spin.bind("<Return>", self._on_max_offset_change)
        ttk.Label(c, text="(min+N → max)", foreground="#666",
                  font=("맑은 고딕", 9)).grid(row=2, column=2, sticky="w")

        # 로그
        c = self._add_settings_section(sf, row, "로그")
        row += 2
        self.log_var = tk.BooleanVar()
        self.log_check = mk_check(c, variable=self.log_var, text="로그 저장",
                                   command=self._on_log_toggle)
        self.log_check.grid(row=0, column=0, sticky="w")
        self.btn_log_path = tk.Button(c, text="경로 변경",
                                       bg="#444", fg=FG2,
                                       font=("맑은 고딕", 10),
                                       relief="flat", cursor="hand2",
                                       command=self._on_change_log_path)
        self.btn_log_path.grid(row=0, column=2, sticky="e")

        self.lbl_log_path = ttk.Label(c, text="", foreground="#666",
                                       font=("맑은 고딕", 10), wraplength=300)
        self.lbl_log_path.grid(row=1, column=0, columnspan=3, sticky="w")

        # 데이터
        c = self._add_settings_section(sf, row, "데이터")
        row += 2
        ttk.Label(c, text="데이터:", foreground=FG2).grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.lbl_data_date = ttk.Label(c, text="확인 중...",
                                        foreground="#666",
                                        font=("맑은 고딕", 10))
        self.lbl_data_date.grid(row=0, column=1, sticky="w")
        self.btn_data_update = tk.Button(c, text="업데이트",
                                          bg="#444", fg=FG2,
                                          font=("맑은 고딕", 9),
                                          relief="flat", cursor="hand2",
                                          command=self._on_manual_data_update)
        self.btn_data_update.grid(row=0, column=2, sticky="e")

        # 유료 인증
        c = self._add_settings_section(sf, row, "유료 인증")
        row += 2
        ttk.Label(c, text="유료키:", foreground=FG2).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.premium_key_var = tk.StringVar()
        premium_key_frame = ttk.Frame(c)
        premium_key_frame.grid(row=0, column=1, columnspan=2, sticky="ew")
        self._premium_key_entry = tk.Entry(
            premium_key_frame, textvariable=self.premium_key_var,
            width=24, bg="#1e1e1e", fg=FG, insertbackground=FG,
            relief="flat", font=("Consolas", 9), show="•")
        self._premium_key_entry.pack(side="left")
        self._premium_key_entry.bind("<Return>", lambda e: self._on_verify_premium_key())
        self._verify_premium_btn = tk.Button(
            premium_key_frame, text="확인",
            bg="#4a7c4e", fg="white", font=("맑은 고딕", 9),
            relief="flat", cursor="hand2",
            command=self._on_verify_premium_key)
        self._verify_premium_btn.pack(side="left", padx=(4, 0))
        tk.Button(premium_key_frame, text="표시",
                  bg="#444", fg=FG2, font=("맑은 고딕", 9),
                  relief="flat", cursor="hand2",
                  command=lambda: self._premium_key_entry.config(
                      show="" if self._premium_key_entry.cget("show") == "•" else "•"
                  )).pack(side="left", padx=(4, 0))

        self.lbl_premium_status = ttk.Label(
            c, text=f"미인증 (무료버전 - 실행당 {self._FREE_DAILY_LIMIT}회 제한)",
            foreground="#888", font=("맑은 고딕", 10))
        self.lbl_premium_status.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 2))

        # 즐겨찾기 갱신
        c = self._add_settings_section(sf, row, "즐겨찾기 갱신")
        row += 2
        ttk.Label(c, text="즐겨찾기 갱신:", foreground=FG2).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.fav_refresh_var = tk.IntVar(value=self.config.get("fav_refresh_min", 5))
        self.fav_refresh_spin = ttk.Spinbox(
            c, from_=5, to=60, increment=5,
            textvariable=self.fav_refresh_var, width=6,
            command=self._on_fav_refresh_change)
        self.fav_refresh_spin.grid(row=0, column=1, sticky="w")
        self.fav_refresh_spin.bind("<FocusOut>", self._on_fav_refresh_change)
        self.fav_refresh_spin.bind("<Return>", self._on_fav_refresh_change)
        ttk.Label(c, text="분 (무료: 20회 한도에 포함)", foreground=FG2, font=("맑은 고딕", 10)).grid(
            row=0, column=2, sticky="w")

        ttk.Label(c, text="오버레이 표시 주기:", foreground=FG2).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.fav_overlay_interval_var = tk.IntVar(
            value=self.config.get("fav_overlay_interval_min", 5))
        self.fav_overlay_interval_spin = ttk.Spinbox(
            c, from_=1, to=60, increment=1,
            textvariable=self.fav_overlay_interval_var, width=6,
            command=self._on_fav_overlay_interval_change)
        self.fav_overlay_interval_spin.grid(row=1, column=1, sticky="w")
        self.fav_overlay_interval_spin.bind("<FocusOut>", self._on_fav_overlay_interval_change)
        self.fav_overlay_interval_spin.bind("<Return>", self._on_fav_overlay_interval_change)
        ttk.Label(c, text="분마다 표시 (유료 전용)", foreground=FG2, font=("맑은 고딕", 10)).grid(
            row=1, column=2, sticky="w")  # 오버레이 자동순환은 유료 전용 유지

        # 오버레이
        c = self._add_settings_section(sf, row, "오버레이")
        row += 2
        ttk.Label(c, text="Y 좌표 (px):", foreground=FG2).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.overlay_offset_var = tk.IntVar(
            value=self.config.get("overlay_bottom_offset", 180))
        offset_spin = ttk.Spinbox(
            c, from_=0, to=2000, textvariable=self.overlay_offset_var,
            width=6, command=self._on_overlay_offset_change)
        offset_spin.grid(row=0, column=1, sticky="w")
        offset_spin.bind("<FocusOut>", self._on_overlay_offset_change)
        offset_spin.bind("<Return>",   self._on_overlay_offset_change)
        ttk.Label(c, text="px  (화면 상단에서의 거리)",
                  foreground="#666", font=("맑은 고딕", 9)).grid(
                      row=0, column=2, sticky="w")

        ttk.Label(c, text="색상:", foreground=FG2).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        _color_frame = tk.Frame(c, bg=BG)
        _color_frame.grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Label(_color_frame, text="배경", foreground=FG2,
                  font=("맑은 고딕", 9)).pack(side="left", padx=(0, 3))
        self.btn_overlay_bg_color = tk.Button(
            _color_frame, text="  ",
            bg=self.config.get("overlay_bg_color", "#111111"),
            width=3, relief="solid", borderwidth=1, cursor="hand2",
            command=lambda: self._on_overlay_color_change("bg"))
        self.btn_overlay_bg_color.pack(side="left", padx=(0, 12))
        ttk.Label(_color_frame, text="글자", foreground=FG2,
                  font=("맑은 고딕", 9)).pack(side="left", padx=(0, 3))
        self.btn_overlay_text_color = tk.Button(
            _color_frame, text="  ",
            bg=self.config.get("overlay_text_color", "#d4a843"),
            width=3, relief="solid", borderwidth=1, cursor="hand2",
            command=lambda: self._on_overlay_color_change("text"))
        self.btn_overlay_text_color.pack(side="left")
        self.btn_overlay_color_reset = tk.Button(
            _color_frame, text="기본값",
            bg="#444", fg=FG2, font=("맑은 고딕", 9),
            relief="flat", cursor="hand2",
            command=self._on_overlay_color_reset)
        self.btn_overlay_color_reset.pack(side="left", padx=(12, 0))

        ttk.Label(c, text="글씨 크기:", foreground=FG2).grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self.overlay_font_extra_var = tk.IntVar(
            value=self.config.get("overlay_font_extra", 0))
        overlay_font_spin = ttk.Spinbox(
            c, from_=0, to=10, increment=1,
            textvariable=self.overlay_font_extra_var, width=6,
            command=self._on_overlay_font_change)
        overlay_font_spin.grid(row=2, column=1, sticky="w")
        overlay_font_spin.bind("<FocusOut>", self._on_overlay_font_change)
        overlay_font_spin.bind("<Return>",   self._on_overlay_font_change)
        ttk.Label(c, text="기본(11pt) + 0~10pt",
                  foreground="#666", font=("맑은 고딕", 9)).grid(
                      row=2, column=2, sticky="w")

        ttk.Label(c, text="오버레이:", foreground=FG2).grid(
            row=3, column=0, sticky="w", padx=(0, 8))
        _sample_frame = tk.Frame(c, bg=BG)
        _sample_frame.grid(row=3, column=2, sticky="e")
        self.btn_free_sample = tk.Button(
            _sample_frame, text="무료샘플보기",
            bg="#444", fg=FG2, font=("맑은 고딕", 9),
            relief="flat", cursor="hand2",
            command=self._show_single_overlay_sample)
        self.btn_free_sample.pack(side="left", padx=(0, 4))
        self.btn_fav_sample = tk.Button(
            _sample_frame, text="즐겨찾기샘플보기",
            bg="#444", fg=FG2, font=("맑은 고딕", 9),
            relief="flat", cursor="hand2",
            command=self._show_fav_overlay_sample_btn)
        self.btn_fav_sample.pack(side="left")

        # ── 구분선 ──
        tk.Frame(parent, bg="#444", height=1).grid(row=1, column=0, sticky="ew")

        # ── 로그창 ──
        log_frame = ttk.Frame(parent, padding=(8, 4))
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        log_hdr = ttk.Frame(log_frame)
        log_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(log_hdr, text="로그",
                  font=("맑은 고딕", 10, "bold"),
                  foreground=FG2).pack(side="left")
        tk.Button(log_hdr, text="지우기",
                  bg="#333", fg=FG2, font=("맑은 고딕", 8),
                  relief="flat", cursor="hand2",
                  command=self._clear_log).pack(side="right")

        self.log_text = tk.Text(
            log_frame, height=8,
            bg="#1a1a1a", fg="#aaaaaa",
            font=("Consolas", 9),
            relief="flat", state="disabled", wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                    command=self.log_text.yview)
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.config(yscrollcommand=log_scroll.set)

        self.log_text.tag_config("info",    foreground="#aaaaaa")
        self.log_text.tag_config("success", foreground="#66ff66")
        self.log_text.tag_config("warn",    foreground="#ffcc44")
        self.log_text.tag_config("error",   foreground="#ff6666")

    def _build_tab_favorites(self, parent):
        """즐겨찾기 탭 구성 (무료: 목록 관리만 / 유료: 자동갱신+오버레이 추가)"""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)

        # ── 잠금 안내 프레임 (더이상 탭 전체를 가리지 않음 — 유지 호환용) ──
        self._fav_lock_frame = tk.Frame(parent, bg="#666666")

        # ── 무료 버전 안내 배너 ──
        self._fav_free_banner = tk.Label(
            parent,
            text="무료버전: 즐겨찾기 최대 3개 / 자동갱신 횟수 한도 포함 / 오버레이 자동순환은 유료 전용입니다.",
            bg="#3a3a1a", fg=GOLD, font=("맑은 고딕", 9),
            anchor="w", padx=8, pady=4)
        self._fav_free_banner.grid(row=1, column=0, sticky="ew")

        # ── PanedWindow: 사용자가 가로 구분선을 드래그해 좌/우 비율 조절 ──
        paned = tk.PanedWindow(parent, orient="horizontal",
                               bg="#444", sashwidth=5, sashrelief="flat",
                               handlesize=0)
        paned.grid(row=0, column=0, sticky="nsew")

        # ── 좌측: 즐겨찾기 목록 ──
        left = ttk.Frame(paned, padding=(10, 10, 6, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        hdr = ttk.Frame(left)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(hdr, text="즐겨찾기 목록",
                  font=("맑은 고딕", 12, "bold"),
                  foreground=GOLD).pack(side="left")

        self.lbl_fav_countdown = ttk.Label(hdr, text="",
                                            foreground="#888",
                                            font=("맑은 고딕", 9))
        self.lbl_fav_countdown.pack(side="left", padx=(14, 0))

        tk.Button(hdr, text="지우기",
                  bg="#444", fg=FG2, font=("맑은 고딕", 9),
                  relief="flat", cursor="hand2",
                  command=self._clear_favorites).pack(side="right", padx=(0, 4))

        _fav_style = ttk.Style()
        _fav_style.configure("Fav.Treeview", rowheight=22)
        _fav_style.map("Fav.Treeview",
                       background=[("selected", "#555555")],
                       foreground=[("selected", FG)])

        fav_cols = ("name", "min", "max", "query")
        self.fav_tree = ttk.Treeview(left, columns=fav_cols, show="headings",
                                      selectmode="browse", style="Fav.Treeview")
        self.fav_tree.heading("name",  text="아이템이름")
        self.fav_tree.heading("min",   text="최저가")
        self.fav_tree.heading("max",   text="최고가")
        self.fav_tree.heading("query", text="조회")
        self.fav_tree.column("name",  width=160, stretch=True, anchor="center")
        self.fav_tree.column("min",   width=100, stretch=True, anchor="center")
        self.fav_tree.column("max",   width=100, stretch=True, anchor="center")
        self.fav_tree.column("query", width=50,  stretch=False, anchor="center")
        self.fav_tree.grid(row=1, column=0, sticky="nsew")
        self.fav_tree.bind("<<TreeviewSelect>>", self._on_fav_select)
        self.fav_tree.bind("<Double-1>", self._on_fav_double_click)
        self.fav_tree.bind("<Button-1>", self._on_fav_click)

        fav_scroll = ttk.Scrollbar(left, orient="vertical", command=self.fav_tree.yview)
        fav_scroll.grid(row=1, column=1, sticky="ns")
        self.fav_tree.config(yscrollcommand=fav_scroll.set)

        ttk.Label(left, text="더블클릭 → 트레더리 열기  /  선택 → 옵션 보기",
                  foreground="#555", font=("맑은 고딕", 9)).grid(
                      row=2, column=0, sticky="w", pady=(4, 0))

        paned.add(left, minsize=200, width=480)

        # ── 우측: 옵션 상세 ──
        right = ttk.Frame(paned, padding=(8, 10, 10, 10))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        detail_hdr = ttk.Frame(right)
        detail_hdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(detail_hdr, text="옵션 상세",
                  font=("맑은 고딕", 11, "bold"),
                  foreground=GOLD).pack(side="left")
        tk.Button(detail_hdr, text="전체해제",
                  bg="#555", fg=FG2, font=("맑은 고딕", 9),
                  relief="flat", cursor="hand2",
                  command=self._fav_select_none).pack(side="right", padx=(4, 0))
        tk.Button(detail_hdr, text="전체선택",
                  bg="#444", fg=FG, font=("맑은 고딕", 9),
                  relief="flat", cursor="hand2",
                  command=self._fav_select_all).pack(side="right")

        # ── 별칭 편집 행 ──
        alias_row = ttk.Frame(right)
        alias_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(alias_row, text="별칭:", foreground=FG2,
                  font=("맑은 고딕", 9)).pack(side="left")
        self._fav_alias_var = tk.StringVar()
        self._fav_alias_entry = tk.Entry(
            alias_row, textvariable=self._fav_alias_var,
            width=20, bg="#3a3a3a", fg=FG,
            insertbackground=FG, relief="flat", font=("맑은 고딕", 10))
        self._fav_alias_entry.pack(side="left", padx=(4, 6))
        tk.Button(alias_row, text="저장",
                  bg="#444", fg=FG, font=("맑은 고딕", 9),
                  relief="flat", cursor="hand2",
                  command=self._save_fav_alias).pack(side="left")
        ttk.Label(alias_row, text="(오버레이에서 아이템이름 대신 표시)",
                  foreground="#666", font=("맑은 고딕", 8)).pack(side="left", padx=(8, 0))

        self.lbl_fav_query_result = ttk.Label(right, text="",
                                               foreground=GOLD, font=("맑은 고딕", 9))
        self.lbl_fav_query_result.grid(row=2, column=0, sticky="w", pady=(0, 4))

        self.fav_detail_frame = ttk.Frame(right)
        self.fav_detail_frame.grid(row=3, column=0, sticky="nsew")
        self.fav_detail_frame.columnconfigure(0, weight=0)   # 체크박스
        self.fav_detail_frame.columnconfigure(1, weight=0)   # 이름
        self.fav_detail_frame.columnconfigure(2, weight=1)   # 위젯

        paned.add(right, minsize=150)

    # ────────────────────── OCR 미리보기 ─────────────────────────
    def _update_preview(self, img, lines: list[str] = None, item_name: str = ""):
        """'미리보기' 탭 업데이트 (메인 스레드에서 호출) — 개발 단계 OCR 확인용"""
        try:
            pw = self.preview_label.winfo_width()
            ph = self.preview_label.winfo_height()
            pw = pw if pw > 20 else 240
            ph = ph if ph > 20 else 180
            img_copy = img.copy()
            img_copy.thumbnail((pw, ph), PILImage.LANCZOS)
            self._preview_img_tk = ImageTk.PhotoImage(img_copy)
            self.preview_label.config(image=self._preview_img_tk, text="")
        except Exception:
            self.preview_label.config(image="", text="미리보기 실패")

        self.ocr_text.config(state="normal")
        self.ocr_text.delete("1.0", "end")
        for line in (lines or []):
            tag = "highlight" if (item_name and item_name in line) else ""
            self.ocr_text.insert("end", line + "\n", tag)
        self.ocr_text.config(state="disabled")

    # ────────────────────── 설정 적용 ────────────────────────────
    def _apply_config(self):
        display = hotkey_display_name(self.config.get("hotkey", "print_screen"))
        self.lbl_hotkey_val.config(text=display)

        self.log_var.set(self.config.get("log_enabled", False))
        self.logger.set_enabled(self.log_var.get())
        self.logger.set_log_dir(self.config.get("log_path", LOG_DEFAULT_ROOT))
        self._update_log_path_label()

        self.season_var.set(self.config.get("ladder", "Ladder"))
        self.mode_var.set(self.config.get("mode", "Softcore"))
        gs = self.config.get("ladder_season", 0)
        self.game_season_var.set("전체" if not gs else f"시즌 {gs}")
        versions = self.config.get("versions", [])
        self.ver_classic_var.set("classic" in versions)
        self.ver_lod_var.set("lord of destruction" in versions)
        self.ver_d2r_var.set("reign of the warlock" in versions)
        clean_versions = []
        if self.ver_classic_var.get():
            clean_versions.append("classic")
        if self.ver_lod_var.get():
            clean_versions.append("lord of destruction")
        if self.ver_d2r_var.get():
            clean_versions.append("reign of the warlock")
        self.config["versions"] = clean_versions

        self.max_offset_var.set(self.config.get("option_max_offset", 0))
        self.ocr_mode_var.set(self.config.get("ocr_mode", "paddle"))
        self._update_ai_provider_label()
        self._update_ocr_mode_ui()
        _off = self.config.get("overlay_bottom_offset", 180)
        self.overlay_offset_var.set(_off)
        self.overlay.set_bottom_offset(_off)
        self.fav_overlay.set_bottom_offset(_off)
        _bg_c  = self.config.get("overlay_bg_color",   "#111111")
        _txt_c = self.config.get("overlay_text_color", "#d4a843")
        set_overlay_colors(bg=_bg_c, text=_txt_c)
        self.btn_overlay_bg_color.config(bg=_bg_c)
        self.btn_overlay_text_color.config(bg=_txt_c)
        _font_extra = self.config.get("overlay_font_extra", 0)
        self.overlay_font_extra_var.set(_font_extra)
        set_overlay_font_extra(_font_extra)
        self.premium_key_var.set(self.config.get("premium_key", ""))
        self.fav_refresh_var.set(self.config.get("fav_refresh_min", 5))
        self.fav_overlay_interval_var.set(self.config.get("fav_overlay_interval_min", 5))
        self._update_premium_status_label()
        self._update_fav_tab_state()
        self._update_preview_tab_visibility()

    # ────────────────────── 프로세스 목록 ────────────────────────
    def _refresh_processes(self):
        def _load():
            procs = get_window_processes()
            self._proc_map = {p.display_name(): p for p in procs}
            display_list = list(self._proc_map.keys())
            self.root.after(0, lambda: self._update_proc_combo(display_list))

        threading.Thread(target=_load, daemon=True).start()

    def _update_proc_combo(self, display_list: list[str]):
        self.proc_combo.config(values=display_list)

        prev = self.proc_var.get()
        if prev and prev in self._proc_map:
            pass
        else:
            d2r_key = next(
                (k for k in display_list
                 if any(kw in k.lower() for kw in ('diablo', 'd2r', 'd2resurrected'))),
                None
            )
            if d2r_key:
                self.proc_var.set(d2r_key)
                self._selected_proc = self._proc_map[d2r_key]
            elif display_list:
                self.proc_var.set(display_list[0])
                self._selected_proc = self._proc_map[display_list[0]]

        saved_proc = self.config.get("target_process", "")
        if saved_proc:
            match = next((k for k in display_list if saved_proc in k), None)
            if match:
                self.proc_var.set(match)
                self._selected_proc = self._proc_map[match]

    def _on_proc_change(self, event=None):
        key = self.proc_var.get()
        proc = self._proc_map.get(key)
        self._selected_proc = proc
        if proc:
            self.config["target_process"] = proc.proc_name
            save_config(self.config)

    # ────────────────────── 설정 잠금/해제 ───────────────────────
    def _lock_settings(self):
        for w in self._setting_widgets:
            try:
                if isinstance(w, ttk.Combobox):
                    w.config(state="disabled")
                else:
                    w.config(state="disabled")
            except Exception:
                pass

    def _unlock_settings(self):
        for w in self._setting_widgets:
            try:
                if isinstance(w, ttk.Combobox):
                    w.config(state="readonly")
                else:
                    w.config(state="normal")
            except Exception:
                pass

    # ────────────────────── 이벤트 핸들러 ────────────────────────
    def _on_start(self):
        if self.is_tracking:
            return

        ocr_mode = self.config.get("ocr_mode", "paddle")

        # 무료버전에서 AI 모드 선택 시 paddle로 강제 전환
        if not self._is_premium and ocr_mode == "ai":
            self.ocr_mode_var.set("paddle")
            self.config["ocr_mode"] = "paddle"
            save_config(self.config)
            self._update_ocr_mode_ui()
            self._append_log("무료버전에서는 AI API 모드를 사용할 수 없습니다. PaddleOCR로 전환합니다.", "warn")
            ocr_mode = "paddle"

        if ocr_mode == "paddle":
            if not self.paddle_bridge.is_ready():
                self._show_paddle_download_dialog()
                return
        else:
            if not self.ai_bridge.has_any_key():
                self._set_status("API 키 없음 - '설정' 탭에서 입력하세요")
                return

        self._do_start()

    def _do_start(self):
        ocr_mode = self.config.get("ocr_mode", "paddle")
        self._set_status("추적 시작 중...")
        self.btn_start.config(state="disabled", bg="#555", fg="#777")
        self._lock_settings()

        self.is_tracking = True
        hotkey_val = self.config.get("hotkey", "print_screen")
        self.hotkey_listener.set_hotkey(hotkey_val, self._on_trigger)

        if ocr_mode == "paddle":
            ocr_label = "PaddleOCR (로컬)"
        else:
            ocr_label = f"AI: {self.ai_bridge.current_provider_name}"

        self._append_log(
            f"추적 시작 — {ocr_label} / 핫키: {hotkey_display_name(hotkey_val)}", "success")
        self._start_tray()
        if self._is_premium and self._favorites:
            self.fav_overlay.set_items(self._favorites)
            self._start_fav_overlay_cycle()
        if self._favorites:
            self._start_fav_price_refresh()
        self._start_process_watch()
        self._tracking_started()

    def _tracking_started(self):
        hotkey_disp = hotkey_display_name(self.config.get("hotkey", "print_screen"))
        _pname = self._selected_proc.window_title if self._selected_proc else "전체 화면"
        _pdisplay = _pname[:30] + "…" if len(_pname) > 30 else _pname
        self._set_status(f"추적 중  [{hotkey_disp}]  |  {_pdisplay}")
        self.btn_start.config(state="disabled", bg="#555", fg="#777")
        self.btn_stop.config(state="normal", bg="#7c4a4a", fg="white")
        self.root.update_idletasks()
        self.root.after(50, self.root.iconify)

    def _on_stop(self):
        if not self.is_tracking:
            return
        self.is_tracking = False
        self.hotkey_listener.stop()
        self._stop_tray()
        self._stop_fav_overlay_cycle()
        self.fav_overlay.stop()
        self._fav_overlay_paused = False
        if self._fav_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._fav_refresh_after_id)
            except Exception:
                pass
            self._fav_refresh_after_id = None
        if self._fav_countdown_id is not None:
            try:
                self.root.after_cancel(self._fav_countdown_id)
            except Exception:
                pass
            self._fav_countdown_id = None
        self.lbl_fav_countdown.config(text="")
        if self._proc_check_after_id is not None:
            try:
                self.root.after_cancel(self._proc_check_after_id)
            except Exception:
                pass
            self._proc_check_after_id = None
        self._set_status("대기 중")
        self.btn_start.config(state="normal", bg="#4a7c4e", fg="white")
        self.btn_stop.config(state="disabled", bg="#555", fg="#777")
        self._unlock_settings()

    # ────────────────────── 대상 프로세스 종료 감지 ──────────────────
    def _start_process_watch(self):
        self._proc_check_after_id = self.root.after(3000, self._check_process_alive)

    def _check_process_alive(self):
        if not self.is_tracking:
            return
        proc = self._selected_proc
        if proc and proc.pid and not psutil.pid_exists(proc.pid):
            self._append_log(
                f"모니터링 대상 프로세스({proc.window_title})가 종료되어 모니터링을 종료합니다.", "warn")
            self._on_stop()
            return
        self._proc_check_after_id = self.root.after(3000, self._check_process_alive)

    def _on_max_offset_change(self, event=None):
        try:
            val = int(self.max_offset_var.get())
            val = max(0, val)
        except (ValueError, tk.TclError):
            val = 0
        self.config["option_max_offset"] = val
        save_config(self.config)

    def _open_hotkey_capture(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("핫키 설정")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.wm_attributes("-topmost", True)
        dialog.grab_set()

        tk.Label(dialog, text="아무 키나 누르세요",
                 bg=BG, fg=FG, font=("맑은 고딕", 14, "bold")).pack(padx=60, pady=(28, 6))
        tk.Label(dialog, text="Ctrl / Alt / Shift 조합도 가능합니다",
                 bg=BG, fg=FG2, font=("맑은 고딕", 9)).pack(pady=(0, 28))

        def _captured(key_str: str):
            dialog.after(0, lambda: self._apply_hotkey(key_str))
            dialog.after(0, dialog.destroy)

        hook_ref = capture_next_key(_captured)

        def _cancel():
            if hook_ref[0] is not None:
                import keyboard as _kb
                try:
                    _kb.unhook(hook_ref[0])
                except Exception:
                    pass
                hook_ref[0] = None
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        tk.Button(dialog, text="취소",
                  bg="#555", fg=FG2, font=("맑은 고딕", 10),
                  relief="flat", cursor="hand2",
                  command=_cancel).pack(pady=(0, 20))

    def _apply_hotkey(self, key_str: str):
        display = hotkey_display_name(key_str)
        self.lbl_hotkey_val.config(text=display)
        self.config["hotkey"] = key_str
        save_config(self.config)

    def _on_game_info_change(self, event=None):
        self.config["ladder"] = self.season_var.get()
        self.config["mode"] = self.mode_var.get()
        gs_label = self.game_season_var.get()
        if gs_label == "전체":
            self.config["ladder_season"] = 0
        else:
            try:
                self.config["ladder_season"] = int(gs_label.replace("시즌 ", ""))
            except ValueError:
                self.config["ladder_season"] = 0
        versions = []
        if self.ver_classic_var.get():
            versions.append("classic")
        if self.ver_lod_var.get():
            versions.append("lord of destruction")
        if self.ver_d2r_var.get():
            versions.append("reign of the warlock")
        self.config["versions"] = versions
        save_config(self.config)

    def _get_season_dates(self) -> tuple:
        """(season_start, season_end, is_current_season) 반환.
        is_current_season=True: 진행 중인 시즌 → 1일 필터 적용."""
        from datetime import date as _dt
        season_num = self.config.get("ladder_season", 0)
        if not season_num:
            return None, None, False
        today = _dt.today()
        for s in self._ladder_seasons:
            if s["season"] == season_num:
                end = s.get("end")
                if end in (None, "null", ""):
                    end = None
                is_current = (end is None) or (
                    _dt.fromisoformat(str(end)[:10]) >= today
                )
                return s["start"], end, is_current
        return None, None, False

    def _update_ai_provider_label(self):
        self.lbl_ai_provider.config(text=self.ai_bridge.current_provider_name)

    def _open_api_key_dialog(self):
        keys = load_ai_keys()
        dialog = tk.Toplevel(self.root)
        dialog.title("AI API 키 설정")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.wm_attributes("-topmost", True)
        dialog.grab_set()

        tk.Label(dialog,
                 text="무료 API 할당량 소진 시 순서대로 자동 전환됩니다.\n▲▼ 버튼으로 호출 순서를 변경하세요.",
                 bg=BG, fg=FG2, font=("맑은 고딕", 9), justify="left").grid(
                     row=0, column=0, columnspan=4, sticky="w",
                     padx=12, pady=(10, 6))

        ALL_PROVIDERS = {
            "gemini": "Gemini 2.5 Flash",
            "groq":   "Groq (Llama 4)",
        }

        saved_order = [p for p in keys.get("order", ["groq", "gemini"]) if p in ALL_PROVIDERS]
        # order에 누락된 항목 보충
        for p in ALL_PROVIDERS:
            if p not in saved_order:
                saved_order.append(p)
        order_var = list(saved_order)  # 현재 순서 (변경 가능)

        entries = {k: tk.StringVar(value=keys.get(k, "")) for k in ALL_PROVIDERS}
        model_entries = {k: tk.StringVar(value=keys.get(f"{k}_model", "")) for k in ALL_PROVIDERS}

        # 행 프레임을 재렌더링하는 함수
        row_frames = {}

        def _render_rows():
            for f in row_frames.values():
                f.destroy()
            row_frames.clear()
            for rank, key in enumerate(order_var):
                label = ALL_PROVIDERS[key]
                base_row = 1 + rank * 3

                lf = tk.Frame(dialog, bg=BG)
                lf.grid(row=base_row, column=0, sticky="w", padx=(12, 4), pady=(6, 0))
                row_frames[f"lbl_{key}"] = lf

                # 순서 번호
                tk.Label(lf, text=f"{rank+1}.", bg=BG, fg="#888",
                         font=("맑은 고딕", 9), width=2).pack(side="left")
                tk.Label(lf, text=label, bg=BG, fg=FG,
                         font=("맑은 고딕", 10, "bold")).pack(side="left")
                has_key = bool(entries[key].get().strip())
                tk.Label(lf, text=" ✓설정됨" if has_key else " 미설정",
                         bg=BG, fg=GREEN if has_key else "#666",
                         font=("맑은 고딕", 9)).pack(side="left", padx=(4, 0))

                # ▲▼ 버튼
                btn_f = tk.Frame(dialog, bg=BG)
                btn_f.grid(row=base_row, column=1, padx=(0, 4), pady=(6, 0), sticky="e")
                row_frames[f"btn_{key}"] = btn_f
                tk.Button(btn_f, text="▲", bg="#444", fg=FG2,
                          font=("맑은 고딕", 8), relief="flat", cursor="hand2", width=2,
                          command=lambda k=key: _move(k, -1)).pack(side="left", padx=(0, 1))
                tk.Button(btn_f, text="▼", bg="#444", fg=FG2,
                          font=("맑은 고딕", 8), relief="flat", cursor="hand2", width=2,
                          command=lambda k=key: _move(k, 1)).pack(side="left")

                # API 키 입력창
                ent = tk.Entry(dialog, textvariable=entries[key], width=38,
                               bg="#1e1e1e", fg=FG, insertbackground=FG,
                               relief="flat", font=("Consolas", 9), show="•")
                ent.grid(row=base_row + 1, column=0, columnspan=3,
                         padx=(12, 4), pady=(2, 0), sticky="ew")
                row_frames[f"ent_{key}"] = ent

                tk.Button(dialog, text="표시",
                          bg="#444", fg=FG2, font=("맑은 고딕", 9),
                          relief="flat", cursor="hand2",
                          command=lambda e=ent: e.config(
                              show="" if e.cget("show") == "•" else "•")).grid(
                                  row=base_row + 1, column=3, padx=(0, 12), pady=(2, 0))

                # 모델명 입력창
                mf = tk.Frame(dialog, bg=BG)
                mf.grid(row=base_row + 2, column=0, columnspan=4,
                        padx=(12, 12), pady=(2, 4), sticky="ew")
                row_frames[f"mf_{key}"] = mf
                tk.Label(mf, text="모델:", bg=BG, fg="#888",
                         font=("맑은 고딕", 9), width=4, anchor="w").pack(side="left")
                tk.Entry(mf, textvariable=model_entries[key], width=42,
                         bg="#1e1e1e", fg="#aaa", insertbackground=FG,
                         relief="flat", font=("Consolas", 9)).pack(side="left", fill="x", expand=True)

        def _move(key, direction):
            idx = order_var.index(key)
            new_idx = idx + direction
            if 0 <= new_idx < len(order_var):
                order_var[idx], order_var[new_idx] = order_var[new_idx], order_var[idx]
                _render_rows()
                _update_btn_row()

        def _update_btn_row():
            n = len(ALL_PROVIDERS)
            btn_frame.grid(row=1 + n * 3, column=0, columnspan=4, pady=(12, 12))

        _render_rows()
        n = len(ALL_PROVIDERS)

        def _save():
            new_keys = {k: v.get().strip() for k, v in entries.items()}
            for k, mv in model_entries.items():
                new_keys[f"{k}_model"] = mv.get().strip()
            new_keys["order"] = order_var[:]
            save_ai_keys(new_keys)
            self.ai_bridge.reset_provider()
            self.root.after(0, lambda: self._append_log("API 키가 저장됐습니다.", "info"))
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.grid(row=1 + n * 3, column=0, columnspan=4, pady=(12, 12))
        tk.Button(btn_frame, text="저장", width=10,
                  bg="#4a7c4e", fg="white",
                  font=("맑은 고딕", 10, "bold"),
                  relief="flat", cursor="hand2",
                  command=_save).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="취소", width=10,
                  bg="#555", fg=FG2,
                  font=("맑은 고딕", 10),
                  relief="flat", cursor="hand2",
                  command=dialog.destroy).pack(side="left")


    def _on_overlay_color_change(self, kind: str):
        current = self.config.get(
            "overlay_bg_color" if kind == "bg" else "overlay_text_color",
            "#111111" if kind == "bg" else "#d4a843")
        result = colorchooser.askcolor(color=current, parent=self.root,
                                       title="배경색 선택" if kind == "bg" else "글자색 선택")
        color = result[1]
        if not color:
            return
        if kind == "bg":
            self.config["overlay_bg_color"] = color
            self.btn_overlay_bg_color.config(bg=color)
        else:
            self.config["overlay_text_color"] = color
            self.btn_overlay_text_color.config(bg=color)
        set_overlay_colors(
            bg=self.config.get("overlay_bg_color"),
            text=self.config.get("overlay_text_color"))
        from config import save_config
        save_config(self.config)

    def _on_overlay_color_reset(self):
        _DEF_BG  = "#111111"
        _DEF_TXT = "#d4a843"
        self.config["overlay_bg_color"]   = _DEF_BG
        self.config["overlay_text_color"] = _DEF_TXT
        self.btn_overlay_bg_color.config(bg=_DEF_BG)
        self.btn_overlay_text_color.config(bg=_DEF_TXT)
        set_overlay_colors(bg=_DEF_BG, text=_DEF_TXT)
        from config import save_config
        save_config(self.config)

    def _on_overlay_font_change(self, event=None):
        try:
            val = int(self.overlay_font_extra_var.get())
            val = max(0, min(10, val))
        except (ValueError, TypeError):
            val = 0
        self.overlay_font_extra_var.set(val)
        self.config["overlay_font_extra"] = val
        set_overlay_font_extra(val)
        from config import save_config
        save_config(self.config)

    def _on_overlay_offset_change(self, event=None):
        try:
            val = int(self.overlay_offset_var.get())
            val = max(0, min(2000, val))
        except (ValueError, tk.TclError):
            val = 180
        self.overlay_offset_var.set(val)
        self.config["overlay_bottom_offset"] = val
        self.overlay.set_bottom_offset(val)
        self.fav_overlay.set_bottom_offset(val)
        from config import save_config
        save_config(self.config)

    _SAMPLE_FAV_ITEMS = [
        {"name": "메피스토의 두개골", "url": "https://traderie.com", "min_price": "Vex",  "max_price": "Ohm",    "slot": "head"},
        {"name": "윈드포스",        "url": "https://traderie.com", "min_price": "Jah",  "max_price": "Cham 2개","slot": "weapon"},
        {"name": "집착",            "url": "https://traderie.com", "min_price": "Pul",  "max_price": "Um",     "slot": "ring"},
    ]

    def _show_single_overlay_sample(self):
        self._on_overlay_offset_change()
        self.overlay.show(
            item_name="메피스토의 두개골",
            traderie_url="https://traderie.com",
            min_price="Vex",
            max_price="Ohm",
            count=5,
            slot="head",
        )

    def _show_fav_overlay_sample_btn(self):
        """즐겨찾기샘플보기 버튼 핸들러 (유료 전용) — 항상 샘플 데이터 사용"""
        if not self._is_premium:
            return
        self._on_overlay_offset_change()
        self._show_fav_overlay_sample(self._SAMPLE_FAV_ITEMS)

    def _show_fav_overlay_sample(self, sample_items: list[dict]):
        if self._overlay_sample_preview is not None:
            self._overlay_sample_preview.stop()
            self._overlay_sample_preview = None

        preview = FavoriteOverlay(
            self.root, proc_getter=lambda: self._selected_proc)
        preview.set_bottom_offset(self.config.get("overlay_bottom_offset", 180))
        preview.set_items(sample_items)
        preview.start()
        self._overlay_sample_preview = preview
        self.root.after(8000, self._stop_fav_overlay_sample)

    def _stop_fav_overlay_sample(self):
        if self._overlay_sample_preview is not None:
            self._overlay_sample_preview.stop()
            self._overlay_sample_preview = None

    def _on_log_toggle(self):
        enabled = self.log_var.get()
        self.config["log_enabled"] = enabled
        self.logger.set_enabled(enabled)
        save_config(self.config)
        self._update_log_path_label()

    def _on_change_log_path(self):
        path = filedialog.askdirectory(
            title="로그 저장 폴더 선택",
            initialdir=self.config.get("log_path", LOG_DEFAULT_ROOT)
        )
        if path:
            self.config["log_path"] = path
            self.logger.set_log_dir(path)
            save_config(self.config)
            self._update_log_path_label()

    def _update_log_path_label(self):
        if self.log_var.get():
            path = self.logger.get_log_path_display()
            if len(path) > 38:
                path = "..." + path[-35:]
            self.lbl_log_path.config(text=path, foreground="#888")
        else:
            self.lbl_log_path.config(text="(로그 비활성화)", foreground="#555")

    # ────────────────────── 데이터 업데이트 ──────────────────────
    def _auto_update_data(self):
        self._refresh_data_label()
        threading.Thread(target=lambda: self._run_data_update(force=True), daemon=True).start()

    def _on_manual_data_update(self):
        self.btn_data_update.config(state="disabled", fg="#555")
        self.lbl_data_date.config(text="다운로드 중...", foreground="#ffcc44")
        threading.Thread(
            target=lambda: self._run_data_update(force=True), daemon=True
        ).start()

    def _run_data_update(self, force: bool = False):
        def _status(msg: str):
            self.root.after(0, lambda m=msg: self.lbl_data_date.config(
                text=m, foreground="#ffcc44"))

        ok, msg = download_data(DATA_DIR, status_cb=_status, force=force)

        def _done():
            if ok:
                self._refresh_data_label()
                try:
                    self.item_parser._init_matcher()
                except Exception:
                    pass
            else:
                self.lbl_data_date.config(text="업데이트 실패", foreground=RED)
            self.btn_data_update.config(state="normal", fg=FG2)

        self.root.after(0, _done)

    def _refresh_data_label(self):
        last = get_last_updated(DATA_DIR)
        self.lbl_data_date.config(text=last, foreground="#888")

    # ────────────────────── 스캔 목록 ────────────────────────────
    def _add_scan_result(self, item_name: str, traderie_url: str,
                          min_price: str, max_price: str, options: dict = None,
                          api_url: str = "", options_editable: list = None,
                          url_ctx: dict = None, slot: str = ''):
        self._scan_counter += 1
        iid = f"scan_{self._scan_counter}"
        self._scan_urls[iid] = traderie_url
        self._scan_data[iid] = {
            "name": item_name,
            "url": traderie_url,
            "api_url": api_url,
            "min_price": min_price,
            "max_price": max_price,
            "options": options or {},
            "options_editable": options_editable or [],
            "url_ctx": url_ctx or {},
            "slot": slot,
        }
        self.tree.insert("", 0, iid=iid,
                         values=("☐", item_name, min_price, max_price, "추가", "↻"))

    def _clear_scan_list(self):
        if not self._scan_selected:
            return
        for iid in list(self._scan_selected):
            if self.tree.exists(iid):
                self.tree.delete(iid)
            self._scan_urls.pop(iid, None)
            self._scan_data.pop(iid, None)
        self._scan_selected.clear()

    def _on_tree_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            col = self.tree.identify_column(event.x)
            if col in ("#1", "#5", "#6"):  # 선택 / 즐겨찾기 / 재조회 컬럼
                return
            url = self._scan_urls.get(sel[0], "")
            if url:
                webbrowser.open(url)

    def _on_tree_click(self, event):
        col = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        if col == "#1":
            self._toggle_scan_select(row_id)
        elif col == "#5":
            self._add_to_favorites(row_id)
        elif col == "#6":
            self._requery_row(row_id)

    def _toggle_scan_select(self, iid: str):
        vals = list(self.tree.item(iid, "values"))
        if iid in self._scan_selected:
            self._scan_selected.discard(iid)
            vals[0] = "☐"
        else:
            self._scan_selected.add(iid)
            vals[0] = "☑"
        self.tree.item(iid, values=vals)

    def _requery_row(self, iid: str):
        data = self._scan_data.get(iid)
        api_url = data.get("api_url", "") if data else ""
        if not api_url:
            self._append_log("재조회 불가: API URL 없음", "warn")
            return

        vals = list(self.tree.item(iid, "values"))
        vals[5] = "..."
        self.tree.item(iid, values=vals)

        def _work():
            try:
                s_start, s_end, is_cur = self._get_season_dates()
                stats = fetch_price_stats(api_url, season_start=s_start, season_end=s_end, current_season=is_cur)
            except Exception:
                stats = {}
            self.root.after(0, lambda: self._apply_requery_result(iid, stats))

        threading.Thread(target=_work, daemon=True).start()

    def _apply_requery_result(self, iid: str, stats: dict):
        if not self.tree.exists(iid):
            return
        if stats.get("success") and stats.get("count", 0) > 0:
            min_price = stats.get("min_text", "N/A")
            max_price = stats.get("max_text", "N/A")
        else:
            min_price = "매물없음"
            max_price = "-"
        data = self._scan_data.get(iid)
        if data:
            data["min_price"] = min_price
            data["max_price"] = max_price
        vals = list(self.tree.item(iid, "values"))
        vals[2] = min_price
        vals[3] = max_price
        vals[5] = "↻"
        self.tree.item(iid, values=vals)
        if data and stats.get("success"):
            def _fav_cb(_n=data.get("name", ""), _u=data.get("url", ""),
                        _a=data.get("api_url", ""), _mn=min_price, _mx=max_price,
                        _oe=data.get("options_editable", []),
                        _ctx=data.get("url_ctx", {}), _sl=data.get("slot", "")):
                self._toggle_fav_from_search(_n, _u, _a, _mn, _mx, _oe,
                                             url_ctx=_ctx, slot=_sl)
            self.overlay.show(
                item_name=data.get("name", ""),
                traderie_url=data.get("url", ""),
                min_price=min_price,
                max_price=max_price,
                count=stats.get("count", 0),
                slot=data.get("slot", ""),
                on_fav=_fav_cb,
                is_fav=self._is_in_fav(data.get("url", "")),
            )

    _FREE_FAV_LIMIT = 3

    def _add_to_favorites(self, iid: str):
        data = self._scan_data.get(iid)
        if not data:
            return
        # 이미 즐겨찾기에 있으면 제거 (토글)
        for i, fav in enumerate(self._favorites):
            if fav.get("url") == data.get("url"):
                self._favorites.pop(i)
                self._save_favorites()
                self._refresh_fav_tree()
                self._append_log(f"즐겨찾기 제거: {data.get('name')}", "warn")
                vals = list(self.tree.item(iid, "values"))
                vals[4] = "추가"
                self.tree.item(iid, values=vals)
                self.fav_overlay.set_items(self._favorites)
                return
        # 무료 회원 즐겨찾기 개수 제한
        if not self._is_premium and len(self._favorites) >= self._FREE_FAV_LIMIT:
            self._append_log(
                f"즐겨찾기는 무료버전에서 최대 {self._FREE_FAV_LIMIT}개까지 추가 가능합니다.", "warn")
            return
        self._favorites.append(data)
        self._save_favorites()
        self._refresh_fav_tree()
        self._append_log(f"즐겨찾기 추가: {data.get('name')}", "success")
        vals = list(self.tree.item(iid, "values"))
        vals[4] = "제거"
        self.tree.item(iid, values=vals)
        self.fav_overlay.set_items(self._favorites)

    def _is_in_fav(self, url: str) -> bool:
        return any(f.get("url") == url for f in self._favorites)

    def _toggle_fav_from_search(self, name: str, url: str, api_url: str,
                                 min_price: str, max_price: str,
                                 options_editable: list,
                                 url_ctx: dict = None, slot: str = '') -> bool:
        """시세찾기/시세확인 즐겨찾기 토글. True=추가됨, False=제거됨"""
        for i, fav in enumerate(self._favorites):
            if fav.get("url") == url:
                self._favorites.pop(i)
                self._save_favorites()
                self._refresh_fav_tree()
                self.fav_overlay.set_items(self._favorites)
                return False
        # 무료 회원 즐겨찾기 개수 제한
        if not self._is_premium and len(self._favorites) >= self._FREE_FAV_LIMIT:
            self._append_log(
                f"즐겨찾기는 무료버전에서 최대 {self._FREE_FAV_LIMIT}개까지 추가 가능합니다.", "warn")
            return False
        self._favorites.append({
            "name":             name,
            "url":              url,
            "api_url":          api_url,
            "min_price":        min_price,
            "max_price":        max_price,
            "options":          {},
            "options_editable": options_editable,
            "url_ctx":          url_ctx or {},
            "slot":             slot,
        })
        self._save_favorites()
        self._refresh_fav_tree()
        self.fav_overlay.set_items(self._favorites)
        return True

    def _save_favorites(self):
        self.config["favorites"] = self._favorites
        save_config(self.config)

    def _refresh_fav_tree(self):
        sel = self.fav_tree.selection()
        sel_iid = sel[0] if sel else None
        self.fav_tree.delete(*self.fav_tree.get_children())
        for i, fav in enumerate(self._favorites):
            alias = fav.get("alias", "").strip()
            display_name = alias if alias else fav.get("name", "")
            self.fav_tree.insert("", "end", iid=f"fav_{i}",
                                  values=(display_name,
                                          fav.get("min_price", ""),
                                          fav.get("max_price", ""),
                                          "조회"))
        if sel_iid and self.fav_tree.exists(sel_iid):
            self.fav_tree.selection_set(sel_iid)

    def _on_fav_click(self, event):
        col = self.fav_tree.identify_column(event.x)
        iid = self.fav_tree.identify_row(event.y)
        if not iid:
            return
        if col == "#4":   # "query" 컬럼 (#1=name, #2=min, #3=max, #4=query)
            self._fav_query_row(iid)

    def _fav_query_row(self, iid: str):
        """즐겨찾기 목록 '조회' 클릭 — 해당 행 수동 시세 조회"""
        idx = int(iid.replace("fav_", ""))
        if not (0 <= idx < len(self._favorites)):
            return
        fav = self._favorites[idx]
        api_url = fav.get("api_url", "")
        if not api_url:
            self.lbl_fav_query_result.config(text="API URL 없음")
            return

        # 해당 행 "조회" → "..."
        vals = list(self.fav_tree.item(iid, "values"))
        vals[3] = "..."
        self.fav_tree.item(iid, values=vals)
        self.lbl_fav_query_result.config(text="")

        def _fetch():
            try:
                s_start, s_end, is_cur = self._get_season_dates()
                stats = fetch_price_stats(api_url, season_start=s_start, season_end=s_end, current_season=is_cur)
                if stats.get("success") and stats.get("count", 0) > 0:
                    fav["min_price"] = stats.get("min_text", "N/A")
                    fav["max_price"] = stats.get("max_text", "N/A")
                    result = f"최저가 {fav['min_price']}  최고가 {fav['max_price']}"
                    self._save_favorites()
                    self.root.after(0, self._refresh_fav_tree)
                    def _fav_toggle(_n=fav.get("name",""), _u=fav.get("url",""),
                                    _a=fav.get("api_url",""), _mn=fav["min_price"],
                                    _mx=fav["max_price"],
                                    _oe=fav.get("options_editable",[])):
                        self._toggle_fav_from_search(_n, _u, _a, _mn, _mx, _oe)
                    self.root.after(0, lambda _ft=_fav_toggle, _u=fav.get("url",""): self.overlay.show(
                        item_name=fav.get("name", ""),
                        traderie_url=fav.get("url", ""),
                        min_price=fav["min_price"],
                        max_price=fav["max_price"],
                        count=stats.get("count", 0),
                        slot=fav.get("slot", ""),
                        on_fav=_ft,
                        is_fav=self._is_in_fav(_u),
                    ))
                else:
                    result = "매물 없음"
                    def _restore():
                        v = list(self.fav_tree.item(iid, "values"))
                        v[3] = "조회"
                        self.fav_tree.item(iid, values=v)
                    self.root.after(0, _restore)
                self.root.after(0, lambda r=result: self.lbl_fav_query_result.config(text=r))
            except Exception:
                self.root.after(0, lambda: self.lbl_fav_query_result.config(text="조회 실패"))
                def _restore_err():
                    if self.fav_tree.exists(iid):
                        v = list(self.fav_tree.item(iid, "values"))
                        v[3] = "조회"
                        self.fav_tree.item(iid, values=v)
                self.root.after(0, _restore_err)

        threading.Thread(target=_fetch, daemon=True).start()

    def _clear_favorites(self):
        sel = self.fav_tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            idx = int(iid.replace("fav_", ""))
        except ValueError:
            return
        if 0 <= idx < len(self._favorites):
            self._favorites.pop(idx)
            self._save_favorites()
            self._refresh_fav_tree()
            self.fav_overlay.set_items(self._favorites)
            self._clear_fav_detail()

    def _on_fav_select(self, event=None):
        sel = self.fav_tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = int(iid.replace("fav_", ""))
        if 0 <= idx < len(self._favorites):
            fav = self._favorites[idx]
            self._fav_alias_var.set(fav.get("alias", ""))
            self._show_fav_detail(fav)

    def _save_fav_alias(self):
        """선택된 즐겨찾기 항목에 별칭을 저장"""
        sel = self.fav_tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = int(iid.replace("fav_", ""))
        if not (0 <= idx < len(self._favorites)):
            return
        fav = self._favorites[idx]
        alias = self._fav_alias_var.get().strip()
        fav["alias"] = alias
        self._save_favorites()
        self._refresh_fav_tree()
        self.fav_overlay.set_items(self._favorites)
        display = alias if alias else fav.get("name", "")
        self._append_log(f"별칭 저장: {fav.get('name','')} → '{display}'", "success")

    def _show_fav_detail(self, fav: dict):
        self._clear_fav_detail()
        self._fav_current = fav
        options_editable = fav.get("options_editable")
        if options_editable:
            self._show_fav_detail_structured(fav, options_editable)
            return

        # 구조화 메타데이터가 없는 구버전 데이터 / magic·rare 폴백 — 단순 텍스트 편집
        options = fav.get("options", {})
        if not options:
            ttk.Label(self.fav_detail_frame, text="옵션 정보 없음",
                      foreground="#666", font=("맑은 고딕", 10)).grid(
                          row=0, column=0, columnspan=2, sticky="w", pady=4)
            return
        self._fav_detail_vars: dict[str, tk.StringVar] = {}
        for i, (k, v) in enumerate(options.items()):
            ttk.Label(self.fav_detail_frame, text=f"{k}",
                      foreground=FG2, font=("맑은 고딕", 10)).grid(
                          row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            var = tk.StringVar(value=str(v))
            self._fav_detail_vars[k] = var
            entry = ttk.Entry(self.fav_detail_frame, textvariable=var, width=14)
            entry.grid(row=i, column=1, sticky="w", pady=2)
            entry.bind("<FocusOut>", lambda e, fv=fav, key=k: self._on_fav_option_change(fv, key))
            entry.bind("<Return>", lambda e, fv=fav, key=k: self._on_fav_option_change(fv, key))

    def _show_fav_detail_structured(self, fav: dict, options_editable: list):
        """
        구조화된 옵션 편집 UI.
        column 0: 포함 체크박스 / column 1: 옵션 이름 / column 2: 값 위젯
        - is_range: Min/Max Entry (수정 가능)
        - selectable: 고정값 레이블 (포함 여부만 체크박스로 제어)
        - 고정값(min==max): 단일 Entry (수정 가능)
        """
        _ENTRY_BG = "#3a3a3a"
        _ENTRY_FG = "#ffffff"
        self._fav_option_widgets: dict = {}
        for i, opt in enumerate(options_editable):
            name = opt.get("name", "")
            db_min = opt.get("db_min")
            db_max = opt.get("db_max")
            selectable = opt.get("selectable", False)
            is_range = db_min is not None and db_max is not None and db_min != db_max

            # column 0: 포함/제외 체크박스
            default_inc = opt.get("included", False if selectable else True)
            inc_var = tk.BooleanVar(value=default_inc)
            inc_cb = mk_check(
                self.fav_detail_frame, variable=inc_var,
                command=lambda fv=fav, o=opt, v=inc_var: self._on_fav_option_include(fv, o, v))
            inc_cb.grid(row=i, column=0, sticky="w", pady=2)

            # column 1: 옵션 이름
            ttk.Label(self.fav_detail_frame, text=name,
                      foreground=FG2, font=("맑은 고딕", 10)).grid(
                          row=i, column=1, sticky="w", padx=(0, 8), pady=2)

            # column 2: 값 위젯
            if selectable:
                ttk.Label(self.fav_detail_frame,
                          text=f"값: {opt.get('min', 0)}",
                          foreground=FG, font=("맑은 고딕", 10)).grid(
                              row=i, column=2, sticky="w", pady=2)
                self._fav_option_widgets[id(opt)] = inc_var
            elif is_range:
                frame = tk.Frame(self.fav_detail_frame, bg=BG)
                frame.grid(row=i, column=2, sticky="w", pady=2)
                min_var = tk.StringVar(value=str(opt.get("min", db_min)))
                max_var = tk.StringVar(value=str(opt.get("max", db_max)))
                tk.Label(frame, text="Min", bg=BG, fg=FG2,
                         font=("맑은 고딕", 9)).pack(side="left")
                min_entry = tk.Entry(frame, textvariable=min_var, width=6,
                                     bg=_ENTRY_BG, fg=_ENTRY_FG,
                                     insertbackground=_ENTRY_FG, relief="flat")
                min_entry.pack(side="left", padx=(2, 8))
                tk.Label(frame, text="Max", bg=BG, fg=FG2,
                         font=("맑은 고딕", 9)).pack(side="left")
                max_entry = tk.Entry(frame, textvariable=max_var, width=6,
                                     bg=_ENTRY_BG, fg=_ENTRY_FG,
                                     insertbackground=_ENTRY_FG, relief="flat")
                max_entry.pack(side="left", padx=(2, 0))
                tk.Label(frame, text=f"(DB {db_min}~{db_max})", bg=BG,
                         fg="#888888", font=("맑은 고딕", 8)).pack(side="left", padx=(6, 0))

                handler = lambda e, fv=fav, o=opt, mnv=min_var, mxv=max_var, dmin=db_min, dmax=db_max: \
                    self._on_fav_option_range_change(fv, o, mnv, mxv, dmin, dmax)
                min_entry.bind("<FocusOut>", handler)
                min_entry.bind("<Return>", handler)
                max_entry.bind("<FocusOut>", handler)
                max_entry.bind("<Return>", handler)
                self._fav_option_widgets[id(opt)] = (inc_var, min_var, max_var)
            else:
                val_var = tk.StringVar(value=str(opt.get("min", 0)))
                val_entry = tk.Entry(self.fav_detail_frame, textvariable=val_var, width=8,
                                     bg=_ENTRY_BG, fg=_ENTRY_FG,
                                     insertbackground=_ENTRY_FG, relief="flat",
                                     font=("맑은 고딕", 10))
                val_entry.grid(row=i, column=2, sticky="w", pady=2)
                handler_fixed = lambda e, fv=fav, o=opt, vv=val_var: \
                    self._on_fav_option_fixed_change(fv, o, vv)
                val_entry.bind("<FocusOut>", handler_fixed)
                val_entry.bind("<Return>", handler_fixed)
                self._fav_option_widgets[id(opt)] = (inc_var, val_var)

    def _on_fav_option_include(self, fav: dict, opt: dict, var: "tk.BooleanVar"):
        opt["included"] = var.get()

        # selectable 그룹: 하나 선택 시 나머지 자동 해제 (라디오버튼 동작)
        if opt.get("selectable") and var.get():
            for other in fav.get("options_editable", []):
                if other is not opt and other.get("selectable") and other.get("included"):
                    other["included"] = False
                    widget = self._fav_option_widgets.get(id(other))
                    if isinstance(widget, tk.BooleanVar):
                        widget.set(False)

        self._rebuild_fav_url(fav)
        self._append_log(
            f"옵션 {'포함' if opt['included'] else '제외'}: {fav.get('name', '')} - {opt.get('name', '')}",
            "success")

    def _on_fav_option_fixed_change(self, fav: dict, opt: dict, val_var: "tk.StringVar"):
        try:
            new_val = int(val_var.get())
        except ValueError:
            val_var.set(str(opt.get("min", 0)))
            return
        if opt.get("min") == new_val:
            return
        opt["min"] = new_val
        opt["max"] = new_val
        opt["included"] = True
        self._rebuild_fav_url(fav)
        self._append_log(
            f"옵션 수정: {fav.get('name', '')} - {opt.get('name', '')} = {new_val}", "success")

    def _on_fav_option_range_change(self, fav: dict, opt: dict,
                                     min_var: "tk.StringVar", max_var: "tk.StringVar",
                                     db_min: int, db_max: int):
        try:
            new_min = int(min_var.get())
            new_max = int(max_var.get())
        except (ValueError, TypeError):
            min_var.set(str(opt.get("min", db_min or 0)))
            max_var.set(str(opt.get("max", db_max or 0)))
            return
        if db_min is not None and db_max is not None:
            new_min = max(db_min, min(new_min, db_max))
            new_max = max(db_min, min(new_max, db_max))
        else:
            new_min = max(0, new_min)
            new_max = max(0, new_max)
        if new_min > new_max:
            new_min, new_max = new_max, new_min
        min_var.set(str(new_min))
        max_var.set(str(new_max))
        if opt.get("min") == new_min and opt.get("max") == new_max:
            return
        opt["min"] = new_min
        opt["max"] = new_max
        opt["included"] = True
        self._rebuild_fav_url(fav)
        self._append_log(
            f"옵션 수정: {fav.get('name', '')} - {opt.get('name', '')} = {new_min}~{new_max}", "success")

    def _rebuild_fav_url(self, fav: dict):
        """옵션 변경 후 즐겨찾기의 traderie_url/api_url 재생성 + 표시 갱신 + 저장"""
        url_ctx = fav.get("url_ctx")
        options_editable = fav.get("options_editable")
        if not url_ctx or options_editable is None:
            self._save_favorites()
            return
        result = self.item_parser.rebuild_url(url_ctx, options_editable)
        fav["url"] = result["traderie_url"]
        fav["api_url"] = result["api_url"]
        fav["options"] = self.item_parser._build_options_display(
            [o for o in options_editable if o.get("included", True)])
        self._save_favorites()

    def _on_fav_option_change(self, fav: dict, key: str):
        var = self._fav_detail_vars.get(key)
        if var is None:
            return
        new_val = var.get()
        options = fav.get("options")
        if options is None or options.get(key) == new_val:
            return
        options[key] = new_val
        self._save_favorites()
        self._append_log(f"옵션 수정: {fav.get('name', '')} - {key} = {new_val}", "success")

    def _clear_fav_detail(self):
        for w in self.fav_detail_frame.winfo_children():
            w.destroy()
        self._fav_detail_vars = {}
        self._fav_option_widgets = {}
        self._fav_current = None
        if hasattr(self, "_fav_alias_var"):
            self._fav_alias_var.set("")

    def _fav_select_all(self):
        """옵션 상세 전체 선택 (모든 inc_var → True)"""
        fav = getattr(self, "_fav_current", None)
        if not fav:
            return
        for widget_data in self._fav_option_widgets.values():
            inc_var = widget_data if isinstance(widget_data, tk.BooleanVar) else widget_data[0]
            inc_var.set(True)
        opts = fav.get("options_editable", [])
        for o in opts:
            o["included"] = True
        self._rebuild_fav_url(fav)

    def _fav_select_none(self):
        """옵션 상세 전체 해제 (모든 inc_var → False)"""
        fav = getattr(self, "_fav_current", None)
        if not fav:
            return
        for widget_data in self._fav_option_widgets.values():
            inc_var = widget_data if isinstance(widget_data, tk.BooleanVar) else widget_data[0]
            inc_var.set(False)
        opts = fav.get("options_editable", [])
        for o in opts:
            o["included"] = False
        self._rebuild_fav_url(fav)

    def _on_fav_double_click(self, event):
        sel = self.fav_tree.selection()
        if sel:
            iid = sel[0]
            idx = int(iid.replace("fav_", ""))
            if 0 <= idx < len(self._favorites):
                url = self._favorites[idx].get("url", "")
                if url:
                    webbrowser.open(url)

    def _auto_verify_premium(self):
        """앱 시작 시 저장된 유료키로 재인증 (매월 변경되는 GitHub 해시값과 비교)"""
        key = self.config.get("premium_key", "")
        if key:
            threading.Thread(
                target=lambda: self._run_premium_verify(key), daemon=True
            ).start()

    # 관리자 모드 키 해시 (SHA-256, 평문 키는 소스에 존재하지 않음)
    _ADMIN_KEY_HASH = "a9d7c217b6636d6a5f5c1b901a3f73e8f054ceab70fe59fd4616c3ba00251cd2"

    def _on_verify_premium_key(self):
        import hashlib
        key = self.premium_key_var.get().strip()
        if not key:
            return

        # 입력값을 해시로 변환 후 저장된 해시와 비교 (평문 비교 없음)
        if hashlib.sha256(key.encode()).hexdigest() == self._ADMIN_KEY_HASH:
            self._activate_admin_mode()
            return

        self._verify_premium_btn.config(state="disabled")
        self.lbl_premium_status.config(text="인증 확인 중...", foreground="#ffcc44")
        threading.Thread(
            target=lambda: self._run_premium_verify(key), daemon=True
        ).start()

    def _activate_admin_mode(self):
        """관리자 모드 활성화: 유료 기능 + 미리보기 탭 활성"""
        self._is_admin = True
        self._is_premium = True
        self.config["is_premium"] = True
        # 관리자 키는 config에 저장하지 않음
        save_config(self.config)
        self.overlay.set_multi_mode(True)
        self._update_premium_status_label()
        self._update_fav_tab_state()
        self._update_ocr_mode_ui()
        self._update_preview_tab_visibility()
        self._append_log("관리자 모드 활성화됨 (미리보기 탭 사용 가능)", "success")

    def _update_preview_tab_visibility(self):
        """관리자 모드일 때만 미리보기 탭을 notebook에 표시"""
        tab_texts = [self.notebook.tab(i, "text") for i in range(self.notebook.index("end"))]
        preview_label = "  미리보기  "
        if self._is_admin:
            if preview_label not in tab_texts:
                self.notebook.add(self._tab4, text=preview_label)
        else:
            if preview_label in tab_texts:
                idx = tab_texts.index(preview_label)
                self.notebook.forget(idx)

    def _run_premium_verify(self, key: str):
        ok, msg = verify_key(key)

        def _done():
            self._verify_premium_btn.config(state="normal")
            self._is_premium = ok
            self.config["is_premium"] = ok
            self.config["premium_key"] = key
            save_config(self.config)
            self.overlay.set_multi_mode(ok)
            self._update_premium_status_label()
            self._update_fav_tab_state()
            self._update_ocr_mode_ui()
            self._update_preview_tab_visibility()
            self._append_log(
                f"유료키 {'인증 성공' if ok else f'인증 실패: {msg}'}",
                "success" if ok else "warn")
            if ok:
                threading.Thread(target=lambda: self._run_data_update(force=True), daemon=True).start()

        self.root.after(0, _done)

    def _update_premium_status_label(self):
        if self._is_admin:
            self.lbl_premium_status.config(
                text="[관리자] 모든 기능 활성화됨", foreground=GOLD)
        elif self._is_premium:
            self.lbl_premium_status.config(
                text="✓ 유료버전 인증됨", foreground=GREEN)
        else:
            self.lbl_premium_status.config(
                text=f"미인증 (무료버전 - 실행당 {self._FREE_DAILY_LIMIT}회 제한)", foreground="#888")

    def _on_fav_refresh_change(self, event=None):
        try:
            val = int(self.fav_refresh_var.get())
            val = max(5, min(60, (val // 5) * 5))  # 5단위로 반올림
        except (ValueError, tk.TclError):
            val = 5
        self.fav_refresh_var.set(val)
        self.config["fav_refresh_min"] = val
        save_config(self.config)

    def _on_fav_overlay_interval_change(self, event=None):
        try:
            val = int(self.fav_overlay_interval_var.get())
            val = max(1, min(60, val))
        except (ValueError, tk.TclError):
            val = 5
        self.fav_overlay_interval_var.set(val)
        self.config["fav_overlay_interval_min"] = val
        save_config(self.config)

    def _start_fav_overlay_cycle(self):
        """N분마다 즐겨찾기 오버레이를 한 차례(전체 1회전) 보여주고 숨기는 사이클"""
        if not self._is_premium or not self._favorites:
            return
        self.fav_overlay.set_items(self._favorites)
        self.fav_overlay.start(max_cycles=1, on_cycle_done=self._end_fav_overlay_show)

        interval_min = self.config.get("fav_overlay_interval_min", 5)
        interval_ms = max(interval_min, 1) * 60 * 1000
        self._fav_overlay_cycle_id = self.root.after(interval_ms, self._start_fav_overlay_cycle)

    def _end_fav_overlay_show(self):
        self._fav_overlay_show_id = None
        # overlay가 max_cycles 완료 시 스스로 stop() 호출하므로 여기선 별도 처리 없음

    def _stop_fav_overlay_cycle(self):
        for attr in ("_fav_overlay_cycle_id", "_fav_overlay_show_id"):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _start_fav_price_refresh(self):
        if not self._favorites:
            return
        interval_ms = self.config.get("fav_refresh_min", 5) * 60 * 1000

        def _refresh():
            # 무료회원: 즐겨찾기 갱신 1회를 스캔 횟수로 차감
            if not self._is_premium:
                used = self._free_scan_count + len(self._favorites)
                if used > self._FREE_DAILY_LIMIT:
                    self.root.after(0, lambda: self._append_log(
                        "즐겨찾기 갱신 생략: 무료 횟수 한도 초과", "warn"))
                    return
                self._free_scan_count += len(self._favorites)
            for fav in self._favorites:
                api_url = fav.get("api_url", "")
                if not api_url:
                    continue
                try:
                    s_start, s_end = self._get_season_dates()
                    stats = fetch_price_stats(api_url, season_start=s_start, season_end=s_end)
                    if stats.get("success") and stats.get("count", 0) > 0:
                        fav["min_price"] = stats.get("min_text", "N/A")
                        fav["max_price"] = stats.get("max_text", "N/A")
                except Exception:
                    pass
            self.root.after(0, self._refresh_fav_tree)
            self.root.after(0, lambda: self._append_log("즐겨찾기 시세 갱신 완료", "info"))

        threading.Thread(target=_refresh, daemon=True).start()
        self._fav_refresh_after_id = self.root.after(interval_ms, self._start_fav_price_refresh)
        self._fav_countdown_secs = self.config.get("fav_refresh_min", 5) * 60
        self._tick_fav_countdown()

    def _tick_fav_countdown(self):
        self._fav_countdown_id = None
        if not self.is_tracking:
            self.lbl_fav_countdown.config(text="")
            return
        secs = self._fav_countdown_secs
        if secs <= 0:
            self.lbl_fav_countdown.config(text="갱신 중...")
        else:
            m, s = divmod(secs, 60)
            self.lbl_fav_countdown.config(text=f"다음 갱신: {m:02d}:{s:02d}")
            self._fav_countdown_secs -= 1
            self._fav_countdown_id = self.root.after(1000, self._tick_fav_countdown)

    def _update_fav_tab_state(self):
        # 즐겨찾기 탭 자체는 무료/유료 모두 사용 가능 — 잠금 프레임 항상 숨김
        self._fav_lock_frame.place_forget()
        self.fav_tree.column("name", width=70)
        # 스캔 목록 즐겨찾기 컬럼은 무료/유료 모두 표시
        self.tree.column("fav", width=80)
        # 무료버전 안내 배너: 무료일 때만 표시
        if self._is_premium:
            self._fav_free_banner.grid_remove()
        else:
            self._fav_free_banner.grid()
        # 즐겨찾기 자동 갱신: 무료/유료 모두 사용 가능 (무료는 횟수 한도 포함)
        self.fav_refresh_spin.config(state="normal")
        # 오버레이 표시 주기 / 즐겨찾기샘플보기: 유료 전용
        self.fav_overlay_interval_spin.config(state="normal" if self._is_premium else "disabled")
        self.btn_fav_sample.config(state="normal" if self._is_premium else "disabled")

    # ────────────────────── 핵심 처리 흐름 ───────────────────────
    _FREE_DAILY_LIMIT = 20

    def _on_trigger(self):
        """핫키 → 캡처 → 파이프라인 (무료: 단일처리, 유료: 큐 방식)"""
        # ── 무료 버전: 기존 단일 처리 ──────────────────────────────
        if not self._is_premium:
            if self.is_processing:
                return
            if self._free_scan_count >= self._FREE_DAILY_LIMIT:
                self.root.after(0, lambda: self._set_status(
                    f"무료버전 감지 횟수({self._FREE_DAILY_LIMIT}회/실행) 초과"))
                self.root.after(0, lambda: self._append_log(
                    f"무료버전 감지 횟수({self._FREE_DAILY_LIMIT}회/실행)를 초과했습니다. 유료키를 등록하세요.", "warn"))
                return
            if self.fav_overlay._running:
                self.fav_overlay.pause()
                self._fav_overlay_paused = True
            self.is_processing = True
            self.root.after(0, lambda: self._set_status("캡처 중..."))
            try:
                img, region, mouse_pos = capture_around_mouse(self._selected_proc)
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda m=err_msg: self._set_status(f"캡처 오류: {m}"))
                self.root.after(0, lambda m=err_msg: self._append_log(f"캡처 오류: {m}", "error"))
                self.is_processing = False
                return
            self._free_scan_count += 1
            self._run_pipeline_thread(img, region, mouse_pos, from_file=False)
            return

        # ── 유료 버전: 연속 캡처 큐 ───────────────────────────────
        if self._capture_queue.full():
            self.root.after(0, lambda: self._set_status("캡처 대기열이 꽉 찼습니다 (최대 5개)"))
            return

        try:
            img, region, mouse_pos = capture_around_mouse(self._selected_proc)
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda m=err_msg: self._set_status(f"캡처 오류: {m}"))
            self.root.after(0, lambda m=err_msg: self._append_log(f"캡처 오류: {m}", "error"))
            return

        self._capture_queue.put((img, region, mouse_pos, False))
        q_size = self._capture_queue.qsize()
        self.root.after(0, lambda s=q_size: self._set_status(f"대기열 [{s}] 처리 중..."))

        if not self._queue_worker_running:
            self._queue_worker_running = True
            if self.fav_overlay._running:
                self.root.after(0, self.fav_overlay.pause)
                self._fav_overlay_paused = True
            threading.Thread(target=self._queue_worker, daemon=True).start()

    def _queue_worker(self):
        """유료 전용: 캡처 큐를 순차 처리하는 워커 스레드"""
        try:
            while True:
                try:
                    img, region, mouse_pos, from_file = self._capture_queue.get(timeout=2.0)
                except queue.Empty:
                    break
                self._run_pipeline_thread(img, region, mouse_pos, from_file=from_file)
                self._capture_queue.task_done()
        finally:
            self._queue_worker_running = False
            self.root.after(0, self._resume_fav)

    def _resume_fav(self):
        """즐겨찾기 오버레이 재개"""
        if self._is_premium and self._fav_overlay_paused:
            self.fav_overlay.resume()
            self._fav_overlay_paused = False

    def _on_load_image(self):
        """이미지 파일 로드 → 파이프라인 (게임 없이 개발/테스트용).
        유료: 여러 파일 선택 가능, 큐 방식 처리.
        무료: 단일 파일, 처리 중이면 무시."""
        if not self._is_premium and self.is_processing:
            return
        paths = filedialog.askopenfilenames(
            title="게임 스크린샷 선택 (여러 장 가능)",
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.bmp"), ("모든 파일", "*.*")],
        )
        if not paths:
            return

        def _load_one(path: str):
            """이미지 파일 → (img, region, mouse_pos) 또는 None"""
            try:
                img = PILImage.open(path).convert("RGB")
            except Exception as e:
                self._append_log(f"이미지 로드 실패: {e}", "error")
                return None
            w, h = img.size
            region = (0, 0, w, h)
            cursor = find_cursor_in_image(img)
            if cursor:
                mouse_pos = cursor
                self._append_log(f"[개발] {Path(path).name}: 흰색 원 → mouse_pos={mouse_pos}", "info")
            else:
                mouse_pos = (w // 2, h // 2)
                self._append_log(f"[개발] {Path(path).name}: 원 미감지 → 중앙 사용", "warn")
            return img, region, mouse_pos

        if self._is_premium:
            # 큐 방식: 로드한 이미지를 순서대로 큐에 적재
            loaded = []
            for p in paths:
                self._append_log(f"[개발] 이미지 로드: {Path(p).name}", "info")
                result = _load_one(p)
                if result:
                    loaded.append(result)

            if not loaded:
                return

            for item in loaded:
                if not self._capture_queue.full():
                    self._capture_queue.put((*item, True))  # from_file=True
                else:
                    self._append_log("[개발] 캡처 대기열 꽉 참 — 일부 이미지 스킵", "warn")
                    break

            if not self._queue_worker_running:
                self._queue_worker_running = True
                threading.Thread(target=self._queue_worker, daemon=True).start()
        else:
            # 무료: 첫 번째 파일만 처리
            path = paths[0]
            self._append_log(f"[개발] 이미지 로드: {Path(path).name}", "info")
            result = _load_one(path)
            if not result:
                return
            img, region, mouse_pos = result
            self.is_processing = True
            threading.Thread(
                target=self._run_pipeline_thread,
                args=(img, region, mouse_pos, True),
                daemon=True,
            ).start()

    def _run_paddle_crop_ocr(self, ocr_img) -> dict:
        """크롭된 툴팁 이미지를 PaddleOCR(2x)로 분석 → ai_bridge.run_ocr()과 동일한 반환 형식"""
        tmp_crop_path = save_temp_image(ocr_img)
        try:
            crop_ocr = self.paddle_bridge.run_ocr(tmp_crop_path, scale=2.0)
        finally:
            try:
                os.unlink(tmp_crop_path)
            except Exception:
                pass
        lines = crop_ocr.get("lines", [])
        result = {
            "success": bool(lines),
            "lines": lines,
            "rawText": "\n".join(lines),
            "linesWithBbox": crop_ocr.get("linesWithBbox", []),
            "provider": "paddle",
        }
        if not lines:
            result["error"] = "툴팁 내 텍스트 없음"
        return result

    def _run_pipeline_thread(self, img, region, mouse_pos, from_file: bool = False):
        """OCR → 툴팁감지 → 파싱 → 가격 → 결과 (공통 파이프라인)"""
        try:
            img_offset = (region[0], region[1])

            try:
                import tempfile as _tf
                _raw_path = str(Path(_tf.gettempdir()) / "d2r_raw_capture.png")
                img.save(_raw_path, "PNG")
                self.root.after(0, lambda p=_raw_path: self._append_log(
                    f"[DBG] 원본캡처: {p} 크기={img.size} mouse={mouse_pos} offset={img_offset}", "info"))
            except Exception:
                pass

            ocr_mode = self.config.get("ocr_mode", "paddle")

            # 툴팁 감지는 항상 PaddleOCR bbox 기반 — AI/Paddle 모드 공통
            full_lines_with_bbox = []
            self.root.after(0, lambda: self._set_status("PaddleOCR 전체 화면 분석 중..."))
            tmp_full_path = save_temp_image(img)
            try:
                full_ocr = self.paddle_bridge.run_ocr(tmp_full_path)
                full_lines_with_bbox = full_ocr.get('linesWithBbox', [])
                _all_lines = full_ocr.get('lines', [])
                self.root.after(0, lambda n=len(full_lines_with_bbox): self._append_log(
                    f"[DBG] 전체화면 OCR: {n}개 bbox", "info"))
                if ocr_mode == "paddle":
                    for _ln in _all_lines:
                        self.root.after(0, lambda t=_ln: self._append_log(f"  [OCR] {t}", "info"))
            except Exception as _fe:
                self.root.after(0, lambda e=str(_fe): self._append_log(
                    f"[DBG] 전체화면 OCR 오류: {e}", "warn"))
            finally:
                try:
                    os.unlink(tmp_full_path)
                except Exception:
                    pass

            self.root.after(0, lambda: self._set_status("툴팁 감지 중..."))
            tooltip_img, crop_rect, dbg_msg = find_tooltip(
                img, mouse_pos, img_offset, full_lines_with_bbox or None)
            self.root.after(0, lambda m=dbg_msg: self._append_log(f"[DBG] {m}", "info"))

            if not tooltip_img:
                if from_file:
                    # 이미 툴팁만 잘라낸 이미지일 경우 전체를 OCR 대상으로 사용
                    self.root.after(0, lambda: self._append_log(
                        "툴팁 미감지 → 전체 이미지로 OCR 진행 (이미지 로드 모드)", "warn"))
                    tooltip_img = img
                    crop_rect = (0, 0, img.size[0], img.size[1])
                else:
                    self.root.after(0, lambda i=img: self._update_preview(i, ["[툴팁 미감지]"]))
                    self.root.after(0, lambda: self._set_status(
                        "툴팁 미감지 — 아이템 위에 마우스를 올린 후 다시 시도하세요"))
                    self.root.after(0, lambda: self._append_log("툴팁 미감지 (시스템 메시지 없음)", "warn"))
                    return

            ocr_img = tooltip_img
            self.root.after(0, lambda i=ocr_img: self._update_preview(i))

            try:
                from config import _sanitize_log_path
                _base = _sanitize_log_path(self.config.get("log_path", LOG_DEFAULT_ROOT))
                if not Path(_base).exists():
                    _base = LOG_DEFAULT_ROOT
                cap_dir = Path(_base) / Path(CAPTURES_SUBDIR)
                cap_dir.mkdir(parents=True, exist_ok=True)
                cap_path = str(cap_dir / CAPTURES_FILENAME)
                ocr_img.save(cap_path, "PNG")
                self.root.after(0, lambda p=cap_path: self._append_log(
                    f"캡처 저장: {p}", "info"))
            except Exception as cap_err:
                import tempfile as _tf
                cap_path = str(Path(_tf.gettempdir()) / "d2r_cap_latest.png")
                try:
                    ocr_img.save(cap_path, "PNG")
                except Exception:
                    cap_path = None
                self.root.after(0, lambda e=str(cap_err): self._append_log(
                    f"캡처 저장 경로 오류({e}) → 경로 설정을 확인하세요", "warn"))

            if ocr_mode == "paddle":
                self.root.after(0, lambda: self._set_status("PaddleOCR 툴팁 분석 중 (2x)..."))
                ocr_result = self._run_paddle_crop_ocr(ocr_img)
            else:
                self.root.after(0, lambda: self._set_status(
                    f"AI 분석 중 ({self.ai_bridge.current_provider_name})..."))
                tmp_path = save_temp_image(ocr_img)
                try:
                    ocr_result = self.ai_bridge.run_ocr(tmp_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

                # 설정된 AI가 전부 할당량 소진(provider='none') → PaddleOCR로 자동 폴백
                if not ocr_result.get("success") and ocr_result.get("provider") == "none" \
                        and self.paddle_bridge.is_ready():
                    self.root.after(0, lambda: self._append_log(
                        "AI 할당량 모두 소진 → PaddleOCR(로컬)로 전환", "warn"))
                    self.root.after(0, lambda: self._set_status("PaddleOCR 툴팁 분석 중 (2x)..."))
                    ocr_result = self._run_paddle_crop_ocr(ocr_img)

            if not ocr_result.get("success"):
                err = ocr_result.get("error", "OCR 실패")
                self.root.after(0, lambda i=ocr_img, e=err: self._update_preview(i, [f"[OCR 오류] {e}"]))
                self.root.after(0, lambda e=err: self._set_status(f"오류: {e}"))
                self.root.after(0, lambda e=err: self._append_log(e, "error"))
                self.root.after(0, lambda e=err: self.overlay.show_error(e))
                return

            lines = ocr_result.get("lines", [])
            if not lines:
                self.root.after(0, lambda i=ocr_img: self._update_preview(i, ["[텍스트 없음]"]))
                self.root.after(0, lambda: self._set_status("텍스트 인식 실패"))
                self.root.after(0, lambda: self._append_log("텍스트 인식 실패", "warn"))
                self.root.after(0, lambda: self.overlay.show_error("아이템 텍스트를 인식하지 못했습니다"))
                return

            rarity = detect_rarity_from_image(ocr_img, ocr_lines=lines) or "base"
            ai_item_name = None
            options = []

            provider_used = ocr_result.get("provider", "paddle")
            if provider_used == "paddle":
                provider_label = "PaddleOCR"
            else:
                provider_label = PROVIDER_NAMES.get(provider_used, provider_used)

            def _log_ocr(pv=provider_label, lns=lines, rv=rarity):
                self._append_log(f"── OCR 결과 [{pv}] ──────────────", "info")
                self._append_log(f"  등급(HSV) : {rv}", "info")
                self._append_log("  추출 텍스트 :", "info")
                for ln in lns:
                    self._append_log(f"    {ln}", "info")
                self._append_log("─────────────────────────────────", "info")

            self.root.after(0, _log_ocr)

            self.root.after(0, lambda: self._set_status("아이템 분석 중..."))
            parse_result = self.item_parser.parse(lines, rarity, self.config,
                                                   ai_options=options, ai_item_name=ai_item_name)
            item_name = parse_result.get("item_name", ai_item_name or "알 수 없음")

            self.root.after(0, lambda i=ocr_img, ls=lines, nm=item_name:
                            self._update_preview(i, ls, nm))

            if not parse_result.get("success"):
                err = parse_result.get("error", "파싱 실패")
                self.root.after(0, lambda e=err: self._set_status(f"파싱 오류: {e}"))
                self.root.after(0, lambda e=err: self._append_log(f"파싱 오류: {e}", "warn"))
                self.root.after(0, lambda n=item_name, e=err: self.overlay.show_error(f"{n}\n{e}"))
                return

            traderie_url = parse_result.get("traderie_url", "")
            api_url = parse_result.get("api_url", "")

            self.root.after(0, lambda: self._set_status("가격 조회 중..."))
            s_start, s_end, is_cur = self._get_season_dates()
            price_stats = fetch_price_stats(api_url, season_start=s_start, season_end=s_end, current_season=is_cur) if api_url else {}

            if not price_stats.get("success") and price_stats.get("error"):
                err = price_stats["error"]
                self.root.after(0, lambda e=err: self._append_log(f"[가격조회 오류] {e}", "error"))

            min_price = price_stats.get("min_text", "N/A")
            max_price = price_stats.get("max_text", "N/A")
            count     = price_stats.get("count", 0)

            if count == 0:
                min_price = "매물없음"
                max_price = "-"

            parsed_options = parse_result.get("options", {})
            options_editable = parse_result.get("options_editable", [])
            url_ctx = parse_result.get("url_ctx", {})
            slot = parse_result.get("slot", "")

            if parse_result.get("rarity") in ("magic", "charm") and parsed_options and not options_editable:
                self.root.after(0, lambda: self._append_log(
                    "옵션 매칭 실패: 화면에 표시된 옵션이 링크(URL)에는 반영되지 않았습니다 "
                    "(아이템 이름/어픽스 인식 오류로 추정)", "warn"))
            self.root.after(0, lambda _opts=parsed_options, _oe=options_editable,
                            _ctx=url_ctx, _sl=slot:
                            self._add_scan_result(
                                item_name, traderie_url, min_price, max_price, _opts, api_url,
                                _oe, _ctx, _sl))
            self.root.after(0, lambda: self._append_log(
                f"결과: {item_name}  최저 {min_price} / 최고 {max_price}", "success"))
            def _on_fav_click(_n=item_name, _u=traderie_url, _a=api_url,
                              _mn=min_price, _mx=max_price, _oe=options_editable,
                              _ctx=url_ctx, _sl=slot):
                self._toggle_fav_from_search(_n, _u, _a, _mn, _mx, _oe,
                                             url_ctx=_ctx, slot=_sl)
            _in_fav = self._is_in_fav(traderie_url)
            self.root.after(0, lambda _sl=slot, _fav=_on_fav_click, _if=_in_fav: self.overlay.show(
                item_name, traderie_url, min_price, max_price, count,
                slot=_sl, on_fav=_fav, is_fav=_if))

            self.logger.write(item_name, traderie_url, min_price, max_price)

            if from_file:
                self.root.after(0, lambda: self._set_status("이미지 분석 완료"))
            else:
                hotkey_disp = hotkey_display_name(self.config.get("hotkey", "print_screen"))
                _pname = self._selected_proc.window_title if self._selected_proc else "전체 화면"
                _pdisplay = _pname[:30] + "…" if len(_pname) > 30 else _pname
                self.root.after(0, lambda hd=hotkey_disp, pd=_pdisplay: self._set_status(
                    f"추적 중  [{hd}]  |  {pd}"))

        except Exception as e:
            import traceback
            err_msg  = str(e)
            full_tb  = traceback.format_exc()
            print(f"[Tracker] 처리 오류 전체 트레이스:\n{full_tb}")
            self.root.after(0, lambda: self._set_status(f"오류: {err_msg}"))
            self.root.after(0, lambda m=err_msg: self._append_log(f"처리 오류: {m}", "error"))
            self.root.after(0, lambda tb=full_tb: self._append_log(tb, "error"))
            self.root.after(0, lambda m=err_msg: self.overlay.show_error(f"처리 오류: {m}"))
        finally:
            self.is_processing = False
            # 큐 모드일 때는 _queue_worker의 finally에서 일괄 재개
            if not self._queue_worker_running:
                self.root.after(0, self._resume_fav)

    def _set_status(self, msg: str):
        self.lbl_status.config(text=msg)

    # ────────────────────── 로그창 ───────────────────────────────
    def _append_log(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_text.config(state="normal")
        self.log_text.insert("end", line, level)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ────────────────────── 시스템 트레이 ────────────────────────
    def _make_tray_image(self, active: bool) -> PILImage.Image:
        size = 32
        img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = "#4a7c4e" if active else "#555555"
        draw.ellipse([4, 4, size - 4, size - 4], fill=color)
        draw.text((9, 7), "D", fill="white")
        return img

    def _start_tray(self):
        if self._tray_icon:
            return

        hotkey_disp = hotkey_display_name(self.config.get("hotkey", "print_screen"))

        def _show(icon, item):
            self.root.after(0, self.root.deiconify)
            self.root.after(0, self.root.lift)

        def _stop(icon, item):
            self.root.after(0, self._on_stop)

        def _quit(icon, item):
            self.root.after(0, self._on_close)

        menu = pystray.Menu(
            pystray.MenuItem("D2R Tracker — 추적 중", None, enabled=False),
            pystray.MenuItem(f"핫키: {hotkey_disp}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("창 열기", _show, default=True),
            pystray.MenuItem("추적 종료", _stop),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", _quit),
        )

        icon_img = self._make_tray_image(active=True)

        if ICON_FILE.exists():
            try:
                icon_img = PILImage.open(str(ICON_FILE)).resize((32, 32))
            except Exception:
                pass

        self._tray_icon = pystray.Icon("D2RTracker", icon_img,
                                        "D2R Tracker — 추적 중", menu)
        self._tray_thread = threading.Thread(
            target=self._tray_icon.run, daemon=True)
        self._tray_thread.start()

    def _stop_tray(self):
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
            self._tray_thread = None

    # ────────────────────── OCR 모드 ─────────────────────────────
    def _on_ocr_mode_change(self):
        mode = self.ocr_mode_var.get()
        self.config["ocr_mode"] = mode
        save_config(self.config)
        self._update_ocr_mode_ui()

    def _update_ocr_mode_ui(self):
        """OCR 모드에 따라 AI API 키 버튼 활성/비활성"""
        mode = self.ocr_mode_var.get()
        try:
            if not self._is_premium:
                # 무료버전: AI 라디오 비활성화, paddle만 허용
                self.rb_ai.config(state="disabled")
                state = "disabled"
            else:
                self.rb_ai.config(state="normal")
                state = "normal" if mode == "ai" else "disabled"
            self.btn_ai_keys.config(state=state)
        except Exception:
            pass

    def _show_paddle_download_dialog(self):
        """PaddleOCR 모델 첫 다운로드 안내 + 진행 다이얼로그"""
        dialog = tk.Toplevel(self.root)
        dialog.title("PaddleOCR 모델 다운로드")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.wm_attributes("-topmost", True)
        dialog.grab_set()

        from ocr.paddle_ocr_bridge import is_paddle_installed as _pip_check
        _pkg_installed = _pip_check()
        _desc = (
            "PaddleOCR를 처음 사용합니다.\n한국어/영어 모델을 다운로드합니다. (약 300MB)"
            if _pkg_installed else
            "PaddleOCR 패키지가 없습니다.\n패키지 설치 후 모델을 다운로드합니다. (수 분 소요)"
        )
        tk.Label(
            dialog,
            text=_desc,
            bg=BG, fg=FG, font=("맑은 고딕", 11), justify="center",
        ).pack(padx=36, pady=(24, 10))

        progress = ttk.Progressbar(dialog, mode="indeterminate", length=320)
        progress.pack(padx=36, pady=(0, 8))

        self._dl_status_lbl = tk.Label(
            dialog, text="준비 중...",
            bg=BG, fg=FG2, font=("맑은 고딕", 9))
        self._dl_status_lbl.pack(pady=(0, 20))

        def _paddle_dl_status(msg: str):
            dialog.after(0, lambda m=msg: self._dl_status_lbl.config(text=m))
            dialog.after(0, lambda m=msg: self._append_log(m, "info"))

        self.paddle_bridge.set_status_callback(_paddle_dl_status)

        def _run():
            progress.start()
            try:
                self.paddle_bridge.init_ocr()
                dialog.after(0, lambda: [dialog.destroy(), self._do_start()])
            except Exception as e:
                err = str(e)
                dialog.after(0, lambda: progress.stop())
                dialog.after(0, lambda m=err: self._dl_status_lbl.config(
                    text=f"오류: {m}", fg=RED))
                dialog.after(0, lambda m=err: self._append_log(
                    f"PaddleOCR 모델 다운로드 실패: {m}", "error"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_close(self):
        self._on_stop()
        self._stop_tray()
        self.fav_overlay.stop()
        save_config(self.config)
        self.root.destroy()


def _set_dpi_awareness():
    """Windows 디스플레이 배율(125%, 150% 등)로 인해 창이 강제 확대되는 것을 방지"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_DEFAULT_W        = 1100  # 콘텐츠 기준 기본 가로 크기
_DEFAULT_H        = 900   # 콘텐츠 기준 기본 세로 크기
_SCREEN_FIT_RATIO = 0.85   # 화면 크기의 이 비율을 넘지 않도록 제한 (작은 노트북 화면 대응)


def main():
    _set_dpi_awareness()
    root = tk.Tk()
    root.minsize(1000, 580)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    init_w = max(780, min(_DEFAULT_W, int(sw * _SCREEN_FIT_RATIO)))
    init_h = max(580, min(_DEFAULT_H, int(sh * _SCREEN_FIT_RATIO)))
    root.maxsize(init_w * 2, init_h * 2)
    # root.geometry(f"{init_w}x{init_h}")
    root.geometry(f"{init_w}x{init_h}+100+50")  # 좌측에서 100px, 위에서 50px

    if ICON_FILE.exists():
        try:
            root.iconbitmap(str(ICON_FILE))
        except Exception:
            pass

    TrackerApp(root)
    root.mainloop()


if __name__ == "__main__":
    import sys, traceback, tempfile, os
    try:
        main()
    except Exception:
        # exe 배포 환경에서 콘솔이 없을 때 크래시 원인을 파일로 기록
        log_path = os.path.join(tempfile.gettempdir(), "d2r_tracker_crash.log")
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        try:
            import tkinter as _tk, tkinter.messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showerror("D2R Tracker 오류",
                          f"실행 중 오류가 발생했습니다.\n로그: {log_path}")
            _r.destroy()
        except Exception:
            pass
        raise
