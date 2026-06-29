"""
PaddleOCR Bridge - D2R 아이템 이미지 로컬 분석
첫 실행 시 패키지 자동 설치 + 모델 자동 다운로드 (~300MB)
"""
from pathlib import Path
from typing import Optional, Callable

_PADDLE_PACKAGES = [
    "paddlepaddle==2.6.2",
    "imgaug",
    "paddleocr==2.7.3",
]


def _ensure_paddle_installed(notify_fn=None) -> bool:
    """paddleocr import 불가 시 pip으로 자동 설치 후 sys.path 갱신. 성공하면 True."""
    try:
        import paddleocr  # noqa
        return True
    except ImportError:
        pass

    import sys, subprocess, site
    if notify_fn:
        notify_fn("PaddleOCR 패키지 설치 중... (최초 1회, 수 분 소요)")
    try:
        CREATE_NO_WINDOW = 0x08000000
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + _PADDLE_PACKAGES,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        if notify_fn:
            notify_fn(f"PaddleOCR 패키지 설치 실패: {e}")
        return False

    # 설치 후 sys.path에 새 site-packages 경로 추가 (재시작 없이 import 가능하게)
    for sp in site.getsitepackages():
        if sp not in sys.path:
            sys.path.insert(0, sp)
    try:
        sp_user = site.getusersitepackages()
        if sp_user not in sys.path:
            sys.path.insert(0, sp_user)
    except Exception:
        pass

    try:
        import paddleocr  # noqa
        if notify_fn:
            notify_fn("PaddleOCR 패키지 설치 완료")
        return True
    except ImportError as e:
        if notify_fn:
            notify_fn(f"PaddleOCR 설치 후 import 실패: {e}")
        return False


def _apply_numpy_compat():
    """NumPy 2.0에서 제거된 np.sctypes를 PaddlePaddle 호환용으로 복원"""
    import numpy as _np
    if not hasattr(_np, 'sctypes'):
        _np.sctypes = {
            'int': [_np.int8, _np.int16, _np.int32, _np.int64],
            'uint': [_np.uint8, _np.uint16, _np.uint32, _np.uint64],
            'float': [_np.float16, _np.float32, _np.float64],
            'complex': [_np.complex64, _np.complex128],
            'others': [bool, object, bytes, str, _np.void],
        }


def is_paddle_installed() -> bool:
    _apply_numpy_compat()
    try:
        import paddleocr  # noqa
        return True
    except Exception:
        return False


def _get_bundled_models_dir() -> Optional[Path]:
    """PyInstaller 번들 내 paddle_models 폴더 경로 반환. 없으면 None."""
    import sys
    if getattr(sys, 'frozen', False):
        p = Path(sys._MEIPASS) / 'paddle_models'
        if p.exists():
            return p
    # 개발 환경: 프로젝트 루트의 tracker/models/paddleocr
    p = Path(__file__).parent.parent / 'models' / 'paddleocr'
    if p.exists():
        return p
    return None


def _copy_bundled_models_if_needed(notify_fn=None) -> bool:
    """번들 모델을 ~/.paddleocr/whl/ 로 복사 (없을 때만). 성공하면 True."""
    if is_model_ready():
        return True
    src = _get_bundled_models_dir()
    if src is None:
        return False

    import shutil
    dst = Path.home() / '.paddleocr' / 'whl'
    if notify_fn:
        notify_fn("PaddleOCR 모델 복사 중...")
    try:
        shutil.copytree(str(src / 'whl'), str(dst), dirs_exist_ok=True)
        if notify_fn:
            notify_fn("PaddleOCR 모델 복사 완료")
        return True
    except Exception as e:
        if notify_fn:
            notify_fn(f"모델 복사 실패: {e}")
        return False


def is_model_ready() -> bool:
    """PaddleOCR 모델 파일이 ~/.paddleocr/whl/ 에 존재하는지 확인"""
    whl = Path.home() / '.paddleocr' / 'whl'
    if not whl.exists():
        return False
    det = list(whl.glob('**/det/**/*.pdmodel'))
    rec = list(whl.glob('**/rec/**/*.pdmodel'))
    return bool(det and rec)


class PaddleOCRBridge:
    """
    PaddleOCR 로컬 OCR 브릿지
    AIVisionBridge와 동일한 run_ocr() 인터페이스 제공
    """

    def __init__(self):
        self._ocr = None
        self._paddle_ver = (3, 0)
        self._status_callback: Optional[Callable] = None

    def set_status_callback(self, fn: Callable):
        self._status_callback = fn

    def is_ready(self) -> bool:
        # ~/.paddleocr/whl/ 에 있거나, 번들 모델이 있으면 준비된 것으로 간주
        return is_model_ready() or _get_bundled_models_dir() is not None

    def init_ocr(self):
        """PaddleOCR 초기화 — 패키지/모델 없으면 자동 설치·다운로드"""
        if self._ocr is not None:
            return
        import logging
        import warnings
        warnings.filterwarnings('ignore')
        for _name in ('ppocr', 'paddle', 'paddleocr', 'paddlex', 'root'):
            logging.getLogger(_name).setLevel(logging.ERROR)

        _apply_numpy_compat()

        # 패키지 없으면 자동 설치
        if not is_paddle_installed():
            ok = _ensure_paddle_installed(notify_fn=self._notify)
            if not ok:
                raise RuntimeError('PaddleOCR 패키지 설치에 실패했습니다. 수동으로 설치하세요:\n'
                                   'pip install paddlepaddle==2.6.2 paddleocr==2.7.3')

        try:
            from paddleocr import PaddleOCR
            import paddleocr as _poc
        except Exception as _e:
            raise RuntimeError(f'PaddleOCR 로드 실패: {_e}')
        self._paddle_ver = tuple(int(x) for x in _poc.__version__.split('.')[:2])

        # 번들 모델을 ~/.paddleocr/whl/ 로 복사 (없을 때만)
        _copy_bundled_models_if_needed(notify_fn=self._notify)

        self._notify('PaddleOCR 모델 로딩 중...')

        try:
            if self._paddle_ver >= (3, 0):
                # 3.x API: use_angle_cls / show_log 파라미터 없음
                self._ocr = PaddleOCR(lang='korean')
            else:
                # 2.x API
                self._ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang='korean',
                    show_log=False,
                )
        except Exception as e:
            self._ocr = None
            raise RuntimeError(
                f'PaddleOCR 초기화 실패: {e}\n'
                f'(paddleocr {".".join(str(v) for v in self._paddle_ver)})\n'
                '해결: conda activate d2r-tracker 후\n'
                'pip install paddlepaddle==2.6.2 paddleocr==2.7.3'
            )
        self._notify('PaddleOCR 준비 완료')

    @staticmethod
    def _merge_to_lines(raw_items: list, row_tol: int = None) -> list:
        """
        단어 단위 bbox 목록을 y좌표 기준으로 같은 줄끼리 합쳐서 라인 단위로 반환.
        raw_items: [(text, bbox), ...] — bbox는 4점 폴리곤
        row_tol: None이면 bbox 높이 중앙값의 40%로 자동 계산
        Returns: [(merged_text, merged_bbox), ...]
          merged_bbox = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] (라인 전체를 감싸는 직사각형)
        """
        if not raw_items:
            return []

        def bbox_cy(bbox):
            try:
                ys = [p[1] for p in bbox]
                return (min(ys) + max(ys)) / 2
            except Exception:
                return 0

        def bbox_h(bbox):
            try:
                ys = [p[1] for p in bbox]
                return max(ys) - min(ys)
            except Exception:
                return 0

        # row_tol을 bbox 높이 중앙값 기준으로 자동 결정
        if row_tol is None:
            heights = sorted([bbox_h(bb) for _, bb in raw_items if bb])
            if heights:
                median_h = heights[len(heights) // 2]
                row_tol = max(8, int(median_h * 0.6))
            else:
                row_tol = 12

        # y중심 기준으로 정렬
        sorted_items = sorted(raw_items, key=lambda it: (bbox_cy(it[1]), it[1][0][0] if it[1] else 0))

        groups = []   # [[(text, bbox), ...], ...]
        cur_group = [sorted_items[0]]
        cur_cy = bbox_cy(sorted_items[0][1])

        for item in sorted_items[1:]:
            cy = bbox_cy(item[1])
            if abs(cy - cur_cy) <= row_tol:
                cur_group.append(item)
            else:
                groups.append(cur_group)
                cur_group = [item]
                cur_cy = cy
        groups.append(cur_group)

        merged = []
        for group in groups:
            # x 기준으로 정렬
            group.sort(key=lambda it: it[1][0][0] if it[1] else 0)

            # 같은 y행이라도 x간격이 너무 크면 별도 라인으로 분리
            # 허용 gap = row_tol * 4 (글자 높이 기준)
            max_x_gap = row_tol * 4
            sub_groups = []
            cur_sub = [group[0]]
            for item in group[1:]:
                prev_bb = cur_sub[-1][1]
                cur_bb = item[1]
                try:
                    prev_x1 = max(p[0] for p in prev_bb)
                    cur_x0 = min(p[0] for p in cur_bb)
                    gap = cur_x0 - prev_x1
                except Exception:
                    gap = 0
                if gap > max_x_gap:
                    sub_groups.append(cur_sub)
                    cur_sub = [item]
                else:
                    cur_sub.append(item)
            sub_groups.append(cur_sub)

            for sub in sub_groups:
                text = ' '.join(t for t, _ in sub)
                all_xs = [p[0] for _, bb in sub for p in bb]
                all_ys = [p[1] for _, bb in sub for p in bb]
                x0, y0, x1, y1 = min(all_xs), min(all_ys), max(all_xs), max(all_ys)
                bbox = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                merged.append((text, bbox))

        return merged

    def run_ocr(self, image_path: str, lang: str = 'kor+eng', scale: float = 1.0) -> dict:
        """
        이미지에서 텍스트 추출
        scale: 1.0이면 원본, 2.0이면 2배 확대 후 OCR (작은 글자 인식률 향상)

        Returns:
            {
                'success': bool,
                'lines': List[str],
                'rawText': str,
                'linesWithBbox': [],
                'provider': 'paddle',
                'error': str   # 실패 시
            }
        """
        import tempfile as _tf
        scaled_path = None
        try:
            self.init_ocr()
            self._notify('PaddleOCR 분석 중...')

            # scale > 1.0이면 이미지 확대 후 임시파일로 OCR
            if scale > 1.0:
                from PIL import Image as _PILImage
                _img = _PILImage.open(image_path)
                new_w = int(_img.width * scale)
                new_h = int(_img.height * scale)
                _img = _img.resize((new_w, new_h), _PILImage.LANCZOS)
                fd, scaled_path = _tf.mkstemp(suffix='.png')
                import os as _os
                _os.close(fd)
                _img.save(scaled_path, 'PNG')
                ocr_target = scaled_path
            else:
                ocr_target = image_path

            raw_items = []  # [(text, bbox)] — 단어 단위 원본

            if self._paddle_ver >= (3, 0):
                results = self._ocr.ocr(ocr_target)
                for page in results:
                    for item in page:
                        text = item.get('transcription', '') if isinstance(item, dict) else ''
                        score = item.get('score', 1.0) if isinstance(item, dict) else 1.0
                        bbox = item.get('points', None) if isinstance(item, dict) else None
                        if not text and hasattr(item, '__iter__'):
                            try:
                                bbox, (text, score) = item[0], item[1]
                            except Exception:
                                continue
                        if str(text).strip() and float(score) > 0.5:
                            raw_items.append((str(text).strip(), bbox))
            else:
                result = self._ocr.ocr(ocr_target, cls=True)
                if result and result[0]:
                    for item in result[0]:
                        bbox = item[0]
                        text = item[1][0]
                        conf = item[1][1]
                        if text.strip() and conf > 0.5:
                            raw_items.append((text.strip(), bbox))

            # scale > 1이면 bbox 좌표를 원본 크기로 역변환
            if scale > 1.0:
                inv = 1.0 / scale
                raw_items = [
                    (t, [[p[0] * inv, p[1] * inv] for p in bb] if bb else bb)
                    for t, bb in raw_items
                ]

            # 단어 bbox → 라인 단위로 병합
            lines_with_bbox = self._merge_to_lines(raw_items)
            lines = [text for text, _ in lines_with_bbox]

            raw = '\n'.join(lines)
            self._notify(f'PaddleOCR 완료 — {len(lines)}줄')
            for i, line in enumerate(lines):
                print(f'[PaddleOCR] [{i}] {line}')

            return {
                'success': True,
                'lines': lines,
                'rawText': raw,
                'linesWithBbox': lines_with_bbox,
                'provider': 'paddle',
            }

        except Exception as e:
            msg = f'PaddleOCR 오류: {e}'
            self._notify(msg)
            return {
                'success': False,
                'lines': [],
                'rawText': '',
                'linesWithBbox': [],
                'provider': 'paddle',
                'error': msg,
            }
        finally:
            if scaled_path:
                try:
                    import os as _os2
                    _os2.unlink(scaled_path)
                except Exception:
                    pass

    def _notify(self, msg: str):
        print(f'[PaddleOCR] {msg}')
        if self._status_callback:
            try:
                self._status_callback(msg)
            except Exception:
                pass
