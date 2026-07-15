"""
AI Vision Bridge - D2R 아이템 이미지 분석
Tesseract OCR 대신 AI 비전 API를 사용하여 툴팁 텍스트 추출

폴백 순서: Gemini → Groq
할당량 초과(429) 발생 시 자동으로 다음 제공자로 전환
"""
import base64
import json
from pathlib import Path
from typing import Optional, Callable

from config import load_ai_keys, load_config, save_config, save_ai_keys, \
    AI_MODEL_GEMINI, AI_MODEL_GROQ, DEFAULT_PROVIDER_ORDER

PROVIDER_NAMES = {
    'gemini': 'Gemini 2.5 Flash',
    'groq':   'Groq (Llama 4)',
}


def _get_providers() -> list:
    """keys에 저장된 order 기준으로 provider 순서 반환"""
    return load_ai_keys().get('order', DEFAULT_PROVIDER_ORDER[:])

# D2R 아이템 툴팁 분석 프롬프트
_PROMPT = """\
Extract all text from the image top to bottom. Output ONLY a JSON object. No explanation, no markdown, no code blocks.
{"lines": ["line1", "line2", ...]}
"""


class QuotaExceededError(Exception):
    def __init__(self, provider: str, detail: str = ''):
        self.provider = provider
        self.detail = detail
        super().__init__(f'{provider} 할당량 초과')


class ProviderUnavailableError(QuotaExceededError):
    """일시적 서버 과부하/장애 (503 UNAVAILABLE 등) — 할당량 초과와 동일하게 폴백 처리"""
    pass


class AIVisionBridge:
    """
    AI 비전 API 브릿지
    GPT → Gemini → Claude 순서로 폴백하며 이미지에서 텍스트 추출
    """

    def __init__(self):
        # 키는 매번 호출 시 config에서 fresh 로드 (UI에서 변경해도 바로 반영)
        self._status_callback: Optional[Callable] = None

        self._provider_idx = 0

        # 세션 내 소진된 provider 추적
        self._exhausted = set()

    # ──────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────

    def set_status_callback(self, fn: Callable):
        self._status_callback = fn

    @property
    def current_provider(self) -> str:
        keys = load_ai_keys()
        providers = _get_providers()
        for i in range(self._provider_idx, len(providers)):
            p = providers[i]
            if keys.get(p, '').strip():
                return p
        return 'none'

    @property
    def current_provider_name(self) -> str:
        return PROVIDER_NAMES.get(self.current_provider, self.current_provider)

    def has_any_key(self) -> bool:
        """API 키가 하나라도 설정돼 있는지 확인"""
        keys = load_ai_keys()
        return any(keys.get(p, '').strip() for p in _get_providers())

    def reset_provider(self):
        """첫 번째 키 설정된 provider부터 다시 시작 (UI에서 수동 리셋 시 호출)"""
        keys = load_ai_keys()
        providers = _get_providers()
        self._provider_idx = next(
            (i for i, p in enumerate(providers) if keys.get(p, '').strip()), 0
        )
        self._exhausted.clear()
        self._save_provider()
        self._log(f'AI 제공자 리셋 → {self.current_provider_name}')

    def run_ocr(self, image_path: str, lang: str = 'kor+eng') -> dict:
        """
        이미지에서 텍스트 추출 (기존 OcrBridge.run_ocr과 동일한 반환 형식)

        Returns:
            {
                'success': bool,
                'lines': List[str],
                'rawText': str,
                'linesWithBbox': [],   # AI는 bbox 정보 없음
                'provider': str,       # 사용된 AI 제공자
                'error': str           # 실패 시
            }
        """
        # provider_idx부터 순서대로 시도 (키 없는 provider는 스킵)
        keys = load_ai_keys()
        providers = _get_providers()
        for idx in range(self._provider_idx, len(providers)):
            provider = providers[idx]
            if not keys.get(provider, '').strip():
                continue  # API 키 미설정 → 스킵
            if provider in self._exhausted:
                continue

            self._log(f'{PROVIDER_NAMES[provider]} 호출 중...')
            self._notify_status(f'AI 분석 중 ({PROVIDER_NAMES[provider]})')

            try:
                result = self._call_provider(provider, image_path)
                # 성공: 현재 provider 기억
                if self._provider_idx != idx:
                    self._provider_idx = idx
                    self._save_provider()
                result['provider'] = provider
                lines = result.get('lines', [])
                raw = result.get('rawText', '')
                self._log(f'{PROVIDER_NAMES[provider]} 성공 - {len(lines)}줄')
                self._log(f'  rawText({len(raw)}자): {raw[:300]}')
                for i, line in enumerate(lines):
                    self._log(f'  [{i}] {line}')
                if not lines:
                    raise RuntimeError(f'AI가 텍스트를 반환하지 않았습니다 (rawText: {raw[:150]})')
                return result

            except QuotaExceededError as qe:
                detail = f': {qe.detail[:120]}' if qe.detail else ''
                reason = '일시적 서버 과부하' if isinstance(qe, ProviderUnavailableError) else '할당량 초과'
                msg = f'{PROVIDER_NAMES[provider]} {reason} → 다음 제공자로 전환{detail}'
                self._log(msg)
                self._notify_status(msg)
                self._exhausted.add(provider)
                self._provider_idx = idx + 1
                self._save_provider()
                continue

            except Exception as e:
                msg = f'{PROVIDER_NAMES[provider]} 오류: {e}'
                self._log(msg)
                self._notify_status(msg)
                return {'success': False, 'lines': [], 'rawText': '', 'linesWithBbox': [],
                        'provider': provider, 'error': str(e)}

        # 설정된 provider 소진
        configured = [p for p in providers if keys.get(p, '').strip()]
        if not configured:
            msg = 'API 키가 설정된 AI가 없습니다. "API 키" 버튼에서 키를 입력해주세요.'
        else:
            msg = f'설정된 AI({", ".join(PROVIDER_NAMES[p] for p in configured)})의 할당량이 모두 소진됐습니다. "AI 리셋" 버튼을 눌러주세요.'
        self._log(msg)
        return {'success': False, 'lines': [], 'rawText': '', 'linesWithBbox': [],
                'provider': 'none', 'error': msg}

    # ──────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────

    def _call_provider(self, provider: str, image_path: str) -> dict:
        if provider == 'gemini':
            return self._call_gemini(image_path)
        elif provider == 'groq':
            return self._call_groq(image_path)
        raise ValueError(f'알 수 없는 provider: {provider}')

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    # AI 거부 응답 패턴 (content policy 등)
    _REFUSAL_PATTERNS = (
        "i'm sorry",
        "i cannot",
        "i can't",
        "i am unable",
        "i'm unable",
        "sorry, i",
        "as an ai",
        "죄송합니다",
        "도움을 드릴 수 없",
    )

    # 할당량 초과가 응답 텍스트로 반환되는 패턴 (HTTP 에러가 아닌 경우)
    _QUOTA_PATTERNS = (
        "your current quota",
        "check your plan",
        "exceeded your",
        "rate limit exceeded",
        "quota exceeded",
        "upgrade your plan",
        "insufficient_quota",
    )

    def _parse_text(self, text: str, provider: str = '') -> dict:
        stripped = text.strip()
        lower = stripped.lower()

        # 할당량 초과 텍스트 응답 감지 → QuotaExceededError로 변환
        if len(stripped) < 300 and any(p in lower for p in self._QUOTA_PATTERNS):
            raise QuotaExceededError(provider or 'unknown', stripped[:120])

        # 거부 응답 감지
        if len(stripped) < 200 and any(p in lower for p in self._REFUSAL_PATTERNS):
            raise RuntimeError(f'AI가 이미지 분석을 거부했습니다: {stripped[:80]}')

        # 마크다운 코드블록 제거 (```json ... ``` 또는 ``` ... ```)
        if '```' in stripped:
            import re as _re
            m = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', stripped, _re.DOTALL)
            if m:
                stripped = m.group(1)

        # 설명문 무시하고 JSON 객체만 추출 ({ 첫 등장 위치부터)
        brace = stripped.find('{')
        if brace > 0:
            stripped = stripped[brace:]

        # JSON 파싱 시도
        try:
            data = json.loads(stripped)
            # 새 포맷: {"lines": [...]}
            if 'lines' in data:
                lines = [str(l).strip() for l in data['lines'] if str(l).strip()]
            else:
                # 구 포맷 폴백
                header = [str(l).strip() for l in data.get('header_lines', []) if str(l).strip()]
                options = [str(o).strip() for o in data.get('options', []) if str(o).strip()]
                lines = header + options

            return {
                'success': True,
                'item_name': None,   # main.py에서 item_parser가 결정
                'rarity': None,      # main.py에서 HSV가 결정
                'options': [],
                'lines': lines,
                'rawText': text,
                'linesWithBbox': [],
            }
        except (json.JSONDecodeError, KeyError):
            # JSON 파싱 실패 시 줄 단위 폴백
            lines = [l.strip() for l in stripped.split('\n') if l.strip()]
            return {
                'success': True,
                'item_name': None,
                'rarity': None,
                'options': [],
                'lines': lines,
                'rawText': text,
                'linesWithBbox': [],
            }

    def _save_provider(self):
        try:
            cfg = load_config()
            cfg['ai_provider'] = self.current_provider
            save_config(cfg)
        except Exception:
            pass

    def _log(self, msg: str):
        print(f'[AIVisionBridge] {msg}')

    def _notify_status(self, msg: str):
        if self._status_callback:
            try:
                self._status_callback(msg)
            except Exception:
                pass

    # ──────────────────────────────────────────
    # Gemini 2.0 Flash
    # ──────────────────────────────────────────

    def _call_gemini(self, image_path: str) -> dict:
        try:
            from google import genai as google_genai
            from google.genai import types as genai_types
        except ImportError:
            raise RuntimeError('google-genai 패키지가 설치되지 않았습니다. pip install google-genai')

        _keys = load_ai_keys()
        api_key = _keys.get('gemini', '')
        if not api_key:
            raise RuntimeError('Gemini API 키가 설정되지 않았습니다. 설정 창에서 키를 입력해주세요.')
        model = _keys.get('gemini_model', '') or AI_MODEL_GEMINI

        try:
            client = google_genai.Client(api_key=api_key)

            with open(image_path, 'rb') as f:
                image_bytes = f.read()

            response = client.models.generate_content(
                model=model,
                contents=[
                    genai_types.Content(parts=[
                        genai_types.Part(text=_PROMPT),
                        genai_types.Part(
                            inline_data=genai_types.Blob(
                                mime_type='image/png',
                                data=image_bytes
                            )
                        ),
                    ])
                ],
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=800,
                    http_options=genai_types.HttpOptions(timeout=30000),  # ms 단위
                ),
            )
            text = response.text or ''
            return self._parse_text(text, provider='gemini')

        except Exception as e:
            err_str = str(e).lower()
            if '429' in err_str or 'quota' in err_str or 'resource exhausted' in err_str:
                raise QuotaExceededError('gemini', str(e))
            if ('503' in err_str or 'unavailable' in err_str or 'overloaded' in err_str
                    or 'high demand' in err_str):
                raise ProviderUnavailableError('gemini', str(e))
            if 'api_key_invalid' in err_str or 'api key not valid' in err_str:
                raise RuntimeError('Gemini API 키가 유효하지 않습니다. 설정 창에서 키를 다시 확인해주세요.')
            raise

    # ──────────────────────────────────────────
    # Groq (Llama 4 Scout Vision)
    # ──────────────────────────────────────────

    def _call_groq(self, image_path: str) -> dict:
        try:
            import groq as groq_sdk
        except ImportError:
            raise RuntimeError('groq 패키지가 설치되지 않았습니다. pip install groq')

        _keys = load_ai_keys()
        api_key = _keys.get('groq', '')
        if not api_key:
            raise RuntimeError('Groq API 키가 설정되지 않았습니다. 설정 창에서 키를 입력해주세요.')
        model = _keys.get('groq_model', '') or AI_MODEL_GROQ

        try:
            import httpx
            import ssl
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            http_client = httpx.Client(verify=False)
            client = groq_sdk.Groq(api_key=api_key, http_client=http_client)
            b64 = self._encode_image(image_path)

            response = client.chat.completions.create(
                model=model,
                messages=[{
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/png;base64,{b64}'},
                        },
                        {'type': 'text', 'text': _PROMPT},
                    ],
                }],
                max_tokens=800,
                timeout=30,
            )
            text = response.choices[0].message.content or ''
            return self._parse_text(text, provider='groq')

        except groq_sdk.RateLimitError:
            raise QuotaExceededError('groq')
        except groq_sdk.AuthenticationError:
            raise RuntimeError('Groq API 키가 유효하지 않습니다. 설정 창에서 키를 다시 확인해주세요.')


