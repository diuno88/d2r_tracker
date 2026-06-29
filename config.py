"""
Tracker 설정 관리
개발 환경과 PyInstaller 번들 환경 모두 지원
경로 설정은 path.properties 파일에서 관리
"""
import json
import sys
from pathlib import Path


# ── 런타임 디렉토리 ──────────────────────────────────────────

def _get_runtime_dir() -> Path:
    """실행 환경에 따른 기준 디렉토리 (exe 옆 / tracker/ 폴더)"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _get_meipass_dir() -> Path:
    """PyInstaller 내부 리소스 경로"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


RUNTIME_DIR = _get_runtime_dir()
MEIPASS_DIR = _get_meipass_dir()


# ── path.properties 로드 ─────────────────────────────────────

def _load_path_properties() -> dict:
    """path.properties 파일을 읽어 {key: value} dict 반환"""
    props: dict[str, str] = {}

    # RUNTIME_DIR 옆 우선, 없으면 이 파일과 같은 디렉토리
    for candidate in (RUNTIME_DIR / "path.properties",
                      Path(__file__).parent / "path.properties"):
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, val = line.partition("=")
                        props[key.strip()] = val.strip()
            break

    return props


_PROPS = _load_path_properties()


def _p(key: str, default: str = "") -> str:
    """path.properties 값 조회 (없으면 default 반환)"""
    return _PROPS.get(key, default)


def _rel(key: str, default: str) -> Path:
    """RUNTIME_DIR 기준 상대 경로 → 절대 Path"""
    return RUNTIME_DIR / _p(key, default)


def _expand(val: str) -> Path:
    """~ 를 홈 디렉토리로 치환 후 Path 반환"""
    return Path(val.replace("~", str(Path.home())))


def _get_documents_dir() -> str:
    """
    Windows 실제 Documents 폴더 경로 반환.
    OneDrive·폴더 리다이렉트 등에도 올바른 경로를 반환하기 위해
    Windows 레지스트리에서 직접 읽는다.
    """
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        ) as key:
            docs, _ = winreg.QueryValueEx(key, "Personal")
            if docs and Path(docs).exists():
                return docs
    except Exception:
        pass
    # 레지스트리 실패 시 홈/Documents 폴백
    fallback = Path.home() / "Documents"
    return str(fallback)


# ── 경로 상수 ────────────────────────────────────────────────

CONFIG_FILE       = _rel("config.file",      "tracker_config.json")
AI_KEYS_FILE      = _rel("ai_keys.file",     "tracker_config_keys.json")
NODE_WORKER_PATH  = _rel("node_worker.file", "node_worker/ocr_worker.js")
DATA_DIR          = _rel("data.dir",         "data")
ICON_FILE         = _rel("icon.file",        "icon.ico")

# 부위 아이콘 폴더: tracker/icon (개발/번들 모두 RUNTIME_DIR 하위)
SLOT_ICONS_DIR = RUNTIME_DIR / "icon"

CAPTURES_SUBDIR   = _p("captures.subdir",   "D2R_Tracker/captures")
CAPTURES_FILENAME = _p("captures.filename", "cap_latest.png")
LOG_DEFAULT_ROOT  = _get_documents_dir()

AI_MODEL_GEMINI = _p("ai.model.gemini", "gemini-2.0-flash")
AI_MODEL_GROQ   = _p("ai.model.groq",   "meta-llama/llama-4-scout-17b-16e-instruct")

GITHUB_DATA_URL   = _p("github.data.url",
                        "https://raw.githubusercontent.com/diuno88/d2r_kain/main/")
GITHUB_DATA_FILES = [f.strip()
                     for f in _p("github.data.files", "").split(",")
                     if f.strip()] or [
    "baseItemList.json", "craftedResult.json", "d2r_affixes_detailed.json",
    "item-category.json", "ladderSeason.json", "optionCombo.json",
    "runWordsResult.json", "setItemList.json", "uniqueResult.json",
]

# 유료 키 인증: GitHub에는 평문 키가 아닌 SHA-256 해시값만 공개로 올린다
GITHUB_PREMIUM_KEY_URL = _p("github.premium_key.url",
                             GITHUB_DATA_URL + "premium_keys.json")

# Node 실행파일: 번들된 exe 우선, 없으면 시스템 PATH의 node
_bundled_node = _rel("node.exe", "node/node.exe")
NODE_EXE = str(_bundled_node) if _bundled_node.exists() else "node"

# tessdata: 번들 디렉토리 우선, 없으면 개발 환경 extension/data
_bundled_tessdata = _rel("tessdata.dir", "tessdata")
if _bundled_tessdata.exists():
    TESSDATA_PATH = str(_bundled_tessdata)
else:
    TESSDATA_PATH = str(RUNTIME_DIR.parent / "extension" / "data")

# 아이템 데이터: tracker/data 우선 → _internal/tracker_data fallback
_bundled_data = MEIPASS_DIR / "tracker_data"
if DATA_DIR.exists():
    BACKEND_DATA_PATH = str(DATA_DIR)
elif _bundled_data.exists():
    BACKEND_DATA_PATH = str(_bundled_data)
else:
    BACKEND_DATA_PATH = str(DATA_DIR)

# 개발 환경 전용
PROJECT_ROOT = RUNTIME_DIR.parent if not getattr(sys, 'frozen', False) else None
BACKEND_PATH = PROJECT_ROOT / "backend" if PROJECT_ROOT else None


# ── 기본 설정값 ──────────────────────────────────────────────

DEFAULT_CONFIG = {
    "hotkey":            "print_screen",
    "log_enabled":       False,
    "log_path":          LOG_DEFAULT_ROOT,
    "ladder":            "Ladder",
    "mode":              "Softcore",
    "ladder_season":     14,           # 0 = 전체, 1~N = 특정 시즌 (기본: 최신 시즌)
    "language":          "kor",
    "option_max_offset": 0,
    "ocr_mode":          "paddle",       # "paddle" | "ai"
    "overlay_position":       "top",   # "top" | "bottom"
    "overlay_bottom_offset":  180,    # HUD 위 고정 px
    "overlay_bg_color":       "#111111",
    "overlay_text_color":     "#d4a843",
    "overlay_font_extra":     0,
    "is_premium":             False,
    "premium_key":            "",
    "fav_refresh_min":        5,
    "fav_overlay_interval_min": 5,
    "favorites":              [],
}


# ── 설정 파일 입출력 ─────────────────────────────────────────

def _sanitize_log_path(raw: str) -> str:
    """
    log_path 안전성 검사.
    홈 루트이거나 빈 값이면 LOG_DEFAULT_ROOT 로 교정해서 반환.
    """
    import os
    if not raw:
        return LOG_DEFAULT_ROOT
    try:
        # resolve() 없이 normcase + abspath 비교 (symlink/junction 불필요)
        home_nc = os.path.normcase(os.path.abspath(str(Path.home())))
        raw_nc  = os.path.normcase(os.path.abspath(raw))
        if raw_nc == home_nc:
            return LOG_DEFAULT_ROOT
    except Exception:
        return LOG_DEFAULT_ROOT
    return raw


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config = DEFAULT_CONFIG.copy()
            config.update(saved)
            config["log_path"] = _sanitize_log_path(config.get("log_path", ""))
            return config
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


DEFAULT_PROVIDER_ORDER = ["groq", "gemini"]


def load_ai_keys() -> dict:
    defaults = {
        "gemini": "", "groq": "",
        "gemini_model": AI_MODEL_GEMINI,
        "groq_model":   AI_MODEL_GROQ,
        "order": DEFAULT_PROVIDER_ORDER[:],
    }
    if AI_KEYS_FILE.exists():
        try:
            with open(AI_KEYS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for p in ("gemini", "groq"):
                if p in saved:
                    defaults[p] = saved[p]
                model_key = f"{p}_model"
                if model_key in saved and saved[model_key].strip():
                    defaults[model_key] = saved[model_key].strip()
            order = [p for p in saved.get("order", DEFAULT_PROVIDER_ORDER[:])
                     if p in ("gemini", "groq")]
            if not order:
                order = DEFAULT_PROVIDER_ORDER[:]
            defaults["order"] = order
            return defaults
        except Exception:
            pass
    return defaults


def save_ai_keys(keys: dict):
    with open(AI_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=2)
