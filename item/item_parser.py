"""
OCR 텍스트 → 아이템 데이터 파싱 + Traderie URL 생성
"""
import re
import sys
import os
from pathlib import Path
from typing import Optional

from config import BACKEND_DATA_PATH

try:
    from .item_matcher import ItemMatcher
    from .url_builder import TraderieUrlBuilder
    _backend_available = True
except ImportError as e:
    print(f"[ItemParser] 서비스 로드 실패: {e}")
    _backend_available = False

try:
    from .slot_resolver import get_slot as _get_slot
except ImportError:
    _get_slot = lambda ctg: ''


class ItemParser:
    def __init__(self):
        self._matcher: Optional[ItemMatcher] = None
        self._init_matcher()

    def _init_matcher(self):
        if not _backend_available:
            return
        try:
            self._matcher = ItemMatcher()
            print("[ItemParser] ItemMatcher 초기화 완료")
        except Exception as e:
            print(f"[ItemParser] ItemMatcher 초기화 실패: {e}")

    # ── OCR Constants (ocr-constants.js 포팅) ─────────────────────

    REQUIRED_LEVEL_KEYWORDS = [
        '요구 레벨', '요구레벨', '착용 가능한 레벨', '구 레벨',
        'Required Level', 'Req Level'
    ]

    STATS_PATTERN = re.compile(
        r'^(착용요구치|착용가능|방어력|밤머력|내구력|내구도|수량|방어|필요|막기|피해'
        r'|양손 피해|한손 피해|투척|한손|전용|힘|민첩'
        r'|Defense|Required|Strength|Dexterity|Durability|Block|Quantity|Damage|Throw)'
        r'(\s|$|\+|\*|:|\\)'
    )

    SYSTEM_MESSAGES = [
        '소지품', '소지품에 보관', 'Keep in Inventory', 'to Inventory', '인벤토리',
        'Ctrl', 'Shift', 'Alt', '홈이 있는 아이템에 삽입 가능', '홈이 있는',
        '삽입 가능', 'Can be Inserted', 'Socketed Item',
        '우클릭', '좌클릭', 'Right Click', 'Left Click',
        # 보관함(스태시) UI 탭 문구
        '보관함', '개인', '공유', '공개',
        'Personal', 'Shared', 'Public',
    ]

    MAGIC_AFFIX_PREFIXES = [
        '임의의', '임의', '사악한', '선량한', '균형잡힌', '날카로운', '빛나는',
        '튼튼한', '화려한', '거친', '단단한', '맹렬한', '완벽한', '신성한',
        '위대한', '고귀한', '전설의', '신비로운',
    ]

    # ── 파싱 진입점 ───────────────────────────────────────────────

    def parse(self, ocr_lines: list, rarity: str, config: dict,
              ai_options: list = None, ai_item_name: str = None) -> dict:
        """
        OCR 텍스트 라인 → 아이템 정보 + Traderie URL 생성
        ai_options: AI가 구조화한 옵션 문자열 목록 (있으면 우선 사용)
        ai_item_name: AI가 직접 반환한 아이템 이름 (옵션 패턴 아니면 우선 사용)
        """
        if not ocr_lines:
            return {'success': False, 'error': 'OCR 결과가 없습니다'}

        # 1. 요구 레벨 기준으로 헤더(이름 영역) / 옵션 분리
        header_lines, option_lines = self._split_at_required_level(ocr_lines)

        # 2. 아이템 이름 결정
        # AI가 반환한 item_name이 옵션 패턴이 아니면 우선 사용
        if ai_item_name and not self._looks_like_option(ai_item_name):
            cleaned = re.sub(r'[^가-힣ㄱ-㆏a-zA-Z]', '', ai_item_name)
            item_name = cleaned if cleaned else None
        else:
            item_name = self._extract_item_name(header_lines)

        if not item_name:
            return {'success': False, 'error': '아이템 이름을 인식할 수 없습니다'}

        print(f"[ItemParser] 이름 추출: '{item_name}'  rarity={rarity}")

        if not self._matcher:
            return {
                'success': False,
                'item_name': item_name,
                'rarity': rarity,
                'error': '아이템 매처를 초기화할 수 없습니다'
            }

        # 3. Traderie 아이템 키 찾기
        # 옵션으로 인식된 라인 수 (부적 판별 시 유니크 여부 신호로 사용)
        _option_src = ai_options if ai_options else option_lines
        option_line_count = len(self._extract_options(_option_src))
        item_info = self._matcher.find_item_key(
            item_name, rarity, ocr_lines, option_line_count=option_line_count)

        if not item_info:
            return {
                'success': False,
                'item_name': item_name,
                'rarity': rarity,
                'error': f'Traderie DB에서 "{item_name}"을 찾을 수 없습니다'
            }

        # DB 이름 매치로 확정된 rarity 우선, 없으면 AI rarity 사용
        rarity = item_info.pop('_resolved_rarity', None) or rarity

        # ctg → 부위 슬롯 (charm rarity는 ctg와 무관하게 'charm' 고정)
        ctg = item_info.get('ctg', '')
        if not ctg:
            # uniqueResult/setItemList 등 ctg 필드 없는 경우: img URL에서 추출
            # 예: .../diablo2resurrected/circlet/diadem.png → 'circlet'
            img_url = item_info.get('img', '')
            if img_url:
                _m = re.search(r'/diablo2resurrected/([^/]+)/', img_url)
                if _m:
                    ctg = _m.group(1)
        slot = 'charm' if rarity == 'charm' else _get_slot(ctg)

        item_key = item_info.get('id') or item_info.get('key')
        name_id = item_info.get('nameId') or item_info.get('name_id') or \
                  self._to_name_id(item_info.get('name') or item_name) or \
                  str(item_key or '')

        if not item_key:
            return {
                'success': False,
                'item_name': item_name,
                'rarity': rarity,
                'error': f'아이템 키를 찾을 수 없습니다: {item_info}'
            }

        # 4. URL 빌더
        builder = TraderieUrlBuilder(name_id, item_key)
        ladder = config.get('ladder', 'Ladder')
        mode = config.get('mode', 'Softcore')
        versions = config.get('versions', [])
        ethereal = self._detect_ethereal(ocr_lines)

        builder.set_common_props(ladder, mode, ethereal)
        if versions:
            builder.set_game_version(','.join(versions))
        builder.set_rarity(rarity.capitalize())

        # 5. 옵션 적용
        # AI가 반환한 options를 우선 사용 (요구레벨 이하 옵션만 정리된 상태)
        # ocr_lines 기반 분리(option_lines)는 폴백으로 사용
        active_option_lines = ai_options if ai_options else option_lines
        ocr_options = self._extract_options(active_option_lines)
        max_offset = int(config.get('option_max_offset', 0) or 0)

        # 옵션 표시용 (즐겨찾기/스캔목록 우측 패널에 보여줄 이름-값 목록)
        options_display: dict = {}
        # 구조화된 옵션 메타데이터 (즐겨찾기 편집 UI에서 min/max 조정, selectable 토글용)
        options_editable: list = []
        url_ctx: dict = {}

        # 세계석조각(shard)/열쇠(key): 아이템 키만으로 검색, 옵션 미적용
        # 유니크 부적(named unique charm)도 description_filtered에 변동옵션 범위가 있으므로
        # 아래 unique/set/base 분기에서 다른 유니크 아이템과 동일하게 크로스 매칭 적용
        # 동상(statue)은 고정 스탯이 항상 존재하므로 옵션 적용 유지
        # (일반 매직 부적은 rarity='charm'이므로 해당 없음 — 어픽스 옵션 계속 적용)
        _skip_options = ctg in {'shard', 'key'}
        if _skip_options:
            pass  # 옵션 적용 없이 URL 빌더 종료
        # unique/set/base(runeword) → DB description_filtered 기준 변동옵션 크로스 매칭
        elif rarity in ('unique', 'set', 'base', 'runeword'):
            all_option_keys = self._matcher.get_options_from_db(
                item_info, ocr_options, max_offset=max_offset, include_unselected=True)
            option_keys = [o for o in all_option_keys if o.get('included', True)]
            if option_keys:
                builder.set_options(option_keys)
                options_display = self._build_options_display(option_keys)
            options_editable = all_option_keys
            url_ctx = {
                'name_id': name_id, 'item_key': item_key,
                'ladder': ladder, 'mode': mode, 'versions': versions,
                'ethereal': ethereal, 'rarity': rarity,
            }
        elif rarity in ('magic', 'charm') and ocr_options:
            # A경로: 어픽스 DB 매칭
            affixes = self._matcher.find_magic_affixes(header_lines, item_info)
            option_keys = []
            if affixes:
                option_keys = self._matcher.build_option_keys_from_affixes(
                    affixes, item_info, ocr_options, max_offset)
                if option_keys:
                    builder.set_options(option_keys)
            elif rarity == 'magic':
                # Magic(비부적): A경로 실패 시 B경로(OCR 직접 매칭) 폴백
                option_keys = self._matcher.find_option_keys(ocr_options, max_offset=max_offset)
                if option_keys:
                    builder.set_options(option_keys)
            # charm은 A경로 실패 시 B경로 미실행 — 어픽스 미특정 상태에서 전체 옵션 적용은 과검색 유발
            options_display = self._build_options_display(ocr_options)
            if option_keys:
                # 즐겨찾기 편집 UI에서 min/max 조정 후 URL 재생성이 가능하도록 저장
                # (없으면 옵션 수정이 표시 텍스트만 바뀌고 링크에는 반영되지 않음)
                options_editable = option_keys
                url_ctx = {
                    'name_id': name_id, 'item_key': item_key,
                    'ladder': ladder, 'mode': mode, 'versions': versions,
                    'ethereal': ethereal, 'rarity': rarity,
                }
        elif rarity == 'rare' and ocr_options:
            option_keys = self._matcher.find_option_keys(ocr_options, max_offset=max_offset)
            if option_keys:
                builder.set_options(option_keys)
            options_display = self._build_options_display(ocr_options)

        traderie_url = builder.get_real_url()
        api_url = builder.get_base_url()

        raw_kor = item_info.get('korName') or item_info.get('name') or item_name
        affix_kor = item_info.get('affix_kor', '')
        if affix_kor:
            # setItemList: affix_kor이 별도 필드 → (부츠)알더의전진
            display_name = f"{affix_kor}{raw_kor}"
        else:
            # uniqueResult: korName이 (접두사)기본명 형태 → 기본명(접두사)
            _pfx = re.match(r'^\(([^)]+)\)(.+)', raw_kor)
            display_name = f"{_pfx.group(2).strip()}({_pfx.group(1)})" if _pfx else raw_kor

        return {
            'success': True,
            'item_name': display_name,
            'rarity': rarity,
            'slot': slot,
            'traderie_url': traderie_url,
            'api_url': api_url,
            'options': options_display,
            'options_editable': options_editable,
            'url_ctx': url_ctx,
        }

    def _build_options_display(self, options: list) -> dict:
        """[{'name'|'key': str, 'min': int, 'max': int}, ...] → {표시명: "min~max"} 변환"""
        display = {}
        for opt in options:
            name = opt.get('name') or str(opt.get('key', ''))
            if not name:
                continue
            min_val, max_val = opt.get('min', 0) or 0, opt.get('max', 0) or 0
            display[name] = str(min_val) if min_val == max_val else f"{min_val}~{max_val}"
        return display

    def rebuild_url(self, url_ctx: dict, options_editable: list) -> dict:
        """
        즐겨찾기 옵션 수치/포함여부 수정 후 traderie_url/api_url 재생성.
        options_editable: [{'key','min','max','included',...}, ...] (수정된 상태)
        반환: {'traderie_url': str, 'api_url': str}
        """
        builder = TraderieUrlBuilder(url_ctx['name_id'], url_ctx['item_key'])
        builder.set_common_props(url_ctx.get('ladder', 'Ladder'),
                                 url_ctx.get('mode', 'Softcore'),
                                 url_ctx.get('ethereal', False))
        versions = url_ctx.get('versions')
        if versions:
            builder.set_game_version(','.join(versions))
        builder.set_rarity(url_ctx.get('rarity', '').capitalize())
        extra_params = url_ctx.get('extra_params')
        if extra_params:
            builder.params.update(extra_params)

        active_options = [o for o in options_editable if o.get('included', True)]
        if active_options:
            builder.set_options(active_options)

        return {
            'traderie_url': builder.get_real_url(),
            'api_url': builder.get_base_url(),
        }

    # ── 헤더/옵션 분리 ────────────────────────────────────────────

    # '요구 레벨'이 OCR 오류로 심하게 깨졌을 때 폴백 매칭용
    # 예: "요구 :弓고 76", "요 구레벨76" 등 — '요구'로 시작 + 숫자 포함
    _REQUIRED_LEVEL_FALLBACK = re.compile(r'^요\s*구\b.*\d')

    def _split_at_required_level(self, lines: list) -> tuple[list, list]:
        """
        '요구 레벨' 키워드 기준으로 헤더(아이템명 영역)와 옵션 영역 분리.
        (ocr-constants.js REQUIRED_LEVEL_KEYWORDS 포팅)
        """
        for i, line in enumerate(lines):
            lower = line.lower()
            if any(kw.lower() in lower for kw in self.REQUIRED_LEVEL_KEYWORDS):
                return lines[:i], lines[i + 1:]

        # 정확한 키워드 매칭 실패 시 폴백: '요구'로 시작 + 숫자 포함 라인
        for i, line in enumerate(lines):
            if self._REQUIRED_LEVEL_FALLBACK.match(line.strip()):
                return lines[:i], lines[i + 1:]

        # 키워드 없으면 전체를 헤더로 처리
        return lines, []

    # ── 아이템 이름 추출 ──────────────────────────────────────────

    def _extract_item_name(self, header_lines: list) -> Optional[str]:
        """
        헤더 라인에서 아이템 이름 추출.
        (item-name-filter.js + text-normalizer.js 포팅)

        흐름:
          1. 각 라인 정규화 (TextNormalizer)
          2. 유효 후보 필터 (ItemNameFilter)
          3. 점수 계산 후 최고 점수 후보 선택
          4. 한글/영문만 남기고 공백 제거
        """
        candidates = []
        for idx, raw in enumerate(header_lines):
            # 룬조합 패턴 제외: 따옴표로 감싸진 라인 (예: '앰랄말이스트오움')
            stripped_raw = raw.strip()
            if re.match(r"^['\"‘’“”].*['\"‘’“”]$", stripped_raw):
                continue
            normalized = self._normalize_line(raw)
            if not normalized:
                continue
            if not self._is_valid_name_candidate(normalized):
                continue
            score = self._score_candidate(normalized)
            # 첫 번째 유효 후보에 위치 보너스 (D2R은 첫 줄이 아이템명)
            position_bonus = max(0, 80 - idx * 30)
            candidates.append((score + position_bonus, normalized))

        if not candidates:
            return None

        candidates.sort(key=lambda x: -x[0])
        best = candidates[0][1]

        # 한글과 영문만 남기고 공백 제거 → "티 아 라" → "티아라"
        cleaned = re.sub(r'[^\uAC00-\uD7A3\u3131-\u318Fa-zA-Z]', '', best)
        return cleaned if cleaned else None

    def _normalize_line(self, line: str) -> str:
        """
        OCR 라인 정규화.
        (text-normalizer.js TextNormalizer.normalizeLine() 포팅)
        """
        s = line.strip()

        # 한글 OCR 오류 수정
        s = re.sub(r'구\s*레벨', '요구 레벨', s)  # "구 레벨" → "요구 레벨"

        # 숫자/기호 오류 수정
        s = re.sub(r'[*＊]\s*\+\s*(\d+)\s*[?？]', r'+\1', s)
        s = re.sub(r'[*＊]\s*\+\s*(\d+)', r'+\1', s)
        s = re.sub(r'(\d)[|｜]', r'\g<1>1', s)

        # 노이즈 특수문자 제거
        s = re.sub(r'ㅁㅁ', '', s)
        s = re.sub(r'[{}\[\]]', '', s)
        s = re.sub(r'[\s.，]+$', '', s)

        # 공백 정규화
        s = re.sub(r'\s{2,}', ' ', s)

        # 부적 이름 정규화
        s = re.sub(r'거대\s*부적', '거대부적', s)
        s = re.sub(r'작은\s*부적', '작은부적', s)
        s = re.sub(r'큰\s*부적', '큰부적', s)

        # Magic affix 접두사 제거
        for prefix in self.MAGIC_AFFIX_PREFIXES:
            s = re.sub(r'^' + re.escape(prefix) + r'\s+', '', s)

        return s.strip()

    def _is_valid_name_candidate(self, line: str) -> bool:
        """
        아이템 이름 후보로 유효한지 확인.
        (item-name-filter.js ItemNameFilter.isValidCandidate() 포팅)
        """
        if not line or len(line.strip()) < 2:
            return False

        # 필터 1: 스탯 키워드로 시작
        if self.STATS_PATTERN.match(line):
            return False

        # 필터 2: 콜론이 중간에 있는 라인 (방어력: 47, 내구도: 25/25 등)
        rarity_keywords = ['(고급)', '(유일)', '(세트)', '(마법)']
        has_rarity = any(kw in line for kw in rarity_keywords)
        colon_idx = line.find(':')
        if colon_idx > 0 and colon_idx < len(line) - 1 and not has_rarity:
            return False

        # 필터 3: 시스템 메시지
        lower = line.lower()
        if any(msg.lower() in lower for msg in self.SYSTEM_MESSAGES):
            return False

        # 필터 4: 한글 최소 2자
        korean_chars = re.findall(r'[\u3131-\u318F\uAC00-\uD7A3]', line)
        if len(korean_chars) < 2:
            return False

        # 필터 5: 한글+영문 비율 20% 이상
        english_chars = re.findall(r'[a-zA-Z]', line)
        total_valid = len(korean_chars) + len(english_chars)
        no_space = line.replace(' ', '')
        ratio = total_valid / len(no_space) if no_space else 0
        if ratio < 0.2:
            return False

        return True

    def _score_candidate(self, line: str) -> float:
        """
        아이템 이름 후보 품질 점수.
        (item-name-filter.js scoreCandidate() 포팅)
        """
        score = 0.0

        # 1. 한글 비율 (0~100)
        korean = re.findall(r'[\uAC00-\uD7A3\u3131-\u318F]', line)
        no_space = line.replace(' ', '')
        korean_ratio = len(korean) / len(no_space) if no_space else 0
        score += korean_ratio * 100

        # 2. 길이 점수 (이상적 15자)
        ideal = 15
        length_score = max(0, 100 - abs(len(line) - ideal) * 3)
        score += length_score * 0.5

        # 3. 특수문자 페널티
        special = re.findall(r'[|_\-#&@*~`\[\]<>]', line)
        score -= len(special) * 10

        # 4. 숫자로 끝나면 페널티
        if re.search(r'\d+$', line):
            score -= 50

        # 5. 희귀도 괄호 보너스
        if re.search(r'\([가-힣]+\)', line):
            score += 30

        return score

    # ── 기타 헬퍼 ────────────────────────────────────────────────

    def _looks_like_option(self, text: str) -> bool:
        """옵션 텍스트 패턴인지 확인 — AI item_name 유효성 검증용"""
        if re.search(r'\d+%', text):
            return True
        option_endings = ['증가', '감소', '하락', '획득', '상승', '추가', '적용', '부여',
                          'increase', 'decrease', 'bonus', 'added']
        lower = text.lower()
        return any(lower.endswith(e) for e in option_endings)

    def _detect_ethereal(self, lines: list) -> bool:
        """에테리얼 여부 감지"""
        keywords = ['에테리얼', '무형', '무 형', 'ethereal']
        for line in lines:
            lower = line.lower()
            if any(kw in lower for kw in keywords):
                return True
        return False

    def _extract_options(self, lines: list) -> list:
        """
        옵션 라인에서 이름/수치 추출.
        숫자가 포함된 모든 옵션 라인을 파싱하여 name + 대표 숫자값을 반환한다.
        """
        options = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 패턴1: "+숫자 옵션명"  예) "+30 민첩", "+4 치명타"
            m = re.match(r'^([+\-]?\d+)%?\s+(.+)$', stripped)
            if m:
                try:
                    val = abs(int(re.sub(r'[^0-9\-]', '', m.group(1))))
                    name = m.group(2).strip()
                    options.append({'name': name, 'min': val, 'max': val, '_raw': stripped})
                except ValueError:
                    pass
                continue

            # 패턴2: "옵션명 +숫자% 증가|감소"  예) "피해 +231% 증가"
            m = re.match(r'^(.+?)\s+[+\-]?(\d+)%\s+(증가|감소|추가|하락|상승)$', stripped)
            if m:
                name = (m.group(1) + ' ' + m.group(3)).strip()
                val = int(m.group(2))
                options.append({'name': name, 'min': val, 'max': val, '_raw': stripped})
                continue

            # 패턴3: "옵션명 숫자% 증가|감소"  예) "방어력 199% 증가"
            m = re.match(r'^(.+?)\s+(\d+)%\s+(증가|감소|추가|하락|상승)$', stripped)
            if m:
                name = (m.group(1) + ' ' + m.group(3)).strip()
                val = int(m.group(2))
                options.append({'name': name, 'min': val, 'max': val, '_raw': stripped})
                continue

            # 패턴4: "옵션명 숫자%"  예) "명중률 보너스 226%", "마법 아이템 발견 확률 23%"
            m = re.match(r'^(.+?)\s+[+\-]?(\d+)%$', stripped)
            if m:
                name = m.group(1).strip()
                val = int(m.group(2))
                options.append({'name': name, 'min': val, 'max': val, '_raw': stripped})
                continue

            # 패턴5: "옵션명 +숫자"  예) "힘 +20", "모든 능력치 +5"
            m = re.match(r'^(.+?)\s+([+\-]\d+)%?$', stripped)
            if m:
                try:
                    val = abs(int(re.sub(r'[^0-9\-]', '', m.group(2))))
                    name = m.group(1).strip()
                    options.append({'name': name, 'min': val, 'max': val, '_raw': stripped})
                except ValueError:
                    pass
                continue

            # 패턴6: 중간에 숫자가 있는 문장  예) "장착 시 16 레벨 명상 오라 효과 적용"
            # 숫자를 추출하고 전체 텍스트를 name으로 사용
            nums = re.findall(r'\d+', stripped)
            if nums:
                val = int(nums[0])  # 첫 번째 숫자를 대표값으로
                options.append({'name': stripped, 'min': val, 'max': val, '_raw': stripped})

        return options

    def _to_name_id(self, name: str) -> str:
        """아이템 이름 → URL-friendly nameId 변환"""
        name_id = name.lower()
        name_id = re.sub(r"[^a-z0-9]+", "-", name_id)
        name_id = name_id.strip("-")
        return name_id
