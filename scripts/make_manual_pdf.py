"""D2R Traderie Tracker 사용자 매뉴얼 PDF 생성"""
from fpdf import FPDF, XPos, YPos
from pathlib import Path

FONT_R = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"
OUT    = Path(__file__).parent.parent / "dist" / "D2R_Tracker_Manual.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

C_BG  = (18, 18, 18)
C_SEC = (180,140, 60)
C_SUB = (100,180,100)
C_TXT = (220,220,220)
C_MUT = (140,140,140)
C_RED = (220, 80, 80)
LM    = 15   # left margin mm


class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("M",  "", FONT_R)
        self.add_font("M",  "B", FONT_B)
        self.set_margins(LM, 15, 15)
        self.set_auto_page_break(True, margin=20)

    # ── 배경 ──────────────────────────────────────────────────────────
    def header(self):
        self.set_fill_color(*C_BG)
        self.rect(0, 0, 210, 297, "F")

    # ── 요소 헬퍼 ────────────────────────────────────────────────────
    def h0(self, text):
        """페이지 제목"""
        self.set_font("M", "B", 20)
        self.set_text_color(*C_SEC)
        self.cell(0, 13, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        self.ln(2)

    def h1(self, text):
        """섹션 헤더"""
        self.ln(4)
        self.set_fill_color(50, 40, 10)
        self.set_draw_color(*C_SEC)
        self.set_line_width(0.5)
        self.set_font("M", "B", 12)
        self.set_text_color(*C_SEC)
        self.set_x(LM)
        self.cell(0, 9, f"  {text}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True, border="B")
        self.ln(2)

    def h2(self, text):
        """서브섹션"""
        self.set_font("M", "B", 10)
        self.set_text_color(*C_SUB)
        self.set_x(LM)
        self.cell(0, 7, f"[ {text} ]", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def p(self, text, indent=0):
        """본문"""
        self.set_font("M", "", 10)
        self.set_text_color(*C_TXT)
        self.set_x(LM + indent)
        self.multi_cell(0, 6, text)

    def li(self, text, indent=4):
        """리스트"""
        self.set_font("M", "", 10)
        self.set_text_color(*C_TXT)
        self.set_x(LM + indent)
        self.multi_cell(0, 6, f"- {text}")

    def note(self, text, indent=4):
        """주석"""
        self.set_font("M", "", 9)
        self.set_text_color(*C_MUT)
        self.set_x(LM + indent)
        self.multi_cell(0, 5.5, f"* {text}")

    def warn(self, text, indent=4):
        """경고"""
        self.set_font("M", "B", 10)
        self.set_text_color(*C_RED)
        self.set_x(LM + indent)
        self.multi_cell(0, 6, f"! {text}")

    def kv(self, key, val, kw=32):
        """키-값 행"""
        self.set_x(LM + 4)
        self.set_font("M", "B", 10)
        self.set_text_color(*C_SUB)
        self.cell(kw, 6.5, key, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("M", "", 10)
        self.set_text_color(*C_TXT)
        self.multi_cell(0, 6.5, val)

    def step(self, num, text):
        """번호 단계"""
        self.set_x(LM)
        self.set_font("M", "B", 11)
        self.set_text_color(*C_SEC)
        self.cell(8, 7, f"{num}.", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("M", "", 10)
        self.set_text_color(*C_TXT)
        self.multi_cell(0, 6.5, text)
        self.ln(1)

    def table_head(self, cols, widths):
        self.set_x(LM)
        self.set_fill_color(40, 35, 10)
        self.set_font("M", "B", 9)
        self.set_text_color(*C_SEC)
        for col, w in zip(cols, widths):
            self.cell(w, 7, f" {col}", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln()

    def table_row(self, cols, widths):
        self.set_x(LM)
        self.set_fill_color(28, 28, 28)
        self.set_font("M", "", 9)
        self.set_text_color(*C_TXT)
        for col, w in zip(cols, widths):
            self.cell(w, 7, f" {col}", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln()

    def divider(self):
        self.ln(3)
        self.set_draw_color(*C_MUT)
        self.set_line_width(0.2)
        self.line(LM, self.get_y(), 195, self.get_y())
        self.ln(4)

    def code(self, text):
        self.set_fill_color(30, 30, 30)
        self.set_font("M", "B", 10)
        self.set_text_color(*C_SEC)
        self.set_x(LM + 4)
        self.cell(0, 8, f"  {text}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)


pdf = PDF()

# ═══════════════════════════════════════════════════════════════════
# 표지
# ═══════════════════════════════════════════════════════════════════
pdf.add_page()
pdf.ln(55)
pdf.set_font("M", "B", 30)
pdf.set_text_color(*C_SEC)
pdf.cell(0, 18, "D2R Traderie Tracker", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

pdf.set_font("M", "", 15)
pdf.set_text_color(*C_TXT)
pdf.cell(0, 11, "사용자 매뉴얼", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

pdf.ln(6)
pdf.set_font("M", "", 11)
pdf.set_text_color(*C_MUT)
pdf.cell(0, 8, "디아블로2 레저렉션  아이템 시세 자동 조회 프로그램", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

pdf.ln(35)
pdf.set_font("M", "", 10)
pdf.cell(0, 7, "traderie.com 기반  |  PaddleOCR / AI Vision 지원", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

# ═══════════════════════════════════════════════════════════════════
# 1장 : 기본 사용법
# ═══════════════════════════════════════════════════════════════════
pdf.add_page()
pdf.h0("기본 사용법")

pdf.h1("시작 순서")
pdf.step(1, "최초 실행 시 PaddleOCR 모델 다운로드 화면이 나타납니다.\n'다운로드' 버튼을 눌러 설치하세요.  (약 300MB, 최초 1회)")
pdf.step(2, "'설정' 탭에서 캡처키, 글자색 등 본인 환경에 맞게 설정하세요.")
pdf.step(3, "디아블로2 레저렉션 실행 후, 화면 상단 프로세스 목록에서 게임을 선택하세요.")
pdf.step(4, "'실행' 버튼을 누르면 프로그램이 트레이로 최소화됩니다.")
pdf.step(5, "게임 중 아이템을 획득하면 설정한 캡처키를 눌러주세요.\n시세 정보가 오버레이로 표시됩니다.")

pdf.divider()
pdf.h1("무료 / 유료 비교")
pdf.table_head(["구분",        "무료버전",       "유료버전"     ], [40, 65, 65])
pdf.table_row( ["OCR 방식",    "PaddleOCR (로컬)","AI Vision (클라우드)"], [40, 65, 65])
pdf.table_row( ["사용 횟수",   "실행당 20회",    "무제한"       ], [40, 65, 65])
pdf.table_row( ["즐겨찾기 갱신","수동만 가능",   "자동 갱신 지원"], [40, 65, 65])
pdf.table_row( ["오버레이",    "공통 지원",      "공통 지원"    ], [40, 65, 65])
pdf.ln(3)
pdf.note("무료버전도 충분히 사용 가능합니다.  OCR 인식률 차이는 크지 않습니다.")

# ═══════════════════════════════════════════════════════════════════
# 2장 : 탭별 사용법
# ═══════════════════════════════════════════════════════════════════
pdf.add_page()
pdf.h0("탭별 상세 사용법")

pdf.h1("시세파악 탭")
pdf.kv("시즌",       "래더 / 스탠다드 선택  (복수선택 불가)")
pdf.kv("모드",       "소프트코어 / 하드코어 선택  (복수선택 불가)")
pdf.kv("버전",       "게임 버전 선택  (복수선택 가능)")
pdf.kv("가격시즌",   "가격 기준 시즌 선택  (복수선택 불가)")
pdf.kv("지우기",     "현재 스캔 기록 전체 삭제")
pdf.kv("즐겨찾기",   "즐겨찾기 탭에 추가  (지우기로 삭제해도 즐겨찾기는 유지됨)")
pdf.kv("재조회",     "현재 스캔 목록 시세 재조회")
pdf.ln(1)
pdf.note("항목을 더블클릭하면 Traderie 링크를 브라우저로 열어줍니다.")

pdf.h1("즐겨찾기 탭")
pdf.li("시세파악 탭에서 '즐겨찾기' 버튼으로 추가한 아이템 목록입니다.")
pdf.li("목록 선택 시 오른쪽에서 옵션 수치를 변경할 수 있습니다.")
pdf.li("'조회' 버튼으로 시세를 재조회합니다.")
pdf.li("항목 더블클릭 시 Traderie 링크를 열어줍니다.")

pdf.h1("설정 탭")
pdf.kv("추출키",      "캡처를 실행할 키  (스킬키와 겹치지 않도록 설정)")
pdf.kv("OCR 설정",    "무료: PaddleOCR  /  유료: AI 방식 선택 가능")
pdf.kv("최대값 여유", "옵션 검색 범위 설정")
pdf.note("예) 175 방어 + 최대값여유 5  ->  175~180 범위로 Traderie 검색", indent=36)
pdf.kv("로그",        "Traderie 링크 로그 파일 저장 여부 설정")
pdf.kv("데이터",      "GitHub 아이템 목록 갱신  (앱 시작 시 자동 갱신)")
pdf.kv("유료인증",    "유료 키 입력란  (별도 구매)")
pdf.kv("즐겨찾기갱신","즐겨찾기 가격 자동 갱신 주기  (유료 전용)")
pdf.kv("오버레이",    "가격 표시 위치 / 배경색 / 글자색 / 미리보기 설정")

# ═══════════════════════════════════════════════════════════════════
# 3장 : AI OCR 설정
# ═══════════════════════════════════════════════════════════════════
pdf.add_page()
pdf.h0("AI OCR 설정  (유료버전)")

pdf.p("유료버전에서는 클라우드 AI를 활용한 OCR을 사용할 수 있습니다.\nGroq API는 무료 할당량이 넉넉해 실질적으로 무료로 사용 가능합니다.")
pdf.ln(3)

pdf.h1("Groq API 키 발급 방법")
pdf.step(1, "구글에서  'groq api 키 발급'  검색 후  console.groq.com  접속")
pdf.step(2, "Google 계정으로 가입  (새 계정 사용 권장)")
pdf.step(3, "상단 메뉴에서  'API Keys'  ->  '+Create API Key'  버튼 클릭")
pdf.step(4, "키 이름 입력  ->  Expiration : 'No expiration'  ->  Submit")
pdf.step(5, "발급된 키를  'Copy' 버튼으로 복사  (재조회 불가, 반드시 저장)")
pdf.step(6, "프로그램 실행 -> 유료인증 -> OCR 설정을 'AI' 로 변경\n'Groq API' 입력란에 복사한 키 붙여넣기")

pdf.ln(1)
pdf.note("키 형태 예시 :  gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
pdf.ln(2)
pdf.note("무료 할당량 소진 시 Gemini, GPT 등 다른 AI로 자동 전환됩니다.")

pdf.divider()
pdf.h1("AI 제공사 우선순위 변경")
pdf.p("설정 탭 -> AI 설정에서 위아래 버튼으로 호출 순서를 변경할 수 있습니다.")
pdf.ln(2)
pdf.kv("Groq (Llama 4)", "기본 추천  -  빠르고 무료 할당량 넉넉",  kw=42)
pdf.kv("Gemini",         "Google AI  -  안정적",                   kw=42)
pdf.kv("GPT-4o",         "OpenAI  -  가장 정확하나 유료",          kw=42)
pdf.kv("HuggingFace",    "오픈소스 모델",                          kw=42)

# ═══════════════════════════════════════════════════════════════════
# 4장 : 완전 삭제 방법
# ═══════════════════════════════════════════════════════════════════
pdf.add_page()
pdf.h0("완전 삭제 방법")

pdf.p("프로그램을 완전히 제거하려면 아래 항목을 모두 삭제해주세요.")
pdf.ln(3)

pdf.h1("삭제 대상 목록")
pdf.table_head(["항목",             "경로",                                       "해당 조건"         ], [38, 90, 42])
pdf.table_row( ["프로그램 폴더",    "압축 해제한 D2R_Tracker 폴더 전체",         "항상"              ], [38, 90, 42])
pdf.table_row( ["설정 파일",        "tracker_config.json  (exe 옆)",              "항상"              ], [38, 90, 42])
pdf.table_row( ["API 키 파일",      "tracker_config_keys.json  (exe 옆)",         "AI 키 저장 시"     ], [38, 90, 42])
pdf.table_row( ["PaddleOCR 모델",  r"%USERPROFILE%\.paddleocr\  (~300MB)",        "PaddleOCR 사용 시" ], [38, 90, 42])
pdf.table_row( ["로그 파일",        r"내 문서\  (*.txt)",                          "로그 저장 사용 시" ], [38, 90, 42])
pdf.table_row( ["임시 캡처",       r"%TEMP%\d2r_*.png",                           "비정상 종료 시"    ], [38, 90, 42])

pdf.ln(5)
pdf.h1("PaddleOCR 모델 폴더 삭제")
pdf.p("Windows 탐색기 주소창에 아래 경로를 입력 후 폴더 삭제:")
pdf.ln(1)
pdf.code(r"%USERPROFILE%\.paddleocr")

pdf.h1("임시 파일 정리")
pdf.p("Windows 탐색기 주소창에 아래 경로를 입력:")
pdf.ln(1)
pdf.code(r"%TEMP%")
pdf.note("'d2r_' 로 시작하는 .png 파일을 찾아 삭제하면 됩니다.")

pdf.ln(6)
pdf.warn("설정 파일(tracker_config.json)에는 AI API 키가 저장되어 있습니다.")
pdf.warn("PC를 다른 사람과 공유한다면 반드시 삭제해주세요.")


pdf.output(str(OUT))
print(f"PDF 생성 완료: {OUT}")
