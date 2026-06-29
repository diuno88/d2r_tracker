"""
Traderie 가격 조회
API URL로 매물 목록 조회 후 최저/최고가 계산
"""
import requests
from typing import Optional

try:
    import cloudscraper as _cloudscraper
except ImportError:
    _cloudscraper = None

# 룬 가치 테이블 (price-calculator.js에서 포팅)
RUNE_VALUES = {
    'Jah': 8000, 'Ber': 7000, 'Sur': 3000, 'Zod': 3000,
    'Lo': 2000, 'Cham': 2000, 'Ohm': 1500, 'Vex': 800,
    'Gul': 400, 'Ist': 200, 'Mal': 100, 'Um': 50,
    'Pul': 25, 'Lem': 12, 'Ko': 6, 'Fal': 3,
    'Lum': 2, 'Io': 1.5, 'Hel': 1, 'Dol': 0.8,
    'Shael': 0.6, 'Sol': 0.4, 'Amn': 0.3, 'Thul': 0.2,
    'Ort': 0.15, 'Ral': 0.12, 'Tal': 0.1, 'Ith': 0.08,
    'Eth': 0.06, 'Nef': 0.04, 'Tir': 0.02, 'Eld': 0.01, 'El': 0.005,
    # 한국어 룬명
    '자': 8000, '베르': 7000, '수르': 3000, '조드': 3000,
    '로': 2000, '참': 2000, '오움': 1500, '벡스': 800,
    '굴': 400, '이스트': 200, '말': 100, '우움': 50,
    '풀': 25, '렘': 12, '코': 6, '팔': 3,
    '룸': 2, '이오': 1.5, '헬': 1, '돌': 0.8,
    '샤엘': 0.6, '솔': 0.4, '앰': 0.3, '주울': 0.2,
    '오르트': 0.15, '랄': 0.12, '탈': 0.1, '아이드': 0.08,
    '에드': 0.06, '네프': 0.04, '티르': 0.02, '엘드': 0.01, '엘': 0.005,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://traderie.com/",
}


def parse_price_text(price_text: str) -> float:
    """
    가격 텍스트를 룬 가치로 변환
    예: "Jah Rune x2" → 16000, "Ist x3" → 600
    """
    if not price_text:
        return 0.0

    import re
    quantity = 1
    qty_match = re.search(r'[x×]\s*(\d+)|\b(\d+)\s*[x×]', price_text, re.IGNORECASE)
    if qty_match:
        quantity = int(qty_match.group(1) or qty_match.group(2)) or 1

    for rune_name, rune_val in RUNE_VALUES.items():
        if rune_name.lower() in price_text.lower():
            return rune_val * quantity

    return 0.0


def calculate_listing_value(price_texts) -> float:
    """
    하나의 매물 가격 목록에서 총 가치 계산
    price_texts: str 또는 List[str]
    """
    if isinstance(price_texts, str):
        return parse_price_text(price_texts)

    if isinstance(price_texts, list):
        total = 0.0
        for pt in price_texts:
            if isinstance(pt, str):
                total += parse_price_text(pt)
            elif isinstance(pt, list):
                total += sum(parse_price_text(p) for p in pt)
        return total

    return 0.0


def value_to_ist_text(value: float) -> str:
    """가치 → Ist 단위 표시"""
    if value <= 0:
        return "N/A"
    IST_VALUE = 200
    ist = value / IST_VALUE
    return f"Ist {ist:.2f}"


def value_to_rune_text(value: float) -> str:
    """가치 → 최상위 룬 표시"""
    if value <= 0:
        return "N/A"
    sorted_runes = sorted(
        [(k, v) for k, v in RUNE_VALUES.items() if len(k) <= 6],
        key=lambda x: -x[1]
    )
    for rune_name, rune_val in sorted_runes:
        if value >= rune_val:
            qty = int(value / rune_val)
            return f"{rune_name} x{qty}" if qty > 1 else rune_name
    return "N/A"


def _rune_short_name(name: str) -> str:
    """'Jah Rune' → 'Jah',  '이스트 룬' → '이스트'"""
    return name.replace(' Rune', '').replace(' rune', '').replace(' 룬', '').strip()


def _calc_listing_value_and_text(prices: list) -> tuple[float, str]:
    """
    Traderie API prices 배열에서 매물 가치 + 실제 표시 텍스트 반환.
    group 내 여러 prices는 AND(합산), group 간은 OR(최솟값).
    반환: (value, 가장_저렴한_그룹의_텍스트)
    """
    if not prices:
        return 0.0, "N/A"

    groups_val: dict[int, float] = {}
    groups_txt: dict[int, list] = {}
    for price in prices:
        g   = price.get('group', 0) or 0
        name = price.get('name', '') or ''
        qty  = int(price.get('quantity', 1) or 1)
        val  = parse_price_text(name) * qty
        short = _rune_short_name(name)
        txt   = f"{short} x{qty}" if qty > 1 else short
        groups_val[g]  = groups_val.get(g, 0.0) + val
        groups_txt.setdefault(g, []).append(txt)

    active = [(g, v) for g, v in groups_val.items() if v > 0]
    if not active:
        return 0.0, "N/A"

    best_g, best_v = min(active, key=lambda x: x[1])
    return best_v, ' + '.join(groups_txt[best_g])


def _calc_listing_value_from_prices(prices: list) -> float:
    """가치만 반환 (하위 호환용)"""
    v, _ = _calc_listing_value_and_text(prices)
    return v


def _listing_date(listing: dict):
    """매물의 날짜 반환 (없으면 None)"""
    from datetime import date as _date
    raw = listing.get('listingDate') or listing.get('createdAt') or ''
    if not raw:
        return None
    try:
        return _date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _entries_from_listings(listings: list) -> list:
    """active 매물에서 (value, text) 추출"""
    result = []
    for listing in listings:
        if not listing.get('active', True):
            continue
        v, txt = _calc_listing_value_and_text(listing.get('prices', []))
        if v > 0:
            result.append((v, txt))
    return result


def _make_stats(entries: list, total_count: int) -> dict:
    if not entries:
        return {
            'success': True, 'count': 0,
            'min_value': 0, 'max_value': 0,
            'min_text': 'N/A', 'max_text': 'N/A',
            'min_ist': 'N/A', 'max_ist': 'N/A',
        }
    min_val, min_text = min(entries, key=lambda x: x[0])
    max_val, max_text = max(entries, key=lambda x: x[0])
    return {
        'success': True, 'count': len(entries),
        'min_value': min_val, 'max_value': max_val,
        'min_text': min_text, 'max_text': max_text,
        'min_ist': value_to_ist_text(min_val),
        'max_ist': value_to_ist_text(max_val),
    }


def fetch_price_stats(api_url: str,
                      season_start: Optional[str] = None,
                      season_end: Optional[str] = None,
                      current_season: bool = False,
                      timeout: int = 12) -> dict:
    """
    Traderie API URL로 가격 통계 조회.

    current_season=True (진행 중인 시즌):
      1) 어제~오늘 매물만 집계
      2) 결과 없으면 날짜 최신순 상위 10개로 집계

    current_season=False (과거 시즌 / 전체):
      season_start~season_end 범위 매물만 포함 (None이면 무제한)
    """
    from datetime import date as _date, timedelta

    try:
        if _cloudscraper is not None:
            scraper = _cloudscraper.create_scraper()
            resp = scraper.get(api_url, timeout=timeout)
        else:
            resp = requests.get(api_url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        listings = data.get('listings', [])
        if not listings:
            return {'success': True, 'count': 0,
                    'min_value': 0, 'max_value': 0,
                    'min_text': 'N/A', 'max_text': 'N/A',
                    'min_ist': 'N/A', 'max_ist': 'N/A'}

        active = [l for l in listings if l.get('active', True)]

        if current_season:
            # 1단계: 어제 이후 매물
            yesterday = _date.today() - timedelta(days=1)
            recent = [l for l in active
                      if (d := _listing_date(l)) is not None and d >= yesterday]
            entries = _entries_from_listings(recent)

            if entries:
                return _make_stats(entries, len(active))

            # 폴백: 날짜 최신순 상위 10개
            dated   = sorted([(l, _listing_date(l)) for l in active if _listing_date(l)],
                              key=lambda x: x[1], reverse=True)
            undated = [l for l in active if _listing_date(l) is None]
            top10   = [l for l, _ in dated[:10]]
            if len(top10) < 10:
                top10 += undated[:10 - len(top10)]
            entries = _entries_from_listings(top10)
            return _make_stats(entries, len(active))

        else:
            # 과거 시즌 / 전체: 날짜 범위 필터
            s_start = _date.fromisoformat(season_start) if season_start else None
            s_end   = _date.fromisoformat(season_end)   if season_end   else None

            def _in_range(listing):
                d = _listing_date(listing)
                if d is None:
                    # 날짜 필터 활성 시 날짜 확인 불가 매물 제외
                    return not (s_start or s_end)
                if s_start and d < s_start:
                    return False
                if s_end   and d > s_end:
                    return False
                return True

            filtered = [l for l in active if _in_range(l)]
            entries  = _entries_from_listings(filtered)
            return _make_stats(entries, len(active))

    except Exception as e:
        return {'success': False, 'error': f'가격 조회 실패: {str(e)}'}
