"""
Traderie URL Builder
Traderie API URL 생성 유틸리티
"""
from urllib.parse import quote


class TraderieUrlBuilder:
    """Traderie API/사이트 URL 생성"""

    BASE_API_URL = 'https://traderie.com/api/diablo2resurrected/listings'
    REAL_URL = 'https://traderie.com/diablo2resurrected/product'

    def __init__(self, name_id: str, item_key: int):
        self.name_id = name_id
        self.item_key = item_key
        self.params = {'item': item_key}

    def set_common_props(self, ladder: str, mode: str, ethereal: bool):
        if ladder == 'Ladder':
            self.params['prop_Ladder'] = 'true'
        elif ladder == 'Non Ladder':
            self.params['prop_Ladder'] = 'false'
        elif 'Ladder' in ladder and 'Non Ladder' in ladder:
            self.params['prop_Ladder'] = 'Ladder,Non Ladder'
        else:
            self.params['prop_Ladder'] = ladder

        self.params['prop_Mode'] = mode.lower() if mode else mode
        if ethereal:
            self.params['prop_Ethereal'] = 'true'

    def set_common_props_without_ethereal(self, ladder: str, mode: str):
        if ladder == 'Ladder':
            self.params['prop_Ladder'] = 'true'
        elif ladder == 'Non Ladder':
            self.params['prop_Ladder'] = 'false'
        elif 'Ladder' in ladder and 'Non Ladder' in ladder:
            self.params['prop_Ladder'] = 'Ladder,Non Ladder'
        else:
            self.params['prop_Ladder'] = ladder

        self.params['prop_Mode'] = mode.lower() if mode else mode

    def set_game_version(self, game_version: str):
        if game_version:
            self.params['prop_Game version'] = game_version

    def set_global_props(self, global_props: dict):
        for key, value in global_props.items():
            if key.startswith('prop_'):
                if isinstance(value, bool) and value is True:
                    self.params[key] = 'true'
                elif isinstance(value, str):
                    self.params[key] = value

    def set_options(self, options: list):
        """
        옵션 설정 (동일 key 중복 시 min/max 합산)
        options: [{'key': 510, 'min': 70, 'max': 90}, ...]
        """
        merged: dict = {}
        for opt in options:
            key = opt.get('key')
            min_val = opt.get('min', 0) or 0
            max_val = opt.get('max', 0) or 0
            if key not in merged:
                merged[key] = {'min': 0, 'max': 0}
            merged[key]['min'] += min_val
            merged[key]['max'] += max_val

        for key, vals in merged.items():
            if vals['min'] > 0:
                self.params[f'prop_{key}Min'] = vals['min']
            if vals['max'] > 0:
                self.params[f'prop_{key}Max'] = vals['max']

    def set_rarity(self, rarity: str):
        lower = rarity.lower() if rarity else ''
        # unique/set/base(runeword)/charm은 prop_Rarity 파라미터 불필요
        # charm은 항상 magic이지만 traderie 검색에서 rarity 필터 미사용
        if lower and lower not in ('set', 'unique', 'base', 'runeword', 'charm'):
            self.params['prop_Rarity'] = lower

    def _build_query_string(self, exclude_keys=None) -> str:
        if exclude_keys is None:
            exclude_keys = []
        return '&'.join(
            f"{quote(str(k), safe='')}={quote(str(v), safe='')}"
            for k, v in self.params.items()
            if k not in exclude_keys
        )

    def get_base_url(self) -> str:
        return f'{self.BASE_API_URL}?{self._build_query_string()}'

    def get_real_url(self) -> str:
        return f'{self.REAL_URL}/{self.name_id}?{self._build_query_string(exclude_keys=["item"])}'
