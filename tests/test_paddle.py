"""
PaddleOCR 기반 sampleimg 테스트
결과: C:\D2R_ITEMSCROLL\test\paddle_YYYYMMDD_HHMMSS.txt

실행:
    conda run -n d2r-tracker python tracker/tests/test_paddle.py
"""
import sys
import os
from pathlib import Path
from datetime import datetime

# tracker/ 루트를 sys.path에 추가 (tests/ 기준 한 단계 위)
_HERE    = Path(__file__).parent
_TRACKER = _HERE.parent
if str(_TRACKER) not in sys.path:
    sys.path.insert(0, str(_TRACKER))

from PIL import Image as PILImage
from config import load_config
from core.capture import detect_rarity_from_image, save_temp_image
from ocr.paddle_ocr_bridge import PaddleOCRBridge
from item.item_parser import ItemParser


SAMPLEIMG_DIR = _TRACKER / "sampleimg"
TEST_OUT_DIR  = _TRACKER.parent / "test"
EXTENSIONS    = {".jpg", ".jpeg", ".png", ".bmp"}


def run_test():
    TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = TEST_OUT_DIR / f"paddle_{timestamp}.txt"

    images = sorted(
        p for p in SAMPLEIMG_DIR.iterdir()
        if p.suffix.lower() in EXTENSIONS
    )

    if not images:
        print(f"[TEST] sampleimg 폴더에 이미지 없음: {SAMPLEIMG_DIR}")
        return

    config = load_config()
    bridge = PaddleOCRBridge()
    parser = ItemParser()

    print("[TEST] PaddleOCR 초기화 중... (첫 실행 시 모델 다운로드)")
    bridge.init_ocr()
    print(f"[TEST] 이미지 {len(images)}개 처리 시작")
    print(f"[TEST] 결과 파일: {out_path}\n")

    lines_out = [
        f"D2R Tracker — PaddleOCR 테스트  {timestamp}",
        "-" * 100,
        "이미지 파일명 | 추출 이름 | 추출 옵션 | 트레더리 URL (실제) | 트레더리 URL (API)",
        "-" * 100,
    ]

    for idx, img_path in enumerate(images, 1):
        print(f"[{idx:02d}/{len(images)}] {img_path.name} 처리 중...")

        row = {
            "file":    img_path.name,
            "name":    "N/A",
            "options": "N/A",
            "url":     "N/A",
            "api_url": "N/A",
            "error":   "",
        }

        try:
            img = PILImage.open(img_path).convert("RGB")

            rarity = detect_rarity_from_image(img)
            print(f"       rarity: {rarity}")

            tmp_path = save_temp_image(img)
            try:
                ocr_result = bridge.run_ocr(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            if not ocr_result.get("success"):
                row["error"] = f"OCR 실패: {ocr_result.get('error', '')}"
                print(f"       [오류] {row['error']}")
            else:
                ocr_lines = ocr_result.get("lines", [])
                print(f"       OCR 라인 {len(ocr_lines)}개")
                for ln in ocr_lines[:6]:
                    print(f"         {ln}")
                if len(ocr_lines) > 6:
                    print(f"         ... ({len(ocr_lines) - 6}개 더)")

                parse_result = parser.parse(ocr_lines, rarity, config)

                if parse_result.get("success"):
                    row["name"]    = parse_result.get("item_name", "N/A")
                    row["url"]     = parse_result.get("traderie_url", "N/A")
                    row["api_url"] = parse_result.get("api_url", "N/A")
                    _, opt_lines   = parser._split_at_required_level(ocr_lines)
                    row["options"] = " / ".join(opt_lines[:5]) if opt_lines else "-"
                    print(f"       이름: {row['name']}")
                    print(f"       URL:  {row['url']}")
                else:
                    row["name"]  = parse_result.get("item_name", "N/A")
                    row["error"] = parse_result.get("error", "파싱 실패")
                    print(f"       [파싱 오류] {row['error']}")

        except Exception as e:
            import traceback
            row["error"] = str(e)
            print(f"       [예외] {e}")
            traceback.print_exc()

        status = f" ※{row['error']}" if row["error"] else ""
        lines_out.append(
            f"{row['file']} | {row['name']} | {row['options']} | "
            f"{row['url']} | {row['api_url']}{status}"
        )
        print()

    lines_out.append("-" * 100)
    lines_out.append(f"완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out) + "\n")

    print(f"[TEST] 결과 저장 완료: {out_path}")


if __name__ == "__main__":
    run_test()
