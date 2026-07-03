"""
Item Matcher
아이템명/옵션을 Traderie DB 키에 매핑
데이터: frozen → _internal/backend_data, 개발 → tracker/data
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Dict, List

from config import BACKEND_DATA_PATH

_DATA_DIR = Path(BACKEND_DATA_PATH)

CHOSUNG  = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
JUNGSUNG = ['ㅏ','ㅐ','ㅑ','ㅒ','ㅓ','ㅔ','ㅕ','ㅖ','ㅗ','ㅘ','ㅙ','ㅚ','ㅛ','ㅜ','ㅝ','ㅞ','ㅟ','ㅠ','ㅡ','ㅢ','ㅣ']
JONGSUNG = ['','ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ','ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']

FUZZY_THRESHOLD_ITEM   = 0.55
FUZZY_THRESHOLD_UNIQUE = 0.80
FUZZY_THRESHOLD_OPTION = 0.80
FUZZY_THRESHOLD_SAMEKOR = 0.75


def _load_json(filename: str) -> list:
    path = _DATA_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    print(f'[ItemMatcher] 파일 없음: {path}')
    return []


def _load_json_dict(filename: str) -> dict:
    path = _DATA_DIR / filename
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    print(f'[ItemMatcher] 파일 없음: {path}')
    return {}


def _build_lookup(items: list) -> dict:
    """korName/name → item dict 룩업 테이블 생성
    affix_kor이 분리된 항목(setItemList)은 clean korName만 키로 사용.
    """
    lookup = {}
    for item in items:
        kor = item.get('korName', '')
        if kor:
            lookup[kor.lower()] = item
        if item.get('name'):
            lookup[item['name'].lower()] = item
    return lookup


CHARM_KEYWORD_MAP = {
    '거대부적': 'grand_charm',
    '거대부작': 'grand_charm',
    '큰부적':   'large_charm',
    '큰부작':   'large_charm',
    '작은부적': 'small_charm',
    '작은부작': 'small_charm',
    # 영문 게임 클라이언트 / Groq OCR 영문 표기
    'grandcharm': 'grand_charm',
    'largecharm': 'large_charm',
    'smallcharm': 'small_charm',
    # 한글 음차 OCR 오인식 ("Large Charm" → "라지 차암")
    '그랜드차암': 'grand_charm',
    '그랜드참':   'grand_charm',
    '라지차암':   'large_charm',
    '라지참':     'large_charm',
    '스몰차암':   'small_charm',
    '스몰참':     'small_charm',
}


_CIRCLET_CTGGROUPS = {'tiara', 'circlet', 'coronet', 'diadem'}

_CTG_TO_AFFIX_KEYS: Dict[str, List[str]] = {
    'amulet':    ['amulet_prefixes',  'amulet_suffixes'],
    'glove':     ['gloves_prefixes',  'gloves_suffixes'],
    'boot':      ['boots_prefixes',   'boots_suffixes'],
    'jewel':     ['jewel_prefixes',   'jewel_suffixes'],
}
_WEAPON_CTGS = {
    'sword', 'axe', 'mace', 'hammer', 'club', 'scepter',
    'staff', 'wand', 'orb', 'bow', 'javelin', 'spear',
    'polearm', 'knife', 'claw', 'h2h', 'pelt', 'voodoo_head',
}

# d2r_affixes_detailed.json에 해당 슬롯 전용 prefix/suffix 데이터가 없는 ctg.
# 매칭 후보를 못 찾을 때 전체 카테고리를 섞어 쓰면 엉뚱한(다른 슬롯) 어픽스와
# 오매칭될 수 있으므로, 이 슬롯들은 A경로(어픽스 DB 매칭)를 포기하고
# B경로(OCR 옵션 직접 매칭)로 넘어가도록 빈 목록을 반환한다.
_CTG_NO_AFFIX_DATA = {'ring', 'belt', 'shield', 'armor'}


class ItemMatcher:
    def __init__(self):
        unique_items  = _load_json('uniqueResult.json')
        set_items     = _load_json('setItemList.json')
        runword_items = _load_json('runWordsResult.json')
        base_items    = _load_json('baseItemList.json')
        self.unique_items  = _build_lookup(unique_items)
        self.set_items     = _build_lookup(set_items)
        self.runword_items = _build_lookup(runword_items)
        self.base_items    = _build_lookup(base_items)

        # affix_kor 필드가 있는 아이템: 동일 korName의 복수 variant → OCR로 판별
        # 예: 무지개자락 8종(affix_kor=라업주얼/라다주얼/...) → {"무지개자락": [item×8]}
        self.unique_affix_lookup: Dict[str, list] = {}
        for item in unique_items:
            if item.get('affix_kor'):
                key = self._normalize(item.get('korName', ''))
                if key:
                    self.unique_affix_lookup.setdefault(key, []).append(item)

        self.option_combo  = _load_json('optionCombo.json')
        self.synonym_dict  = _load_json_dict('synonym_dict.json')
        self.kor_end_affix = _load_json('kor_end_affix.json')
        self.affixes       = _load_json_dict('d2r_affixes_detailed.json')

        charm_list = _load_json('charm.json')
        self.charm_items: Dict[str, dict] = {}
        for c in charm_list:
            name_lower = c.get('name', '').lower()
            if 'grand' in name_lower:
                self.charm_items['grand_charm'] = c
            elif 'large' in name_lower:
                self.charm_items['large_charm'] = c
            elif 'small' in name_lower:
                self.charm_items['small_charm'] = c

    # ──────────────────────────────────────────
    # 텍스트 정규화 / 유사도
    # ──────────────────────────────────────────

    # DB korName vs 게임 내 표기 불일치 교정 (정규화 전 적용)
    _NAME_ALIASES = {
        '트래그울': '트랑울',
        '트레그울': '트랑울',
        '팔뚝': '발톱',       # Trang-Oul's Claws: 게임="팔뚝", DB="발톱"
    }

    @classmethod
    def _normalize(cls, text: str) -> str:
        """특수문자 제거, 소문자화 + 아이템명 별칭 교정"""
        for alias, canonical in cls._NAME_ALIASES.items():
            text = text.replace(alias, canonical)
        return re.sub(r'[^가-힣ㄱ-㆏a-zA-Z0-9]', '', text).lower()

    @staticmethod
    def _normalize_option(text: str) -> str:
        """공백 제거, 소문자화 (옵션명 비교용)"""
        return re.sub(r'\s', '', text).lower()

    @staticmethod
    def _jamo(text: str) -> list:
        result = []
        for ch in text:
            if '가' <= ch <= '힣':
                code = ord(ch) - ord('가')
                result.append(CHOSUNG[code // (21 * 28)])
                result.append(JUNGSUNG[(code % (21 * 28)) // 28])
                jong = JONGSUNG[code % 28]
                if jong:
                    result.append(jong)
            else:
                result.append(ch)
        return result

    def _similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _combined_similarity(self, a: str, b: str) -> float:
        """한글 포함 시 자모 분해(80%) + 원문(20%) 가중 평균"""
        if not a or not b:
            return 0.0
        has_kor = any('가' <= c <= '힣' for c in a + b)
        if has_kor:
            jamo_score = SequenceMatcher(None, self._jamo(a), self._jamo(b)).ratio()
            return jamo_score * 0.8 + self._similarity(a, b) * 0.2
        return self._similarity(a, b)

    # ──────────────────────────────────────────
    # 아이템 이름 매칭
    # ──────────────────────────────────────────

    @staticmethod
    def _strip_affixes(name: str) -> str:
        stripped = re.sub(r'^(?:\S+의\s+)?(?:\S+한\s+)+', '', name).strip()
        if not stripped:
            stripped = name
        stripped = re.sub(r'^(?:\S+의\s+)+', '', stripped).strip()
        return stripped if stripped else name

    def _substring_best_match(self, normalized: str, lookup: dict,
                               min_ratio: float = 0.5) -> Optional[Dict]:
        """DB 키가 normalized에 포함될 때 매칭. ratio < min_ratio 이면 무시."""
        best_ratio = 0.0
        best_item = None
        for key, item in lookup.items():
            key_n = self._normalize(key)
            if len(key_n) < 2:
                continue
            if key_n in normalized:
                ratio = len(key_n) / len(normalized)
                if ratio >= min_ratio and ratio > best_ratio:
                    best_ratio = ratio
                    best_item = item
        if best_item:
            print(f'[ItemMatcher] 서브스트링 베스트 매치: ratio={best_ratio:.2f}')
        return best_item

    # 무지개자락 이벤트 코드 판별 테이블 (레벨업 vs 피격/사망)
    _FACET_EVENT_CODES = [
        (['레벨 상승', '레벨상승'], '업'),
        (['피격', '사망', '죽음'], '다'),
    ]

    def _find_by_affix_kor(self, normalized: str,
                            all_text_lines: List[str]) -> Optional[Dict]:
        """affix_kor 복수 variant 아이템: korName 매칭 후 OCR로 element/event 판별.
        element 판별: description_filtered property_kor 유사도 비교
          (OCR '별개피해'는 '번개피해'와 유사도가 가장 높음 → 교정 불필요)
        event 판별: OCR 키워드 검색 ('레벨 상승' → 업, '사망/피격' → 다)"""
        best_sim = 0.0
        best_key = None
        for base_norm in self.unique_affix_lookup:
            sim = self._combined_similarity(normalized, base_norm)
            if sim >= 0.75 and sim > best_sim:
                best_sim = sim
                best_key = base_norm

        if best_key is None:
            return None

        candidates = self.unique_affix_lookup[best_key]
        if len(candidates) == 1:
            result = dict(candidates[0])
            result['_resolved_rarity'] = 'unique'
            return result

        # 1단계: property_kor 유사도로 element 판별
        # 동일 element의 업/다 variant는 property_kor이 같아 점수도 동일
        option_lines = all_text_lines[1:] if len(all_text_lines) > 1 else all_text_lines
        scored = []
        for item in candidates:
            prop_kors = [self._normalize(p.get('property_kor', ''))
                         for p in item.get('description_filtered', [])
                         if p.get('property_kor')]
            score = 0.0
            for line in option_lines:
                ln = self._normalize(line)
                if not ln or not prop_kors:
                    continue
                best = max(self._combined_similarity(ln, pk) for pk in prop_kors)
                if best >= 0.5:
                    score += best
            scored.append((score, item))

        scored.sort(key=lambda x: -x[0])
        top_score = scored[0][0]
        # 동점 후보 = 동일 element, 업/다만 다른 것
        top_candidates = [item for s, item in scored if abs(s - top_score) < 0.01]

        # 2단계: event 판별 (레벨 상승 vs 사망/피격)
        ocr_full = ' '.join(all_text_lines).lower() if all_text_lines else ''
        detected_event = ''
        for keywords, code in self._FACET_EVENT_CODES:
            if any(k in ocr_full for k in keywords):
                detected_event = code
                break

        best_item = top_candidates[0]
        if detected_event:
            for item in top_candidates:
                if detected_event in item.get('affix_kor', ''):
                    best_item = item
                    break

        print(f'[ItemMatcher] affix_kor 판별: {best_item.get("korName")}'
              f'{best_item.get("affix_kor","")} '
              f'(score={top_score:.2f}, event={detected_event})')
        result = dict(best_item)
        result['_resolved_rarity'] = 'unique'
        return result

    def _detect_charm_type(self, raw_name: str) -> Optional[str]:
        """이름에서 부적 타입 감지. 공백 제거 후 키워드 검색."""
        compact = re.sub(r'\s', '', raw_name)
        for keyword, charm_type in CHARM_KEYWORD_MAP.items():
            if keyword in compact:
                return charm_type
        return None

    def _detect_charm_from_lines(self, lines: List[str]) -> Optional[str]:
        """OCR 줄 목록 전체에서 부적 타입 감지.
        - 각 줄 단독 검사
        - 인접 두 줄을 공백 없이 합쳐서 검사 (예: "작은" + "부적" 줄 분리 대응)
        """
        for line in lines:
            result = self._detect_charm_type(line)
            if result:
                return result
        # 인접 줄 쌍 합치기
        for i in range(len(lines) - 1):
            merged = re.sub(r'\s', '', lines[i]) + re.sub(r'\s', '', lines[i + 1])
            for keyword, charm_type in CHARM_KEYWORD_MAP.items():
                if keyword in merged:
                    return charm_type
        return None

    def _strip_charm_suffix(self, key_n: str) -> str:
        """정규화된 유니크 부적 이름에서 '거대부적/큰부적/작은부적' 등 종류 접미사 제거."""
        for keyword in CHARM_KEYWORD_MAP:
            suf = self._normalize(keyword)
            if suf and key_n.endswith(suf):
                return key_n[:-len(suf)]
        return key_n

    def _find_unique_charm_lenient(self, normalized: str) -> Optional[Dict]:
        """부적 옵션 3줄 이상 감지 시 사용하는 관대한 유니크 부적 매칭.
        OCR이 이름 뒷부분 단어를 통째로 누락한 경우(예: '파열' 탈락)에도
        접두사 일치로 구제한다. 검색 범위를 korName에 '부적'이 포함된
        유니크 부적으로 한정해 오매칭 위험을 낮춘다."""
        if len(normalized) < 4:
            return None
        best_item = None
        best_score = 0.0
        for key, item in self.unique_items.items():
            if '부적' not in key:
                continue
            key_n = self._normalize(key)
            base_n = self._strip_charm_suffix(key_n)
            if not base_n:
                continue
            if base_n.startswith(normalized) or normalized.startswith(base_n):
                shorter = min(len(base_n), len(normalized))
                longer = max(len(base_n), len(normalized))
                score = shorter / longer
            else:
                score = self._combined_similarity(normalized, base_n)
            if score > best_score:
                best_score = score
                best_item = item
        if best_score >= 0.5:
            return best_item
        return None

    def find_item_key(self, item_name: str, rarity: str,
                      all_text_lines: List[str] = None,
                      option_line_count: int = 0) -> Optional[Dict]:
        if not item_name:
            return None

        normalized = self._normalize(item_name)

        # OCR 전체 줄에서 부적 타입 감지 (줄 분리 오인식 포함)
        ocr_charm = self._detect_charm_from_lines(
            [item_name] + (all_text_lines or [])
        )

        # 부적 타입 + 옵션 3줄 이상 = 사실상 확정적 유니크 부적(일반/매직 부적은 옵션 1~2줄).
        # HSV 등급 오판정이나 이름 인식 손상(단어 누락 등)으로 일반 매칭이 실패해도
        # 관대한 매칭으로 유니크 DB에서 먼저 구제를 시도한다 (rarity 분기보다 우선).
        if ocr_charm and option_line_count >= 3:
            lenient = self._find_unique_charm_lenient(normalized)
            if lenient:
                lenient = dict(lenient)
                lenient['_resolved_rarity'] = 'unique'
                print(f'[ItemMatcher] 부적 옵션 {option_line_count}줄 → 관대 매칭(unique): "{normalized}"')
                return lenient

        # unique/set/base: affix_kor 복수 variant 먼저 확인 (무지개자락 8종 등)
        if rarity in ('unique', 'set', 'base'):
            prefix_match = self._find_by_affix_kor(normalized, all_text_lines or [item_name])
            if prefix_match:
                return prefix_match

            # 부적 타입 감지된 경우: unique_items에서 이름 있는 부적 우선 검색
            if ocr_charm:
                uniq = self._fuzzy_lookup(normalized, self.unique_items, threshold=0.70)
                if uniq:
                    uniq = dict(uniq)
                    uniq['_resolved_rarity'] = 'unique'
                    print(f'[ItemMatcher] 명칭 부적(unique) 매칭: "{normalized}"')
                    return uniq
                # 이름 없는 generic 부적
                if ocr_charm in self.charm_items:
                    result = dict(self.charm_items[ocr_charm])
                    result['_resolved_rarity'] = 'charm'
                    print(f'[ItemMatcher] generic 부적 감지 → {ocr_charm}')
                    return result

            best_item, best_score, best_rarity = self._best_match_across_dbs(
                normalized,
                [
                    (self.unique_items,  'unique', 0.75),
                    (self.runword_items, 'base',   0.75),
                    (self.set_items,     'set',    0.75),
                ]
            )
            if best_item:
                best_item = dict(best_item)
                best_item['_resolved_rarity'] = best_rarity
                print(f'[ItemMatcher] DB 교차 매칭 → rarity={best_rarity} score={best_score:.2f}')
                return best_item
            # unique/set DB 매칭 실패 → AI가 unique라고 해도 실제론 rare일 가능성
            # rare로 폴백하여 베이스 아이템 탐색 진행
            if rarity == 'unique':
                print(f'[ItemMatcher] unique DB 매칭 실패 → rare 폴백: "{normalized}"')
                rarity = 'rare'

        # rare/magic: 부적 감지 우선, 이후 base 아이템 탐색
        if rarity in ('rare', 'magic'):
            # 부적 감지: 이름 단독 + 전체 OCR 줄 스캔 (줄 분리 OCR 오류 대응)
            _charm_lines = [item_name] + (all_text_lines or [])
            charm_type = self._detect_charm_from_lines(_charm_lines)
            if charm_type:
                # 부적 타입 감지된 경우: unique_items에서 이름 있는 부적 우선 검색
                # (HSV가 unique를 rare/magic으로 오판할 수 있으므로 제네릭 확정 전에 먼저 확인)
                uniq = self._fuzzy_lookup(normalized, self.unique_items, threshold=0.70)
                if uniq:
                    uniq = dict(uniq)
                    uniq['_resolved_rarity'] = 'unique'
                    print(f'[ItemMatcher] 부적 감지 → 명칭 부적(unique) 매칭: "{normalized}"')
                    return uniq
                # 이름 없는 generic 부적
                if charm_type in self.charm_items:
                    charm = dict(self.charm_items[charm_type])
                    charm['_resolved_rarity'] = 'charm'
                    print(f'[ItemMatcher] 부적 감지 → generic {charm_type}: "{item_name}"')
                    return charm

            # affix_kor 복수 variant 우선 확인 (무지개자락 8종 등)
            prefix_match2 = self._find_by_affix_kor(normalized, all_text_lines or [item_name])
            if prefix_match2:
                return prefix_match2
            # 룬워드/유니크/세트 DB 체크 (HSV가 rare로 오판할 수 있음)
            rw = self._fuzzy_lookup(normalized, self.runword_items, threshold=0.75)
            if rw:
                rw = dict(rw)
                rw['_resolved_rarity'] = 'base'
                print(f'[ItemMatcher] rare→runword 재매칭: "{normalized}"')
                return rw
            best_item2, best_score2, best_rarity2 = self._best_match_across_dbs(
                normalized,
                [
                    (self.unique_items, 'unique', 0.75),
                    (self.set_items,    'set',    0.75),
                ]
            )
            if best_item2:
                best_item2 = dict(best_item2)
                best_item2['_resolved_rarity'] = best_rarity2
                print(f'[ItemMatcher] rare→{best_rarity2} 재매칭: "{normalized}"')
                return best_item2
            candidates = all_text_lines[:3] if all_text_lines else [item_name]
            base = self.find_base_item_from_lines(candidates)
            if base:
                base = dict(base)
                base['_resolved_rarity'] = 'base'
                return base

        # 폴백: base_items 퍼지
        result = self._fuzzy_lookup(normalized, self.base_items, threshold=0.65)
        if result:
            result = dict(result)
            result['_resolved_rarity'] = 'base'
            return result

        # 최종 폴백: unique/runword/set 낮은 threshold로 재시도
        best_item, best_score, best_rarity = self._best_match_across_dbs(
            normalized,
            [
                (self.unique_items,  'unique', 0.60),
                (self.runword_items, 'base',   0.60),
                (self.set_items,     'set',    0.60),
            ]
        )
        if best_item:
            best_item = dict(best_item)
            best_item['_resolved_rarity'] = best_rarity
            return best_item

        return None

    def _best_match_across_dbs(
        self,
        normalized: str,
        db_list: List[tuple]
    ) -> tuple:
        """
        여러 DB에서 동시에 검색해 가장 높은 유사도의 결과를 반환.
        db_list: [(lookup_dict, resolved_rarity, threshold), ...]
        Returns: (best_item, best_score, best_rarity)
        """
        best_item   = None
        best_score  = 0.0
        best_rarity = ''

        for lookup, resolved_rarity, threshold in db_list:
            # 정확 매치
            if normalized in lookup:
                item = lookup[normalized]
                print(f'[ItemMatcher] 정확 매치({resolved_rarity}): "{normalized}"')
                return item, 1.0, resolved_rarity

            # 서브스트링 매치
            item = self._substring_best_match(normalized, lookup)
            if item:
                score = 0.90
                if score > best_score:
                    best_score  = score
                    best_item   = item
                    best_rarity = resolved_rarity
                    print(f'[ItemMatcher] 서브스트링 매치({resolved_rarity}): "{normalized}"')
                continue

            # 퍼지 매치 (score 직접 계산)
            for key, item in lookup.items():
                key_n = self._normalize(key)
                if len(key_n) < 2:
                    continue
                if abs(len(normalized) - len(key_n)) > max(2, len(normalized) // 2):
                    continue
                score = self._combined_similarity(normalized, key_n)
                if score >= threshold and score > best_score:
                    best_score  = score
                    best_item   = item
                    best_rarity = resolved_rarity

        return best_item, best_score, best_rarity

    def _lookup_with_rarity(self, normalized: str, lookup: dict,
                             resolved_rarity: str, threshold: float) -> Optional[Dict]:
        item = None
        if normalized in lookup:
            item = lookup[normalized]
            print(f'[ItemMatcher] 정확 매치({resolved_rarity}): "{normalized}"')
        if not item:
            item = self._substring_best_match(normalized, lookup)
            if item:
                print(f'[ItemMatcher] 서브스트링 매치({resolved_rarity}): "{normalized}"')
        if not item:
            item = self._fuzzy_lookup(normalized, lookup, threshold=threshold)
            if item:
                print(f'[ItemMatcher] 퍼지 매치({resolved_rarity}): "{normalized}"')
        if item:
            item = dict(item)
            item['_resolved_rarity'] = resolved_rarity
        return item

    def find_base_item_from_lines(self, lines: List[str]) -> Optional[Dict]:
        # 부적 타입이 줄에 포함된 경우 여기서도 감지 (레어/매직 부적 대응)
        charm_type = self._detect_charm_from_lines(lines)
        if charm_type and charm_type in self.charm_items:
            print(f'[ItemMatcher] find_base_item_from_lines: 부적 감지 → {charm_type}')
            return self.charm_items[charm_type]

        best_ratio = 0.0
        best_item = None

        for line in lines[:3]:
            raw = line.rstrip('*').strip()
            if not raw:
                continue

            stripped = self._strip_affixes(raw)
            for candidate in dict.fromkeys([stripped, raw]):
                n = self._normalize(candidate)
                if len(n) < 2:
                    continue

                if n in self.base_items:
                    print(f'[ItemMatcher] 정확 매치: "{n}"')
                    return self.base_items[n]

                for key, item in self.base_items.items():
                    key_n = self._normalize(key)
                    if len(key_n) < 2:
                        continue
                    if key_n in n:
                        ratio = len(key_n) / len(n)
                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_item = item

                if not best_item:
                    result = self._fuzzy_lookup(n, self.base_items, threshold=0.65)
                    if result:
                        best_item = result
                        best_ratio = 0.5

            # 매직 아이템 대응: "prefix base suffix" 형태에서 토큰별 개별 매칭
            # 예) "속도퍽 보석공퍽 티아리" → "티아리" 단독으로 "티아라" 매칭
            tokens = [t.strip() for t in raw.split() if len(t.strip()) >= 2]
            if len(tokens) >= 2 and not best_item:
                for token in tokens:
                    t_n = self._normalize(token)
                    if len(t_n) < 2:
                        continue
                    if t_n in self.base_items:
                        print(f'[ItemMatcher] 토큰 정확 매치: "{t_n}"')
                        return self.base_items[t_n]
                    for key, item in self.base_items.items():
                        key_n = self._normalize(key)
                        if len(key_n) < 2:
                            continue
                        score = self._combined_similarity(t_n, key_n)
                        if score >= 0.72 and score > best_ratio:
                            best_ratio = score
                            best_item = item
                            print(f'[ItemMatcher] 토큰 퍼지 매치: "{token}" ≈ "{key}" ({score:.2f})')

        if best_item:
            print(f'[ItemMatcher] 베이스 아이템 매치: ratio={best_ratio:.2f}')
        return best_item

    # ──────────────────────────────────────────
    # 옵션 매칭 (extension option-parser.js 동일 로직)
    # ──────────────────────────────────────────

    def _correct_ocr_typo(self, text: str) -> str:
        """OCR 오타 교정 (synonym_dict.ocr_typo_corrections)"""
        corrections = self.synonym_dict.get('ocr_typo_corrections', {})
        for typo, correction in corrections.items():
            text = text.replace(typo, correction)
        return text

    def _normalize_synonym(self, text: str) -> str:
        """동의어 정규화 (synonym_dict.synonym_normalization)"""
        synonyms = self.synonym_dict.get('synonym_normalization', {})
        key = self._normalize_option(text)
        for synonym, normalized in synonyms.items():
            if key == self._normalize_option(synonym):
                return normalized
        return text

    def _find_option_by_name(self, raw_name: str) -> Optional[Dict]:
        """
        옵션명 → optionCombo 항목 매핑
        extension DataService.findOptionByKoreanName() 동일 로직:
        1. OCR 오타 교정
        2. 동의어 정규화
        3. 단어 순서 swap 후보 생성
        4. exact koKR → samekoKR → speek → substring → fuzzy
        """
        # 1. OCR 오타 교정
        corrected = self._correct_ocr_typo(raw_name)

        # 2. 동의어 정규화
        corrected = self._normalize_synonym(corrected)

        normalized = self._normalize_option(corrected)
        if not normalized:
            return None

        # 3. word order swap 후보 (피해 prefix/suffix)
        candidates = [normalized]
        if normalized.startswith('피해'):
            candidates.append(normalized[2:] + '피해')
        elif normalized.endswith('피해'):
            candidates.append('피해' + normalized[:-2])

        # 4-1. exact koKR match
        for cand in candidates:
            for opt in self.option_combo:
                kor = self._normalize_option(opt.get('koKR', ''))
                if cand == kor:
                    print(f'[ItemMatcher] 옵션 exact 매치: "{raw_name}" → "{opt.get("koKR")}"')
                    return opt

        # 4-2. samekoKR match
        for opt in self.option_combo:
            same_list = opt.get('samekoKR', [])
            if not same_list:
                continue
            for same in same_list:
                same_n = self._normalize_option(same)
                if normalized == same_n:
                    print(f'[ItemMatcher] 옵션 samekoKR exact 매치: "{raw_name}" → "{opt.get("koKR")}"')
                    return opt
                score = self._combined_similarity(normalized, same_n)
                if score >= FUZZY_THRESHOLD_SAMEKOR:
                    print(f'[ItemMatcher] 옵션 samekoKR fuzzy 매치: "{raw_name}" → "{opt.get("koKR")}" ({score:.2f})')
                    return opt
                if normalized in same_n or same_n in normalized:
                    print(f'[ItemMatcher] 옵션 samekoKR 부분 매치: "{raw_name}" → "{opt.get("koKR")}"')
                    return opt

        # 4-3. speek 기반 매칭 (kor_end_affix.json)
        result = self._match_by_speek(normalized)
        if result:
            print(f'[ItemMatcher] 옵션 speek 매치: "{raw_name}" → "{result.get("koKR")}"')
            return result

        # 4-4. substring match (koKR)
        best_sub = None
        best_sub_len = 0
        for opt in self.option_combo:
            kor = self._normalize_option(opt.get('koKR', ''))
            if not kor:
                continue
            if normalized in kor or kor in normalized:
                min_len = min(len(normalized), len(kor))
                max_len = max(len(normalized), len(kor))
                coverage = min_len / max_len if max_len else 0
                # query가 DB 항목의 접두어인 경우도 허용 (예: "홈" → "홈수량")
                is_prefix = kor.startswith(normalized)
                if (coverage >= 0.8 or len(kor) >= 5 or is_prefix) and len(kor) > best_sub_len:
                    best_sub_len = len(kor)
                    best_sub = opt
        if best_sub:
            print(f'[ItemMatcher] 옵션 substring 매치: "{raw_name}" → "{best_sub.get("koKR")}"')
            return best_sub

        # 4-5. fuzzy match
        best_score = 0.0
        best_opt = None
        for opt in self.option_combo:
            kor = self._normalize_option(opt.get('koKR', ''))
            if len(kor) < 2:
                continue
            score = self._combined_similarity(normalized, kor)
            if score > best_score:
                best_score = score
                best_opt = opt
        if best_opt and best_score >= FUZZY_THRESHOLD_OPTION:
            print(f'[ItemMatcher] 옵션 fuzzy 매치: "{raw_name}" → "{best_opt.get("koKR")}" ({best_score:.2f})')
            return best_opt

        return None

    def _match_by_speek(self, normalized: str) -> Optional[Dict]:
        """
        한글 발음(speek) 기반 영어명 조합으로 optionCombo 매칭
        extension OptionParser speek 로직 동일
        """
        if not self.kor_end_affix:
            return None

        sorted_affixes = sorted(
            self.kor_end_affix,
            key=lambda a: len(self._normalize_option(a.get('speek', ''))),
            reverse=True
        )

        matched = []
        for affix in sorted_affixes:
            speek = self._normalize_option(affix.get('speek', ''))
            eng = affix.get('eng', '')
            if not speek or not eng or len(speek) < 2:
                continue
            if speek in normalized:
                already_covered = any(speek in m['speek'] for m in matched)
                if not already_covered:
                    matched.append({'speek': speek, 'eng': eng.lower()})

        if not matched:
            return None

        # 모든 eng 단어가 포함된 option 찾기
        for opt in self.option_combo:
            eng_name = (opt.get('name', '') or '').lower()
            if all(m['eng'] in eng_name for m in matched):
                return opt

        # 부분 매칭 - 가장 많이 일치하는 option
        best_count = 0
        best_opt = None
        for opt in self.option_combo:
            eng_name = (opt.get('name', '') or '').lower()
            count = sum(1 for m in matched if m['eng'] in eng_name)
            if count > best_count:
                best_count = count
                best_opt = opt
        if best_opt and best_count == len(matched):
            return best_opt

        return None

    def find_option_keys(self, options: list, max_offset: int = 0) -> list:
        """
        OCR 옵션 목록 → Traderie option key 목록
        options: [{'name': str, 'min': int, 'max': int}, ...]
        max_offset: max = min + offset (DB max 없으므로 그대로 적용)
        반환:    [{'key': int, 'min': int, 'max': int, 'name': str, 'included': bool}, ...]
        """
        result = []
        for opt in options:
            name = opt.get('name', '')
            ocr_val = opt.get('min', 0) or 0
            computed_max = ocr_val + max_offset if max_offset else ocr_val
            matched = self._find_option_by_name(name)
            if matched and matched.get('id') is not None:
                result.append({
                    'key': matched['id'],
                    'min': ocr_val,
                    'max': computed_max,
                    'name': name,
                    'included': True,
                })
        return result

    def get_options_from_db(self, item_info: dict, ocr_options: list,
                            max_offset: int = 0,
                            include_unselected: bool = False) -> list:
        """
        unique/set/runeword: description_filtered DB 기준으로 옵션 구성
        - OCR에서 찾은 실제값 우선, DB 범위 밖이면 DB값 사용
        - selectable 그룹(또는 property_group 태그된 택1 그룹)은 OCR로 매칭된 항목만 포함 (미매칭 후보는 제외)
        - include_unselected=True면 미매칭 그룹 후보도 included=False로 포함
          (즐겨찾기 편집 UI에서 체크박스로 수동 추가할 수 있도록)
        - 반환값의 'selectable' 필드는 DB 원본 플래그 그대로(UI가 고정값 라벨 vs
          min/max 편집기 중 무엇을 그릴지 판단하는 용도) — property_group으로 인한
          택1 포함 로직은 'included'에만 반영되고 'selectable' 값 자체는 바뀌지 않는다.
        반환: [{'key': int, 'min': int, 'max': int, 'name': str,
               'db_min': int, 'db_max': int, 'selectable': bool, 'included': bool}, ...]
        """
        description_filtered = item_info.get('description_filtered', [])
        if not description_filtered:
            return []

        result = []
        for db_opt in description_filtered:
            prop_id = db_opt.get('property_id')
            if not prop_id:
                continue

            db_min = db_opt.get('min')
            db_max = db_opt.get('max')
            # selectable: DB상 순수 택1 플래그 (UI에 고정값으로 표시 — 편집 UI 렌더링용, 그대로 유지)
            selectable = db_opt.get('selectable', False)
            # group_exclusive: selectable이거나 property_group(A/B/C/D 등) 태그가 있으면
            # 같은 그룹 중 택1 구조 → OCR로 실제 매칭된 것만 채택 (포함 여부 판단 로직 전용,
            # UI의 min/max 편집기 표시 여부에는 영향 주지 않도록 selectable 필드는 그대로 둔다)
            group_exclusive = selectable or bool(db_opt.get('property_group'))

            # 고정값(min==max)은 URL 파라미터 불필요 — group_exclusive면 포함
            if db_min is not None and db_max is not None and db_min == db_max and not group_exclusive:
                continue

            # DB 범위 없는 항목은 스킵
            if db_min is None or db_max is None:
                continue

            prop_kor = db_opt.get('property_kor', '') or ''
            prop_eng = db_opt.get('property', '') or ''

            # prop_kor 인코딩 깨진 경우 감지 (한글 범위 밖 문자가 섞임)
            kor_valid = bool(prop_kor) and all(
                '가' <= c <= '힣' or c in ' _()' or c.isascii()
                for c in prop_kor
            )
            search_names = []
            if kor_valid and prop_kor:
                search_names.append(prop_kor)
            if prop_eng:
                search_names.append(prop_eng)

            display_name = prop_kor if (kor_valid and prop_kor) else (prop_eng or str(prop_id))

            ocr_val = None
            for search_name in search_names:
                ocr_val = self._extract_ocr_value_for_prop(search_name, ocr_options, db_min, db_max)
                if ocr_val is not None:
                    break

            if ocr_val is not None:
                computed_max = min(ocr_val + max_offset, db_max) if max_offset else ocr_val
                result.append({'key': prop_id, 'min': ocr_val, 'max': computed_max, 'name': display_name,
                               'db_min': db_min, 'db_max': db_max, 'selectable': selectable,
                               'included': True})
                print(f'[Matcher] OCR값 적용 prop={prop_id} "{search_name}" → {ocr_val} (DB:{db_min}~{db_max})')
            elif group_exclusive:
                # selectable/property_group 그룹(예: 직업별 스킬 +N 중 택1)은 OCR로 실제 매칭된 항목만 포함.
                # 매칭 안 된 후보는 URL에 기본 반영하지 않고, 즐겨찾기 편집 UI에서
                # 체크박스로 수동 추가할 수 있도록 included=False로만 남겨둔다.
                print(f'[Matcher] selectable 미매칭 — 제외: prop={prop_id} "{display_name}"')
                if include_unselected:
                    result.append({'key': prop_id, 'min': db_min, 'max': db_max, 'name': display_name,
                                   'db_min': db_min, 'db_max': db_max, 'selectable': selectable,
                                   'included': False})
            else:
                # OCR 미매칭: DB 기본값으로 포함(고정 스탯은 항상 존재)
                result.append({'key': prop_id, 'min': db_min, 'max': db_max, 'name': display_name,
                               'db_min': db_min, 'db_max': db_max, 'selectable': selectable,
                               'included': True})
                print(f'[Matcher] DB값 fallback prop={prop_id} "{display_name}" → {db_min}~{db_max}')

        return result

    def _extract_ocr_value_for_prop(self, prop_name: str, ocr_options: list,
                                     db_min: int, db_max: int) -> Optional[int]:
        """
        DB 옵션명에 매칭되는 OCR 옵션을 찾아 DB 범위 내 숫자값 반환.
        매칭 실패 또는 범위 밖이면 None 반환.
        """
        if not prop_name or not ocr_options:
            return None

        ocr_match = self._find_matching_ocr_option(prop_name, ocr_options)
        if not ocr_match:
            return None

        ocr_val = ocr_match.get('min', 0) or 0
        if db_min <= ocr_val <= db_max:
            return ocr_val

        # 범위 밖인 경우: raw 텍스트에서 범위 내 숫자를 모두 찾아 재시도
        raw = ocr_match.get('_raw', '')
        if raw:
            nums = [int(n) for n in re.findall(r'\d+', raw)]
            for n in nums:
                if db_min <= n <= db_max:
                    return n

        return None

    # 영문 DB 옵션명 → OCR 한글 키워드 매핑 (prop_kor 인코딩 깨진 경우 대비)
    _ENG_TO_KOR_KEYWORDS = {
        'enhanced damage':       ['피해', '증가'],
        'bonus to attack rating':['명중률', '보너스'],
        'attack rating':         ['명중률'],
        'fire damage':           ['화염', '피해'],
        'cold damage':           ['냉기', '피해'],
        'lightning damage':      ['번개', '피해'],
        'poison damage':         ['독', '피해'],
        'meditation aura':       ['명상', '오라'],
        'critical strike':       ['치명타'],
        'all attributes':        ['능력치'],
        'mana after each kill':  ['마나'],
        'magic find':            ['마법', '발견'],
        'cast rate':             ['시전', '속도'],
        'minimum damage':        ['최소', '피해'],
        'maximum damage':        ['최대', '피해'],
        'life':                  ['생명력'],
        'mana':                  ['마나'],
        'strength':              ['힘'],
        'dexterity':             ['민첩'],
        'resistances':           ['저항'],
        'fire resist':           ['화염', '저항'],
        'cold resist':           ['냉기', '저항'],
        'lightning resist':      ['번개', '저항'],
        'poison resist':         ['독', '저항'],
        'faster run':            ['이동', '속도'],
        'faster hit recovery':   ['피격', '회복'],
        'increased attack speed':['공격', '속도'],
        'replenish life':        ['생명력', '회복'],
        'defense':               ['방어'],
        'to skills':             ['스킬'],
        'to all skills':         ['전체', '스킬'],
        'indestructible':        ['수리', '불가'],
        'ethereal':              ['무형', '에테리얼'],
    }

    def _find_matching_ocr_option(self, db_name: str, ocr_options: list) -> Optional[Dict]:
        """DB 옵션명과 OCR 옵션 목록에서 가장 유사한 항목 반환"""
        if not db_name or not ocr_options:
            return None

        # 클래스 제한 괄호 제거 후 정규화
        cleaned = re.sub(r'\([^)]*\)', '', db_name).strip()
        cleaned_n = self._normalize_option(cleaned)

        best_score = 0.0
        best_opt = None
        for ocr_opt in ocr_options:
            ocr_name = self._normalize_option(ocr_opt.get('name', ''))
            raw = self._normalize_option(ocr_opt.get('_raw', ''))
            search_target = raw or ocr_name
            if not search_target:
                continue
            if cleaned_n == ocr_name or cleaned_n in search_target or ocr_name in cleaned_n:
                return ocr_opt
            score = self._combined_similarity(cleaned_n, ocr_name)
            if score > best_score:
                best_score = score
                best_opt = ocr_opt

        if best_opt and best_score >= 0.75:
            return best_opt

        # 영문 DB명 → 한글 키워드로 재시도
        eng_lower = cleaned.lower()
        for eng_key, kor_keywords in self._ENG_TO_KOR_KEYWORDS.items():
            if eng_key in eng_lower:
                for ocr_opt in ocr_options:
                    raw = ocr_opt.get('_raw', '') or ocr_opt.get('name', '')
                    if all(kw in raw for kw in kor_keywords):
                        print(f'[Matcher] 영문키워드 매칭: "{db_name}" → "{raw}"')
                        return ocr_opt

        # 한글 DB명 핵심 키워드 매칭 (OCR이 깨져 자모 유사도가 낮은 경우 대비)
        # 예: DB "적의 번개 저항" → 핵심키워드 ['번개','저항'] vs OCR "|하뇨 번개 저항 -15%"
        # DB "번개 기술 피해" → ['번개','기술','피해'] vs OCR "번개 기술 H위표 +13%" (과반 일치)
        kor_keywords = self._extract_kor_keywords(cleaned)
        if kor_keywords:
            best_kw_opt = None
            best_kw_hits = 0
            for ocr_opt in ocr_options:
                raw = ocr_opt.get('_raw', '') or ocr_opt.get('name', '')
                hits = sum(1 for kw in kor_keywords if kw in raw)
                if hits > best_kw_hits:
                    best_kw_hits = hits
                    best_kw_opt = ocr_opt
            required_hits = max(1, (len(kor_keywords) + 1) // 2)  # 과반(올림) 이상 일치
            if best_kw_opt and best_kw_hits >= required_hits:
                print(f'[Matcher] 한글키워드 매칭: "{db_name}" → "{best_kw_opt.get("_raw", "")}" ({best_kw_hits}/{len(kor_keywords)})')
                return best_kw_opt

        return None

    # DB 옵션명에서 의미있는 핵심 명사만 추출 (조사/한정사 제거)
    _KOR_STOPWORDS = {'적의', '의', '에', '시', '당', '및', '추가'}

    def _extract_kor_keywords(self, text: str) -> list:
        words = [w for w in re.split(r'\s+', text.strip()) if w]
        keywords = [w for w in words if w not in self._KOR_STOPWORDS and len(w) >= 2]
        return keywords or [w for w in words if len(w) >= 2]

    # ──────────────────────────────────────────
    # 내부
    # ──────────────────────────────────────────

    def _fuzzy_lookup(self, normalized: str, lookup: dict, threshold: float) -> Optional[Dict]:
        best_score = 0.0
        best_item = None
        for key, item in lookup.items():
            key_n = self._normalize(key)
            if abs(len(normalized) - len(key_n)) > max(2, len(normalized) // 2):
                continue
            score = self._combined_similarity(normalized, key_n)
            if score > best_score:
                best_score = score
                best_item = item
        if best_score >= threshold:
            return best_item
        return None

    # ──────────────────────────────────────────
    # Magic 아이템 어픽스 (A경로)
    # ──────────────────────────────────────────

    def _get_affix_keys_for_item(self, base_item: dict) -> List[str]:
        """base_item ctg/ctgGroup → d2r_affixes_detailed.json 키 목록"""
        ctg = (base_item.get('ctg') or '').lower()
        ctg_group = (base_item.get('ctgGroup') or '').lower()

        if ctg == 'helmet':
            if ctg_group in _CIRCLET_CTGGROUPS:
                return ['helmet_circlet_prefixes', 'helmet_circlet_suffixes']
            return ['helmet_prefixes', 'helmet_suffixes']

        if ctg in _CTG_NO_AFFIX_DATA:
            return []

        if ctg in _CTG_TO_AFFIX_KEYS:
            return list(_CTG_TO_AFFIX_KEYS[ctg])

        if ctg in _WEAPON_CTGS or ctg.lower() in _WEAPON_CTGS:
            return ['weapon_prefixes', 'weapon_suffixes']

        # charm: charm_items에 name으로 구분
        charm_name = (base_item.get('name') or '').lower()
        if 'grand' in charm_name:
            return ['grand_charm_prefixes', 'grand_charm_suffixes']
        if 'small' in charm_name:
            return ['small_charm_prefixes', 'small_charm_suffixes']
        if 'charm' in charm_name:
            return ['grand_charm_prefixes', 'grand_charm_suffixes',
                    'small_charm_prefixes', 'small_charm_suffixes']

        # 폴백: 전체 키
        return list(self.affixes.keys())

    def find_magic_affixes(self, header_lines: List[str], base_item: dict) -> List[Dict]:
        """
        Magic 아이템 이름 라인에서 prefix/suffix 추출 (A경로).
        header_lines: 요구레벨 위쪽 OCR 라인 목록
        base_item: find_base_item_from_lines / find_item_key 결과
        반환: [affix_entry, ...] — effects 포함
        """
        if not header_lines or not base_item:
            return []

        base_kor = self._normalize(base_item.get('korName', ''))

        # 아이템명 줄 탐색: 한글이 없거나(파일명/시스템 문구 등) 보관함 UI 문구인 줄은
        # 건너뛴다. 앞쪽 3줄로 제한하지 않는 이유: OCR/AI가 파일명·UI 잡음을
        # 여러 줄 앞세우는 경우가 있어(예: "sample8.png", "보관함", "공유", "공유")
        # 실제 이름 줄이 4번째 줄 이후에 오는 경우도 존재하기 때문.
        _NOISE_LINES = {'보관함', '공유', '개인', '공개'}
        raw_line = ''
        for ln in header_lines:
            stripped = ln.strip()
            if len(stripped) < 2:
                continue
            if stripped in _NOISE_LINES:
                continue
            if not re.search(r'[가-힣]', stripped):
                continue
            raw_line = stripped
            break
        if not raw_line:
            return []

        tokens = [t for t in raw_line.split() if len(t.strip()) >= 2]
        affix_tokens = [
            t for t in tokens
            if self._combined_similarity(self._normalize(t), base_kor) < 0.70
        ]
        if not affix_tokens:
            print(f'[ItemMatcher] 어픽스 토큰 없음 (name="{raw_line}", base="{base_kor}")')
            return []

        affix_keys = self._get_affix_keys_for_item(base_item)
        candidates: List[Dict] = []
        for key in affix_keys:
            candidates.extend(self.affixes.get(key, []))

        if not candidates:
            print(f'[ItemMatcher] 어픽스 DB 없음: {affix_keys}')
            return []

        found: List[Dict] = []
        for token in affix_tokens:
            t_n = self._normalize(token)
            best_affix: Optional[Dict] = None
            best_score = 0.0
            for affix in candidates:
                affix_n = self._normalize(affix.get('korean_name', ''))
                score = self._combined_similarity(t_n, affix_n)
                if score > best_score:
                    best_score = score
                    best_affix = affix
            if best_affix and best_score >= 0.65:
                print(f'[ItemMatcher] 어픽스 매치: "{token}" → "{best_affix["korean_name"]}" ({best_score:.2f})')
                found.append(best_affix)
            else:
                print(f'[ItemMatcher] 어픽스 매치 실패: "{token}" (best={best_score:.2f})')

        return found

    def build_option_keys_from_affixes(self, affixes: List[Dict], base_item: dict,
                                        ocr_options: List[Dict] = None,
                                        max_offset: int = 0) -> List[Dict]:
        """
        Affix effects → Traderie option key 목록.
        - maxSockets clamp (홈/socket)
        - OCR 실제값으로 범위 내 오버라이드
        반환: [{'key': int, 'min': int, 'max': int, 'name': str,
               'db_min': int, 'db_max': int, 'included': bool}, ...]
        (name/db_min/db_max/included: 즐겨찾기 편집 UI에서 옵션 재적용·URL 재생성에 사용)
        """
        if not affixes:
            return []

        max_sockets = int(base_item.get('maxSockets') or 6)
        result: List[Dict] = []

        for affix in affixes:
            for effect in affix.get('effects', []):
                desc = effect.get('description', '')
                vrange = effect.get('value_range', {})
                eff_min = int(vrange.get('min') or 0)
                eff_max = int(vrange.get('max') or eff_min)

                # 소켓 수 clamp
                if '홈' in desc or 'socket' in desc.lower():
                    eff_min = min(eff_min, max_sockets)
                    eff_max = min(eff_max, max_sockets)
                    print(f'[ItemMatcher] 소켓 clamp → {eff_min}~{eff_max} (maxSockets={max_sockets})')

                matched_opt = self._find_option_by_name(desc)
                if not matched_opt or matched_opt.get('id') is None:
                    print(f'[ItemMatcher] 어픽스 옵션 키 없음: "{desc}"')
                    continue

                actual_min = eff_min
                if ocr_options:
                    ocr_match = self._find_matching_ocr_option(desc, ocr_options)
                    if ocr_match:
                        ocr_val = int(ocr_match.get('min') or 0)
                        if eff_min <= ocr_val <= eff_max:
                            actual_min = ocr_val
                            print(f'[ItemMatcher] 어픽스 OCR값 적용: "{desc}" → {ocr_val}')

                computed_max = min(actual_min + max_offset, eff_max) if max_offset else actual_min
                result.append({'key': matched_opt['id'], 'min': actual_min, 'max': computed_max,
                               'name': desc, 'db_min': eff_min, 'db_max': eff_max, 'included': True})
                print(f'[ItemMatcher] 어픽스→옵션 key={matched_opt["id"]} "{desc}" {actual_min}~{computed_max}')

        return result
