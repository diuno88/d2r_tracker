"""
시세찾기 탭
extension '시세파악' 기능의 tkinter 포팅
"""
import tkinter as tk
from tkinter import ttk
import json
import threading
import webbrowser
from typing import Callable, Optional

from config import DATA_DIR
from item.url_builder import TraderieUrlBuilder
from utils.price_fetcher import fetch_price_stats
from utils.ui_helpers import mk_check as _mk_check

BG    = "#2b2b2b"
FG    = "#e0e0e0"
FG2   = "#aaaaaa"
GOLD  = "#d4a843"
RED   = "#ff6666"
GREEN = "#66ff66"

BASED = {"material", "rare", "magic"}
FIXED = {"unique", "set", "runeword"}



RARITIES = [
    ("재료",   "material",  "#9999cc"),
    ("매직",   "magic",     "#6688ff"),
    ("레어",   "rare",      "#cccc00"),
    ("유니크", "unique",    "#c68b3a"),
    ("세트",   "set",       "#33bb33"),
    ("룬워드", "runeword",  "#9966cc"),
]


class PriceSearchTab:
    """
    시세찾기 탭 컴포넌트.

    toggle_fav_cb(name, url, api_url, min_price, max_price, options_editable, url_ctx=None)
        → True: 추가됨, False: 제거됨
    is_in_fav_cb(url) → bool
    get_ladder_cb() → "Ladder" | "Non Ladder" | ...
    get_mode_cb()   → "Softcore" | "Hardcore"
    """

    def __init__(self, parent: tk.Frame,
                 toggle_fav_cb: Callable,
                 is_in_fav_cb: Callable,
                 get_ladder_cb: Callable,
                 get_mode_cb: Callable,
                 get_season_dates_cb: Optional[Callable] = None):
        self._parent              = parent
        self._toggle_fav_cb       = toggle_fav_cb
        self._is_in_fav_cb        = is_in_fav_cb
        self._get_ladder          = get_ladder_cb
        self._get_mode            = get_mode_cb
        self._get_season_dates_cb = get_season_dates_cb

        # ── 상태 ────────────────────────────────────────────────
        self._rarity_var    = tk.StringVar(value="")
        self._ethereal_var  = tk.BooleanVar(value=False)
        self._selected_ctg: Optional[str] = None
        self._selected_fixed: Optional[dict] = None
        self._added_opts: list[dict] = []

        # 아이템 체크박스 vars: id → {"var": BooleanVar, "item": dict}
        self._item_vars: dict = {}
        # 부적 체크박스 vars: id → {"var": BooleanVar, "item": dict,
        #                          "variant_vars": {variant_id: (BooleanVar, variant_dict)}}
        self._charm_vars: dict = {}
        # 속성 행: [{"prop_id", "check_var", "min_var", "max_var"}]
        self._desc_rows: list[dict] = []

        # 옵션 콤보 상태
        self._opt_sel_id   = None
        self._opt_sel_name = ""

        # ── 데이터 ──────────────────────────────────────────────
        self._cats:    dict       = {}
        self._bases:   list[dict] = []
        self._charms:  list[dict] = []
        self._uniques: list[dict] = []
        self._sets:    list[dict] = []
        self._rwords:  list[dict] = []
        self._opts:    list[dict] = []
        self._fixed_list: list[dict] = []  # 현재 등급 고정아이템 목록
        self._ctg_kor_map: dict = {}       # kor → key

        self._load_data()
        self._build(parent)

    # ── 데이터 로드 ─────────────────────────────────────────────
    def _load_data(self):
        def _load(fname):
            with open(DATA_DIR / fname, encoding="utf-8") as f:
                return json.load(f)
        try:
            self._cats  = _load("item-category.json")
            self._bases = _load("baseItemList.json")
            self._charms = _load("charm.json")
            raw = _load("uniqueResult.json")
            self._uniques = [x for x in raw if x.get("korName","").strip()]
            raw = _load("setItemList.json")
            self._sets = [x for x in raw if x.get("korName","").strip()]
            raw = _load("runWordsResult.json")
            self._rwords = [x for x in raw if x.get("korName","").strip()]
            raw = _load("optionCombo.json")
            self._opts = [x for x in raw if x.get("koKR","").strip()]
        except Exception as e:
            print(f"[PriceSearchTab] 데이터 로드 오류: {e}")

    # ── UI 구성 ─────────────────────────────────────────────────
    def _build(self, parent: tk.Frame):
        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=0)
        parent.columnconfigure(2, weight=2)
        parent.rowconfigure(1, weight=1)

        # 등급 선택 바
        self._build_rarity_bar(parent)

        tk.Frame(parent, bg="#444", height=1).grid(
            row=0, column=0, columnspan=3, sticky="sew")

        # 좌측 컨트롤 패널 (스크롤)
        self._build_left_panel(parent)

        # 구분선
        tk.Frame(parent, bg="#444", width=1).grid(row=1, column=1, sticky="ns")

        # 우측 결과 패널 (스크롤)
        self._build_right_panel(parent)

    def _build_rarity_bar(self, parent):
        bar = ttk.Frame(parent, padding=(10, 6, 10, 6))
        bar.grid(row=0, column=0, columnspan=3, sticky="ew")

        ttk.Label(bar, text="등급 :", foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(side="left", padx=(0, 10))

        for label, value, color in RARITIES:
            rb = tk.Radiobutton(
                bar, text=label,
                variable=self._rarity_var, value=value,
                command=self._on_rarity_change,
                bg=BG, fg=color, selectcolor="#555",
                activebackground=BG, activeforeground=color,
                font=("맑은 고딕", 10, "bold"),
                relief="flat", padx=6, pady=2)
            rb.pack(side="left", padx=2)

    def _build_left_panel(self, parent):
        outer = ttk.Frame(parent)
        outer.grid(row=1, column=0, sticky="nsew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._ctrl = ttk.Frame(canvas, padding=(10, 8))
        win = canvas.create_window((0, 0), window=self._ctrl, anchor="nw")

        self._ctrl.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))

        # 마우스 휠
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

        self._render_ctrl()

    def _build_right_panel(self, parent):
        outer = ttk.Frame(parent, padding=(8, 8))
        outer.grid(row=1, column=2, sticky="nsew")
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text="검색 결과", foreground=GOLD,
                  font=("맑은 고딕", 11, "bold")).grid(
                      row=0, column=0, sticky="w", pady=(0, 6))

        ro = ttk.Frame(outer)
        ro.grid(row=1, column=0, sticky="nsew")
        ro.rowconfigure(0, weight=1)
        ro.columnconfigure(0, weight=1)

        canvas = tk.Canvas(ro, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(ro, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._result_f = ttk.Frame(canvas, padding=(4, 4))
        win = canvas.create_window((0, 0), window=self._result_f, anchor="nw")
        self._result_f.bind("<Configure>",
                            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))

        self._lbl_hint = ttk.Label(self._result_f,
                                    text="등급을 선택하고 아이템을 고른 후 시세 검색을 눌러주세요.",
                                    foreground=FG2, font=("맑은 고딕", 9),
                                    wraplength=220)
        self._lbl_hint.pack(anchor="w", pady=4)

    # ── 컨트롤 패널 렌더 ────────────────────────────────────────
    def _render_ctrl(self):
        for w in self._ctrl.winfo_children():
            w.destroy()
        self._item_vars.clear()
        self._charm_vars.clear()
        self._desc_rows.clear()

        rarity = self._rarity_var.get()
        if not rarity:
            ttk.Label(self._ctrl, text="위에서 등급을 선택하세요.",
                      foreground=FG2, font=("맑은 고딕", 10)).pack(anchor="w", pady=20)
            return

        if rarity in BASED:
            self._build_based_ctrl()
        else:
            self._build_fixed_ctrl()

        self._build_option_section()
        self._build_extra_section()

    # ── Based 컨트롤 ─────────────────────────────────────────────
    def _build_based_ctrl(self):
        # 카테고리
        ttk.Label(self._ctrl, text="카테고리", foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(0, 4))

        ctg_entries = sorted(
            [(k, v.get("kor", k)) for k, v in self._cats.items()
             if v.get("kor") and k != "__composite"],
            key=lambda x: x[1])
        self._ctg_kor_map = {kor: key for key, kor in ctg_entries}
        kor_list = [kor for _, kor in ctg_entries]

        self._ctg_var = tk.StringVar()
        combo = ttk.Combobox(self._ctrl, textvariable=self._ctg_var,
                             values=kor_list, state="readonly", width=22)
        combo.pack(anchor="w")
        combo.bind("<<ComboboxSelected>>", self._on_ctg_change)

        # 베이스 선택 헤더 (접기/펼치기 + 검색)
        self._based_collapsed = False
        sep = ttk.Frame(self._ctrl)
        sep.pack(fill="x", pady=(6, 2))

        self._based_toggle_lbl = tk.Label(
            sep, text="▼", fg=GOLD, bg=BG, font=("맑은 고딕", 9), cursor="hand2")
        self._based_toggle_lbl.pack(side="left")
        ttk.Label(sep, text="베이스 선택", foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(side="left", padx=(4, 0))

        self._based_search_var = tk.StringVar()
        based_search_entry = tk.Entry(
            sep, textvariable=self._based_search_var,
            width=14, bg="#3a3a3a", fg=FG,
            insertbackground=FG, relief="flat", font=("맑은 고딕", 9))
        based_search_entry.pack(side="right", padx=(0, 4))
        ttk.Label(sep, text="검색", foreground=FG2,
                  font=("맑은 고딕", 8)).pack(side="right")

        self._item_tbl_frame = ttk.Frame(self._ctrl)
        self._item_tbl_frame.pack(fill="x")
        ttk.Label(self._item_tbl_frame, text="카테고리를 선택하세요.",
                  foreground=FG2, font=("맑은 고딕", 9)).pack(anchor="w")

        def _toggle_based(_e=None):
            self._based_collapsed = not self._based_collapsed
            self._based_toggle_lbl.config(text="▶" if self._based_collapsed else "▼")
            if self._based_collapsed:
                self._item_tbl_frame.pack_forget()
            else:
                self._item_tbl_frame.pack(fill="x")

        self._based_toggle_lbl.bind("<Button-1>", _toggle_based)

        def _on_based_search(*_):
            ctg = getattr(self, "_selected_ctg", None)
            if ctg == "charm":
                return  # 부적은 3종뿐이라 검색 필터 미적용
            if ctg:
                self._render_item_table(ctg)

        self._based_search_var.trace_add("write", _on_based_search)

    def _on_ctg_change(self, _event=None):
        kor = self._ctg_var.get()
        self._selected_ctg = self._ctg_kor_map.get(kor)
        self._item_vars.clear()
        self._charm_vars.clear()
        if self._selected_ctg == "charm":
            self._render_charm_table()
        elif self._selected_ctg:
            self._render_item_table(self._selected_ctg)

    def _render_item_table(self, ctg_key: str):
        for w in self._item_tbl_frame.winfo_children():
            w.destroy()
        self._item_vars.clear()

        items = [x for x in self._bases
                 if x.get("ctg") == ctg_key and x.get("korName","").strip()]
        if not items:
            ttk.Label(self._item_tbl_frame, text="해당 카테고리에 아이템이 없습니다.",
                      foreground=FG2, font=("맑은 고딕", 9)).pack(anchor="w")
            return

        # 검색 필터
        q = getattr(self, "_based_search_var", None)
        q = q.get().strip().lower() if q else ""
        if q:
            items = [x for x in items
                     if q in x.get("korName","").lower() or q in x.get("name","").lower()]

        has_tier = any(x.get("tier") for x in items)

        if not has_tier:
            # 반지/목걸이/주얼 등: 단순 목록, 자동 선택
            for item in sorted(items, key=lambda x: x.get("korName","")):
                var = tk.BooleanVar(value=True)
                self._item_vars[item["id"]] = {"var": var, "item": item}
                _mk_check(self._item_tbl_frame,
                          variable=var,
                          text=item.get("korName", item.get("name",""))).pack(anchor="w")
            return

        # 3티어 그리드
        groups: dict = {}
        for item in items:
            g    = item.get("ctgGroup") or item["id"]
            tier = (item.get("tier") or "Normal").lower()
            groups.setdefault(g, {}).setdefault(tier, []).append(item)

        # 헤더 + 전체선택
        hdr = ttk.Frame(self._item_tbl_frame)
        hdr.pack(fill="x")
        TIERS = [("normal","노말"), ("exceptional","익셉셔널"), ("elite","엘리트")]
        self._tier_all_vars = {t: tk.BooleanVar() for t, _ in TIERS}

        for col, (tier, label) in enumerate(TIERS):
            f = ttk.Frame(hdr)
            f.grid(row=0, column=col, padx=2, sticky="w")
            t_var = self._tier_all_vars[tier]
            def make_toggle(t=tier, v=t_var):
                def _toggle():
                    val = v.get()
                    for d in self._item_vars.values():
                        if (d["item"].get("tier","Normal").lower()) == t:
                            d["var"].set(val)
                return _toggle
            _mk_check(f, variable=t_var, command=make_toggle()).pack(side="left")
            ttk.Label(f, text=label, foreground=GOLD,
                      font=("맑은 고딕", 9, "bold")).pack(side="left")

        # 스크롤 테이블
        tbl_canvas = tk.Canvas(self._item_tbl_frame, bg=BG,
                               highlightthickness=0, height=200)
        tbl_sb = ttk.Scrollbar(self._item_tbl_frame,
                               orient="vertical", command=tbl_canvas.yview)
        tbl_canvas.configure(yscrollcommand=tbl_sb.set)
        tbl_canvas.pack(side="left", fill="both", expand=True)
        tbl_sb.pack(side="right", fill="y")

        inner = ttk.Frame(tbl_canvas)
        tbl_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: tbl_canvas.configure(scrollregion=tbl_canvas.bbox("all")))

        sorted_groups = sorted(
            groups.keys(),
            key=lambda g: (
                (groups[g].get("normal") or
                 groups[g].get("exceptional") or
                 groups[g].get("elite") or [{}])[0].get("korName","")
            ))

        for r, g in enumerate(sorted_groups):
            for col, (tier, _) in enumerate(TIERS):
                for item in sorted(groups[g].get(tier, []),
                                   key=lambda x: x.get("korName","")):
                    var = tk.BooleanVar()
                    self._item_vars[item["id"]] = {"var": var, "item": item}
                    _mk_check(inner, variable=var,
                              text=item.get("korName", item.get("name",""))
                              ).grid(row=r, column=col, sticky="w", padx=4, pady=1)

    def _render_charm_table(self):
        """
        부적 전용 베이스 선택 UI.
        작은부적/큰부적/거대부적 3종 + 종류별 모양(variant) 하위 체크박스.
        모양을 하나도 선택 안 하면 부적 id로만 검색, 선택하면 모양별 개별 검색.
        """
        for w in self._item_tbl_frame.winfo_children():
            w.destroy()
        self._charm_vars.clear()

        if not self._charms:
            ttk.Label(self._item_tbl_frame, text="부적 데이터가 없습니다.",
                      foreground=FG2, font=("맑은 고딕", 9)).pack(anchor="w")
            return

        for charm in sorted(self._charms, key=lambda x: x.get("korName", "")):
            cid = charm["id"]
            var = tk.BooleanVar()
            self._charm_vars[cid] = {"var": var, "item": charm, "variant_vars": {}}

            _mk_check(self._item_tbl_frame, variable=var,
                      text=charm.get("korName", charm.get("name", ""))
                      ).pack(anchor="w", pady=(4, 0))

            variant_f = ttk.Frame(self._item_tbl_frame)
            variant_f.pack(anchor="w", padx=(20, 0))
            for variant in charm.get("description_filtered", []):
                vid = variant.get("variant")
                if vid is None:
                    continue
                vvar = tk.BooleanVar()
                self._charm_vars[cid]["variant_vars"][vid] = (vvar, variant)
                _mk_check(variant_f, variable=vvar,
                          text=f"모양: {variant.get('kor', variant.get('eng',''))}"
                          ).pack(anchor="w")

    # ── Fixed 컨트롤 ─────────────────────────────────────────────
    def _build_fixed_ctrl(self):
        rarity = self._rarity_var.get()
        labels = {"unique": "유니크 아이템", "set": "세트 아이템", "runeword": "룬워드"}
        src = {"unique": self._uniques, "set": self._sets, "runeword": self._rwords}

        self._fixed_list = sorted(src.get(rarity, []),
                                   key=lambda x: x.get("korName",""))

        ttk.Label(self._ctrl, text=labels.get(rarity,"아이템"),
                  foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(0, 4))

        sf = ttk.Frame(self._ctrl)
        sf.pack(fill="x")

        self._fixed_entry = ttk.Entry(sf, width=26)
        self._fixed_entry.pack(side="left")
        self._fixed_entry.bind("<KeyRelease>", self._on_fixed_key)
        self._fixed_entry.bind("<FocusOut>",
                               lambda e: self._parent.after(200, self._hide_fixed_dd))

        tk.Button(sf, text="초기화", bg="#444", fg=FG2,
                  font=("맑은 고딕", 9), relief="flat", cursor="hand2",
                  command=self._reset_fixed).pack(side="left", padx=(6,0))

        self._fixed_dd: Optional[tk.Toplevel] = None

        # 베이스 선택 영역 (룬워드 전용, 초기 hidden)
        self._base_section = ttk.Frame(self._ctrl)
        self._base_section.pack(fill="x", pady=(8, 2))
        self._base_section_visible = False
        self._base_item_vars: list[dict] = []   # [{var, name, korName, nameId, id}]

        # 속성 목록 영역
        sep = ttk.Frame(self._ctrl)
        sep.pack(fill="x", pady=(8, 2))
        ttk.Label(sep, text="속성 목록", foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(side="left")

        self._desc_frame = ttk.Frame(self._ctrl)
        self._desc_frame.pack(fill="x")
        ttk.Label(self._desc_frame, text="아이템을 검색 후 선택하세요.",
                  foreground=FG2, font=("맑은 고딕", 9)).pack(anchor="w")

    def _on_fixed_key(self, _event=None):
        self._selected_fixed = None
        self._show_fixed_dd(self._fixed_entry.get().strip())

    def _show_fixed_dd(self, text: str):
        self._hide_fixed_dd()
        lf = text.lower()
        filtered = [x for x in self._fixed_list
                    if lf in x.get("korName","").lower()][:60]
        if not filtered:
            return

        try:
            x = self._fixed_entry.winfo_rootx()
            y = self._fixed_entry.winfo_rooty() + self._fixed_entry.winfo_height()
        except Exception:
            return

        dd = tk.Toplevel(self._parent)
        dd.wm_overrideredirect(True)
        dd.geometry(f"+{x}+{y}")
        dd.configure(bg="#333")
        lb = tk.Listbox(dd, bg="#333", fg=FG, selectbackground="#555",
                        font=("맑은 고딕", 10), width=30,
                        height=min(10, len(filtered)),
                        relief="flat", borderwidth=1)
        lb.pack(fill="both", expand=True)
        for item in filtered:
            lb.insert("end", item.get("korName",""))

        def on_sel(e=None):
            if e:
                idx = lb.nearest(e.y)
            else:
                sel = lb.curselection()
                idx = sel[0] if sel else -1
            if idx < 0 or idx >= len(filtered):
                return
            item = filtered[idx]
            self._fixed_entry.delete(0, "end")
            self._fixed_entry.insert(0, item.get("korName",""))
            self._selected_fixed = item
            dd.destroy()
            self._fixed_dd = None
            self._render_desc(item)

        lb.bind("<ButtonRelease-1>", on_sel)
        lb.bind("<Return>", on_sel)
        self._fixed_dd = dd

    def _hide_fixed_dd(self):
        if self._fixed_dd:
            try:
                self._fixed_dd.destroy()
            except Exception:
                pass
            self._fixed_dd = None

    def _reset_fixed(self):
        self._selected_fixed = None
        if hasattr(self, "_fixed_entry"):
            self._fixed_entry.delete(0, "end")
        if hasattr(self, "_base_section"):
            for w in self._base_section.winfo_children():
                w.destroy()
        self._base_item_vars.clear()
        if hasattr(self, "_desc_frame"):
            for w in self._desc_frame.winfo_children():
                w.destroy()
            ttk.Label(self._desc_frame, text="아이템을 검색 후 선택하세요.",
                      foreground=FG2, font=("맑은 고딕", 9)).pack(anchor="w")
        self._desc_rows.clear()

    def _render_desc(self, item: dict):
        # 룬워드이면 베이스 선택 UI 갱신
        if self._rarity_var.get() == "runeword":
            self._render_base_section(item)

        for w in self._desc_frame.winfo_children():
            w.destroy()
        self._desc_rows.clear()

        props = [p for p in item.get("description_filtered", [])
                 if p.get("property_id") and
                 (p.get("min") != p.get("max") or p.get("selectable"))]
        props.sort(key=lambda p: p.get("property_kor") or p.get("property") or "")

        if not props:
            ttk.Label(self._desc_frame, text="검색 가능한 속성이 없습니다.",
                      foreground=FG2, font=("맑은 고딕", 9)).pack(anchor="w")
            return

        # 헤더
        hdr = ttk.Frame(self._desc_frame)
        hdr.pack(fill="x")
        self._desc_all_var = tk.BooleanVar()
        _mk_check(hdr, variable=self._desc_all_var,
                  command=self._toggle_desc_all).grid(row=0, column=0)
        for col, (text, w) in enumerate([("속성명",22),("최고",6),("MIN",6),("MAX",6)], 1):
            fg = GOLD if text == "최고" else FG2
            ttk.Label(hdr, text=text, foreground=fg,
                      font=("맑은 고딕", 8, "bold"), width=w,
                      anchor="center").grid(row=0, column=col, padx=2)

        for prop in props:
            prop_id   = prop["property_id"]
            kor       = (prop.get("property_kor") or prop.get("property") or "")[:22]
            best      = abs(prop.get("max") or 0)
            def_min   = abs(prop.get("min") or 0)
            def_max   = abs(prop.get("max") or 0)

            row_f = ttk.Frame(self._desc_frame)
            row_f.pack(fill="x", pady=1)

            c_var   = tk.BooleanVar()
            min_var = tk.StringVar(value=str(def_min))
            max_var = tk.StringVar(value=str(def_max))

            _mk_check(row_f, variable=c_var).grid(row=0, column=0)
            ttk.Label(row_f, text=kor, foreground=FG,
                      font=("맑은 고딕", 9), width=22,
                      anchor="w").grid(row=0, column=1, sticky="w")
            ttk.Label(row_f, text=str(best), foreground=GOLD,
                      font=("맑은 고딕", 9), width=6,
                      anchor="center").grid(row=0, column=2)
            ttk.Entry(row_f, textvariable=min_var, width=6).grid(row=0, column=3, padx=2)
            ttk.Entry(row_f, textvariable=max_var, width=6).grid(row=0, column=4, padx=2)

            self._desc_rows.append({
                "prop_id":  prop_id,
                "name":     kor,
                "db_min":   def_min,
                "db_max":   def_max,
                "check_var": c_var,
                "min_var":   min_var,
                "max_var":   max_var,
            })

    def _toggle_desc_all(self):
        v = self._desc_all_var.get()
        for row in self._desc_rows:
            row["check_var"].set(v)

    # ── 룬워드 베이스 선택 ──────────────────────────────────────
    def _get_ctgs_from_base_key(self, base_key: str) -> list[str]:
        """'Base Item (Shield, Sword) 3' → ctg 키 목록"""
        import re
        m = re.match(r"^Base Item \((.+)\) \d+$", base_key)
        if not m:
            return []
        type_names = [t.strip() for t in m.group(1).split(",")]
        composite  = self._cats.get("__composite", {})

        # same 역방향 맵
        reverse: dict[str, list[str]] = {}
        for ctg, info in self._cats.items():
            if ctg == "__composite":
                continue
            s = info.get("same")
            if s:
                reverse.setdefault(s, []).append(ctg)

        result: set[str] = set()
        for tname in type_names:
            if tname in composite:
                result.update(composite[tname])
            for ctg in reverse.get(tname, []):
                result.add(ctg)
        return list(result)

    def _render_base_section(self, item: dict):
        """룬워드 베이스 선택 UI를 그린다."""
        for w in self._base_section.winfo_children():
            w.destroy()
        self._base_item_vars.clear()

        base_key = item.get("baseItemKey", "")
        if not base_key:
            return

        ctgs = self._get_ctgs_from_base_key(base_key)
        base_items = sorted(
            [b for b in self._bases if b.get("ctg") in ctgs and b.get("korName","").strip()],
            key=lambda x: (x.get("ctg",""), x.get("korName",""))
        )
        if not base_items:
            return

        ttk.Separator(self._base_section, orient="horizontal").pack(fill="x", pady=(4, 6))

        # ── 헤더: 접기/펼치기 토글 버튼 ──
        self._base_collapsed = getattr(self, "_base_collapsed", False)
        hdr = ttk.Frame(self._base_section)
        hdr.pack(fill="x")

        self._base_toggle_lbl = tk.Label(
            hdr, text="▼" if not self._base_collapsed else "▶",
            fg=GOLD, bg=BG, font=("맑은 고딕", 9),
            cursor="hand2")
        self._base_toggle_lbl.pack(side="left")
        ttk.Label(hdr, text="베이스 선택", foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(side="left", padx=(4, 0))
        ttk.Label(hdr, text="(미선택시 베이스 구분없이 검색)",
                  foreground=FG2, font=("맑은 고딕", 8)).pack(side="left", padx=(6, 0))

        # 검색 입력창
        search_row = ttk.Frame(hdr)
        search_row.pack(side="right")
        self._base_search_var = tk.StringVar()
        base_search_entry = tk.Entry(
            search_row, textvariable=self._base_search_var,
            width=14, bg="#3a3a3a", fg=FG,
            insertbackground=FG, relief="flat", font=("맑은 고딕", 9))
        base_search_entry.pack(side="left", padx=(0, 2))
        ttk.Label(search_row, text="검색", foreground=FG2,
                  font=("맑은 고딕", 8)).pack(side="left")

        # ── 베이스 목록 본체 (접기/펼치기 대상) ──
        self._base_body = ttk.Frame(self._base_section)
        if not self._base_collapsed:
            self._base_body.pack(fill="x", pady=(4, 0))

        self._base_all_items = base_items  # 검색 필터를 위해 보관

        def _toggle_base(_e=None):
            self._base_collapsed = not self._base_collapsed
            self._base_toggle_lbl.config(
                text="▶" if self._base_collapsed else "▼")
            if self._base_collapsed:
                self._base_body.pack_forget()
            else:
                self._base_body.pack(fill="x", pady=(4, 0))

        self._base_toggle_lbl.bind("<Button-1>", _toggle_base)

        def _on_base_search(*_):
            self._render_base_body(self._base_body, self._base_all_items,
                                   self._base_search_var.get())

        self._base_search_var.trace_add("write", _on_base_search)
        self._render_base_body(self._base_body, base_items, "")

    def _render_base_body(self, container: ttk.Frame, base_items: list, query: str):
        """베이스 체크박스 목록을 (재)그린다 — 검색 필터 적용"""
        for w in container.winfo_children():
            w.destroy()
        # 검색어로 필터
        q = query.strip().lower()
        filtered = [b for b in base_items
                    if not q or q in b.get("korName", "").lower()
                    or q in b.get("name", "").lower()]

        # tier 그룹 표로 표시
        TIERS = [("normal","노말"), ("exceptional","익셉"), ("elite","엘리트")]
        groups: dict[str, dict[str, list]] = {}
        for b in filtered:
            g = b.get("ctgGroup") or b.get("id")
            t = (b.get("tier") or "normal").lower()
            groups.setdefault(str(g), {}).setdefault(t, []).append(b)

        tbl_f = ttk.Frame(container)
        tbl_f.pack(fill="x")

        for ci, (_, label) in enumerate(TIERS):
            ttk.Label(tbl_f, text=label, foreground=FG2,
                      font=("맑은 고딕", 8, "bold"), width=10,
                      anchor="center").grid(row=0, column=ci, padx=2)

        # 검색 필터 후 vars 재구성 (체크상태 유지하려면 기존 var 매칭)
        existing = {v["name"]: v for v in self._base_item_vars}
        self._base_item_vars.clear()

        row_idx = 1
        for g_key in sorted(groups.keys()):
            g = groups[g_key]
            max_rows = max(len(g.get(t, [])) for t, _ in TIERS)
            for ri in range(max_rows):
                for ci, (tier, _) in enumerate(TIERS):
                    items_in_cell = g.get(tier, [])
                    if ri < len(items_in_cell):
                        b = items_in_cell[ri]
                        bname = b.get("name", "")
                        prev = existing.get(bname)
                        var = prev["var"] if prev else tk.BooleanVar()
                        self._base_item_vars.append({
                            "var": var, "name": bname,
                            "korName": b.get("korName",""),
                            "nameId": b.get("nameId",""),
                            "id": b.get("id",""),
                        })
                        _mk_check(tbl_f, variable=var,
                                  text=b.get("korName","")).grid(
                                      row=row_idx, column=ci,
                                      sticky="w", padx=2, pady=1)
                row_idx += 1

    # ── 옵션 추가 섹션 ──────────────────────────────────────────
    def _build_option_section(self):
        ttk.Separator(self._ctrl, orient="horizontal").pack(fill="x", pady=(10, 6))

        ttk.Label(self._ctrl, text="옵션 추가", foreground=GOLD,
                  font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(0, 4))

        row = ttk.Frame(self._ctrl)
        row.pack(fill="x")

        self._opt_entry = ttk.Entry(row, width=26)
        self._opt_entry.pack(side="left")
        self._opt_entry.bind("<KeyRelease>", self._on_opt_key)
        self._opt_entry.bind("<FocusOut>",
                             lambda e: self._parent.after(200, self._hide_opt_dd))

        self._opt_min_var = tk.StringVar(value="0")
        self._opt_max_var = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self._opt_min_var, width=5).pack(side="left", padx=(6,2))
        ttk.Label(row, text="~", foreground=FG2).pack(side="left")
        ttk.Entry(row, textvariable=self._opt_max_var, width=5).pack(side="left", padx=(2,4))
        tk.Button(row, text="추가", bg="#444", fg=FG,
                  font=("맑은 고딕", 9), relief="flat", cursor="hand2",
                  command=self._add_option).pack(side="left")

        self._opt_dd: Optional[tk.Toplevel] = None

        self._added_frame = ttk.Frame(self._ctrl)
        self._added_frame.pack(fill="x", pady=(4, 0))
        self._render_added()

    def _on_opt_key(self, _event=None):
        self._opt_sel_id   = None
        self._opt_sel_name = ""
        self._show_opt_dd(self._opt_entry.get().strip())

    def _show_opt_dd(self, text: str):
        self._hide_opt_dd()
        rarity = self._rarity_var.get()
        pool   = ([o for o in self._opts if "전용" in o.get("koKR","")]
                  if rarity == "runeword" else self._opts)
        lf = text.lower()
        filtered = [o for o in pool if lf in o.get("koKR","").lower()][:60] if lf else pool[:60]
        if not filtered:
            return
        try:
            x = self._opt_entry.winfo_rootx()
            y = self._opt_entry.winfo_rooty() + self._opt_entry.winfo_height()
        except Exception:
            return

        dd = tk.Toplevel(self._parent)
        dd.wm_overrideredirect(True)
        dd.geometry(f"+{x}+{y}")
        dd.configure(bg="#333")
        lb = tk.Listbox(dd, bg="#333", fg=FG, selectbackground="#555",
                        font=("맑은 고딕", 9), width=40,
                        height=min(10, len(filtered)),
                        relief="flat", borderwidth=1)
        lb.pack(fill="both", expand=True)
        for o in filtered:
            lb.insert("end", o.get("koKR",""))

        def on_sel(e=None):
            if e:
                idx = lb.nearest(e.y)
            else:
                sel = lb.curselection()
                idx = sel[0] if sel else -1
            if idx < 0 or idx >= len(filtered):
                return
            opt = filtered[idx]
            self._opt_entry.delete(0, "end")
            self._opt_entry.insert(0, opt.get("koKR",""))
            self._opt_sel_id   = opt["id"]
            self._opt_sel_name = opt.get("koKR","")
            dd.destroy()
            self._opt_dd = None

        lb.bind("<ButtonRelease-1>", on_sel)
        lb.bind("<Return>", on_sel)
        self._opt_dd = dd

    def _hide_opt_dd(self):
        if self._opt_dd:
            try:
                self._opt_dd.destroy()
            except Exception:
                pass
            self._opt_dd = None

    def _add_option(self):
        typed = self._opt_entry.get().strip()
        if not typed:
            return
        key  = self._opt_sel_id
        name = self._opt_sel_name
        if not key or name != typed:
            match = next((o for o in self._opts if o.get("koKR") == typed), None)
            if not match:
                return
            key  = match["id"]
            name = match.get("koKR","")
        if any(o["key"] == key for o in self._added_opts):
            return
        try:
            min_v = max(0, int(float(self._opt_min_var.get() or 0)))
            max_v = max(0, int(float(self._opt_max_var.get() or 0)))
        except ValueError:
            min_v = max_v = 0
        self._added_opts.append({"key": key, "name": name, "min": min_v, "max": max_v})
        self._opt_entry.delete(0, "end")
        self._opt_min_var.set("0")
        self._opt_max_var.set("0")
        self._opt_sel_id   = None
        self._opt_sel_name = ""
        self._render_added()

    def _remove_option(self, idx: int):
        if 0 <= idx < len(self._added_opts):
            self._added_opts.pop(idx)
            self._render_added()

    def _render_added(self):
        for w in self._added_frame.winfo_children():
            w.destroy()
        for i, opt in enumerate(self._added_opts):
            row = ttk.Frame(self._added_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=opt["name"][:24], foreground=FG,
                      font=("맑은 고딕", 9)).pack(side="left")
            ttk.Label(row, text=f"  ({opt['min']}~{opt['max']})",
                      foreground=FG2, font=("맑은 고딕", 9)).pack(side="left")
            def _rm(idx=i):
                self._remove_option(idx)
            tk.Button(row, text="✕", bg=BG, fg=RED,
                      font=("맑은 고딕", 8), relief="flat", cursor="hand2",
                      command=_rm).pack(side="left", padx=(4,0))

    # ── 추가 옵션 섹션 (에테리얼 + 검색 버튼) ──────────────────
    def _build_extra_section(self):
        ttk.Separator(self._ctrl, orient="horizontal").pack(fill="x", pady=(10, 6))

        extra = ttk.Frame(self._ctrl)
        extra.pack(fill="x", pady=(0, 8))
        _mk_check(extra, variable=self._ethereal_var,
                  text="에테리얼").pack(side="left")

        self._btn_search = tk.Button(
            self._ctrl, text="시세 검색",
            bg=GOLD, fg="#111",
            font=("맑은 고딕", 11, "bold"),
            relief="flat", cursor="hand2",
            command=self._do_search,
            padx=20, pady=6)
        self._btn_search.pack(anchor="w")

    # ── 이벤트 ──────────────────────────────────────────────────
    def _on_rarity_change(self):
        self._selected_ctg   = None
        self._selected_fixed = None
        self._added_opts.clear()
        self._ethereal_var.set(False)
        self._render_ctrl()
        self._clear_results()

    # ── 검색 ────────────────────────────────────────────────────
    def _do_search(self):
        if not self._rarity_var.get():
            return
        self._btn_search.config(state="disabled", text="검색 중...")
        self._clear_results()
        self._show_hint("검색 중...")
        threading.Thread(target=self._search_thread, daemon=True).start()

    def _search_thread(self):
        try:
            rarity   = self._rarity_var.get()
            ladder   = self._get_ladder()
            mode     = self._get_mode()
            ethereal = self._ethereal_var.get()
            results  = (self._search_based(rarity, ladder, mode, ethereal)
                        if rarity in BASED
                        else self._search_fixed(ladder, mode, ethereal))
            self._parent.after(0, lambda: self._show_results(results))
        except Exception as e:
            self._parent.after(0, lambda: self._show_hint(f"오류: {e}"))
        finally:
            self._parent.after(0, lambda: self._btn_search.config(
                state="normal", text="시세 검색"))

    def _fetch_price_stats(self, api_url: str) -> dict:
        """시즌 설정 반영한 가격 조회"""
        if self._get_season_dates_cb:
            s_start, s_end, is_cur = self._get_season_dates_cb()
            return fetch_price_stats(api_url, season_start=s_start, season_end=s_end,
                                     current_season=is_cur)
        return fetch_price_stats(api_url)

    def _build_opts_editable_from_added(self) -> list[dict]:
        """수동 추가 옵션 → options_editable 포맷"""
        return [{
            "name":      o["name"],
            "key":       o["key"],
            "db_min":    o["min"],
            "db_max":    o["max"],
            "min":       o["min"],
            "max":       o["max"],
            "selectable": False,
            "included":  True,
        } for o in self._added_opts]

    def _search_charm(self, ladder, mode, ethereal) -> list[dict]:
        """
        부적 검색: 모양(variant) 미선택 시 부적 id로만 검색,
        선택 시 모양별로 개별 쿼리 후 결과를 합친다.
        부적은 항상 magic이지만 traderie 쪽에 rarity 파라미터를 보내지 않는다.
        """
        checked = [(cid, d) for cid, d in self._charm_vars.items() if d["var"].get()]
        if not checked:
            return []
        opts_ed = self._build_opts_editable_from_added()
        url_opts = [{"key": o["key"], "min": o["min"], "max": o["max"]}
                    for o in self._added_opts]
        results = []
        for cid, d in checked:
            item = d["item"]
            name_id = item.get("nameId", "")
            if not name_id:
                continue
            selected_variants = [(vid, vinfo) for vid, (vvar, vinfo)
                                  in d["variant_vars"].items() if vvar.get()]

            url_ctx = {
                "name_id": name_id, "item_key": cid,
                "ladder": ladder, "mode": mode, "ethereal": ethereal,
                "rarity": "charm",
            }
            if not selected_variants:
                ub = TraderieUrlBuilder(name_id, cid)
                ub.set_common_props(ladder, mode, ethereal)
                # rarity 파라미터 미사용 (charm은 항상 magic)
                ub.set_options(url_opts)
                results.append({
                    "name":             item.get("korName", item.get("name", "")),
                    "api_url":          ub.get_base_url(),
                    "url":              ub.get_real_url(),
                    "stats":            self._fetch_price_stats(ub.get_base_url()),
                    "options_editable": opts_ed,
                    "url_ctx":          url_ctx,
                })
            else:
                for vid, vinfo in selected_variants:
                    ub = TraderieUrlBuilder(name_id, cid)
                    ub.set_common_props(ladder, mode, ethereal)
                    ub.set_options(url_opts)
                    ub.params['variant'] = vid   # prop_ 접두어 없이 그대로 variant 파라미터
                    results.append({
                        "name": f'{item.get("korName","")} ({vinfo.get("kor","")})',
                        "api_url":          ub.get_base_url(),
                        "url":              ub.get_real_url(),
                        "stats":            self._fetch_price_stats(ub.get_base_url()),
                        "options_editable": opts_ed,
                        "url_ctx":          {**url_ctx, "extra_params": {"variant": vid}},
                    })
        return results

    def _search_based(self, rarity, ladder, mode, ethereal) -> list[dict]:
        if self._selected_ctg == "charm":
            return self._search_charm(ladder, mode, ethereal)
        checked = [(iid, d) for iid, d in self._item_vars.items() if d["var"].get()]
        if not checked:
            return []
        rarity_param = {"rare": "rare", "magic": "magic"}.get(rarity)
        opts_ed = self._build_opts_editable_from_added()
        results = []
        for iid, d in checked:
            item    = d["item"]
            name_id = item.get("nameId", "")
            if not name_id:
                continue
            ub = TraderieUrlBuilder(name_id, iid)
            ub.set_common_props(ladder, mode, ethereal)
            if rarity_param:
                ub.set_rarity(rarity_param)
            ub.set_options([{"key": o["key"], "min": o["min"], "max": o["max"]}
                            for o in self._added_opts])
            results.append({
                "name":             item.get("korName", item.get("name","")),
                "api_url":          ub.get_base_url(),
                "url":              ub.get_real_url(),
                "stats":            self._fetch_price_stats(ub.get_base_url()),
                "options_editable": opts_ed,
                "url_ctx": {
                    "name_id": name_id, "item_key": iid,
                    "ladder": ladder, "mode": mode, "ethereal": ethereal,
                    "rarity": rarity,
                },
            })
        return results

    def _search_fixed(self, ladder, mode, ethereal) -> list[dict]:
        item = self._selected_fixed
        if not item or not item.get("nameId"):
            return []

        # 체크된 desc 속성 → URL 파라미터 + options_editable
        desc_url_opts = []
        desc_editable = []
        for r in self._desc_rows:
            if not r["check_var"].get():
                continue
            min_v = max(0, int(float(r["min_var"].get() or 0)))
            max_v = max(0, int(float(r["max_var"].get() or 0)))
            desc_url_opts.append({"key": r["prop_id"], "min": min_v, "max": max_v})
            desc_editable.append({
                "name":      r["name"],
                "key":       r["prop_id"],
                "db_min":    r["db_min"],
                "db_max":    r["db_max"],
                "min":       min_v,
                "max":       max_v,
                "selectable": False,
                "included":  True,
            })

        all_url_opts = desc_url_opts + [
            {"key": o["key"], "min": o["min"], "max": o["max"]}
            for o in self._added_opts
        ]
        opts_ed = desc_editable + self._build_opts_editable_from_added()

        base_key     = item.get("baseItemKey", "")
        selected_bases = [b for b in self._base_item_vars if b["var"].get()]
        rarity = self._rarity_var.get()

        # 룬워드 + 베이스 선택 → 베이스별 개별 검색
        if base_key and selected_bases:
            results = []
            for base in selected_bases:
                ub = TraderieUrlBuilder(item["nameId"], item["id"])
                ub.set_common_props(ladder, mode, ethereal)
                ub.set_options(all_url_opts)
                ub.params[f"prop_{base_key}"] = base["name"]
                results.append({
                    "name":             f"{item.get('korName','')} ({base['korName']})",
                    "api_url":          ub.get_base_url(),
                    "url":              ub.get_real_url(),
                    "stats":            self._fetch_price_stats(ub.get_base_url()),
                    "options_editable": opts_ed,
                    "url_ctx": {
                        "name_id": item["nameId"], "item_key": item["id"],
                        "ladder": ladder, "mode": mode, "ethereal": ethereal,
                        "rarity": rarity,
                        "extra_params": {f"prop_{base_key}": base["name"]},
                    },
                })
            return results

        # 베이스 미선택 → 기존 단일 검색
        ub = TraderieUrlBuilder(item["nameId"], item["id"])
        ub.set_common_props(ladder, mode, ethereal)
        ub.set_options(all_url_opts)
        return [{
            "name":             item.get("korName",""),
            "api_url":          ub.get_base_url(),
            "url":              ub.get_real_url(),
            "stats":            fetch_price_stats(ub.get_base_url()),
            "options_editable": opts_ed,
            "url_ctx": {
                "name_id": item["nameId"], "item_key": item["id"],
                "ladder": ladder, "mode": mode, "ethereal": ethereal,
                "rarity": rarity,
            },
        }]

    # ── 결과 표시 ────────────────────────────────────────────────
    def _show_results(self, results: list[dict]):
        self._clear_results()
        if not results:
            self._show_hint("아이템을 선택하세요.")
            return
        for res in results:
            self._add_result_card(res)

    def _add_result_card(self, res: dict):
        stats    = res["stats"]
        name     = res["name"]
        url      = res["url"]
        api_url  = res["api_url"]
        opts_ed  = res.get("options_editable", [])
        url_ctx  = res.get("url_ctx", {})

        card = tk.Frame(self._result_f, bg="#333333", bd=0)
        card.pack(fill="x", pady=3, padx=2)
        card.columnconfigure(1, weight=1)

        lbl = tk.Label(card, text=name, bg="#333333", fg=GOLD,
                       font=("맑은 고딕", 10, "bold"),
                       cursor="hand2", anchor="w", padx=8, pady=4)
        lbl.grid(row=0, column=0, columnspan=2, sticky="ew")
        lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        if stats.get("success"):
            min_t = stats.get("min_text", "N/A")
            max_t = stats.get("max_text", "N/A")
            cnt   = stats.get("count", 0)
            tk.Label(card, text=f"최저 {min_t}", bg="#333333", fg=GREEN,
                     font=("맑은 고딕", 9), padx=8).grid(row=1, column=0, sticky="w")
            tk.Label(card, text=f"최고 {max_t}", bg="#333333", fg=RED,
                     font=("맑은 고딕", 9)).grid(row=1, column=1, sticky="w")
            tk.Label(card, text=f"({cnt}건)", bg="#333333", fg=FG2,
                     font=("맑은 고딕", 8), padx=4).grid(row=1, column=2, sticky="w")
        else:
            tk.Label(card, text=stats.get("error","조회 실패"),
                     bg="#333333", fg=RED,
                     font=("맑은 고딕", 9), padx=8).grid(
                         row=1, column=0, columnspan=3, sticky="w")

        # ★ 토글 버튼 — 즐겨찾기 여부에 따라 채움/빈 별
        in_fav   = self._is_in_fav_cb(url)
        star_btn = tk.Button(card, bg="#333333",
                             font=("맑은 고딕", 12), relief="flat", cursor="hand2")
        star_btn.grid(row=0, column=3, rowspan=2, padx=(0, 6))
        self._update_star_btn(star_btn, in_fav)

        def _toggle_fav(btn=star_btn, n=name, u=url, a=api_url,
                        s=stats, oe=opts_ed, ctx=url_ctx):
            min_p   = s.get("min_text","N/A") if s.get("success") else "N/A"
            max_p   = s.get("max_text","N/A") if s.get("success") else "N/A"
            added   = self._toggle_fav_cb(n, u, a, min_p, max_p, oe, url_ctx=ctx)
            self._update_star_btn(btn, added)

        star_btn.config(command=_toggle_fav)

    def _update_star_btn(self, btn: tk.Button, in_fav: bool):
        if in_fav:
            btn.config(text="★", fg=GOLD)
        else:
            btn.config(text="☆", fg=FG2)

    def _clear_results(self):
        for w in self._result_f.winfo_children():
            w.destroy()

    def _show_hint(self, text: str):
        self._clear_results()
        ttk.Label(self._result_f, text=text,
                  foreground=FG2, font=("맑은 고딕", 9),
                  wraplength=220).pack(anchor="w", pady=4)
