"""
아이템 ctg → 부위 슬롯 아이콘 키 매핑
아이콘 파일: 프로젝트 루트/icon/{slot}.png
"""

_CTG_TO_SLOT: dict[str, str] = {
    # 머리
    'helmet':     'head',
    'circlet':    'head',
    'pelt':       'head',
    'voodoo_head':'head',
    # 갑옷
    'armor':      'body',
    # 장갑
    'glove':      'glove',
    # 벨트
    'belt':       'belt',
    # 부츠 (아이콘 파일 없어도 graceful fallback)
    'boot':       'boot',
    # 반지
    'ring':       'ring',
    # 목걸이
    'amulet':     'neck',
    # 방패
    'shield':     'shield',
    # 부적 (charm rarity에서도 직접 지정)
    'charm':      'charm',
    # 무기
    'axe':        'weapon',
    'sword':      'weapon',
    'mace':       'weapon',
    'hammer':     'weapon',
    'scepter':    'weapon',
    'staff':      'weapon',
    'polearm':    'weapon',
    'spear':      'weapon',
    'javelin':    'weapon',
    'bow':        'weapon',
    'Crossbow':   'weapon',
    'knife':      'weapon',
    'h2h':        'weapon',
    'wand':       'weapon',
    'orb':        'weapon',
    'club':       'weapon',
}


def get_slot(ctg: str) -> str:
    """ctg 키 → 슬롯 이름. 매핑 없거나 ctg 없으면 빈 문자열."""
    if not ctg:
        return ''
    return _CTG_TO_SLOT.get(ctg, '')
