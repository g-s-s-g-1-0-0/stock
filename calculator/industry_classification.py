"""Display-friendly stock category and industry classification."""

from __future__ import annotations

from typing import Any

CATEGORY_VALUES = ("가치주", "혼합주", "성장주", "스윙주")

CURATED_BY_TICKER: dict[str, tuple[str, str]] = {
    "000660": ("성장주", "반도체, 메모리, HBM, AI 메모리, DRAM"),
    "005930": ("혼합주", "반도체, 메모리·파운드리, 스마트폰, 소비자 가전"),
    "277810": ("성장주", "협동로봇, 자동화, AI 로보틱스"),
    "034020": ("성장주", "원전, 에너지, SMR, 가스터빈"),
    "015760": ("가치주", "원전·에너지, 전력망, AI 기반 전력수요 관리"),
    "005380": ("가치주", "자동차, 전기차, 수소차, 로보틱스"),
    "012450": ("성장주", "방산, 항공엔진, K-방산, 우주 산업·발사체"),
    "042660": ("성장주", "조선, 방산, LNG선, 잠수함"),
    "042700": ("성장주", "반도체 장비, HBM 패키징, TC본더, 열압착 본딩"),
    "096770": ("성장주", "정유, 전기차 배터리, 데이터센터 냉각·전력 인프라"),
    "009150": ("혼합주", "MLCC, 패키지기판, 카메라 모듈"),
    "000270": ("가치주", "자동차, 전기차, PBV"),
    "247540": ("성장주", "2차전지, 양극재, NCM"),
    "376900": ("성장주", "바이오, 3D 바이오프린팅, 재생의료"),
    "004020": ("성장주", "철강, 자동차강판, 후판, 건설·조선용 강재"),
    "329180": ("성장주", "조선, 해양 플랜트, 엔진·기계"),
    "375500": ("성장주", "건설, 플랜트(EPC), 토목·주택"),
    "086280": ("성장주", "종합물류, 해운, 완성차 운송, 3PL·SCM"),
    "000720": ("성장주", "건설, 토목·인프라, 주택·건축, 원전·신재생"),
    "353200": ("성장주", "반도체 패키지기판, PCB, 서버·네트워크, 전장"),
    "011070": ("성장주", "카메라 모듈, 기판소재, 자동차 전장, AI 반도체 기판"),
    "278470": ("성장주", "뷰티테크, 화장품·건기식, 홈 뷰티 디바이스, D2C 브랜드"),
    "079550": ("성장주", "방산, 유도무기, 레이더, 방산 수출"),
    "HOOD": ("성장주", "핀테크, 리테일 브로커리지, 암호화폐 거래"),
    "AVGO": ("혼합주", "반도체, 네트워크·AI 인프라, ASIC, 광트랜시버"),
    "AMD": ("성장주", "반도체, CPU·GPU, AI 가속기, 데이터센터 GPU"),
    "A": ("성장주", "생명과학·분석 장비, 계측, 진단·실험실 장비"),
    "AAPL": ("혼합주", "스마트폰, 소비자 전자, 서비스, 자체 반도체"),
    "MSFT": ("혼합주", "소프트웨어·클라우드, AI, Azure, Copilot"),
    "GOOG": ("혼합주", "AI, 광고, 클라우드, Waymo, TPU, Gemini"),
    "GOOGL": ("혼합주", "AI, 광고, 클라우드, Waymo, TPU, Gemini"),
    "NVDA": ("성장주", "반도체, AI GPU, 데이터센터, CUDA"),
    "TSLA": ("성장주", "전기차, 에너지, AI, FSD, 로보택시, 로봇(Optimus)"),
    "MU": ("혼합주", "반도체, 메모리, DRAM, NAND, HBM"),
    "LRCX": ("혼합주", "반도체 장비, 식각·증착"),
    "ON": ("성장주", "반도체, 전력·자동차용, SiC 전력반도체"),
    "SNDK": ("가치주", "반도체, 플래시 스토리지, NAND, SSD"),
    "ASTS": ("성장주", "우주 산업, 위성통신, LEO 위성, D2D 통신"),
    "AVAV": ("성장주", "방산, 드론·무인기(UAS), 자율무기"),
    "IONQ": ("성장주", "양자컴퓨팅, 이온트랩, 양자 네트워크"),
    "RKLB": ("성장주", "우주 산업, 소형 발사체, 위성 배포"),
    "PLTR": ("성장주", "AI·빅데이터·방산, AIP, 정부계약, AI 플랫폼"),
    "APP": ("성장주", "모바일 광고·AI, 애드테크, AI 최적화 엔진"),
    "SOXL": ("성장주", "반도체 레버리지 ETF"),
    "TSLL": ("성장주", "테슬라 2x 레버리지 ETF, 전기차·AI 테마"),
    "TE": ("성장주", "에너지, 태양광 모듈·배터리 저장, AI 데이터센터 전력"),
    "ONDS": ("성장주", "방산·드론, 산업용 무선통신, 철도 자동화"),
    "BE": ("성장주", "AI 인프라, 에너지, 연료전지·수소, 데이터센터 전력"),
    "PL": ("성장주", "우주 산업, 위성 지구관측 데이터, 위성 이미지"),
    "VRT": ("성장주", "AI 인프라, 데이터센터 전력·냉각, 액침냉각, UPS"),
    "LITE": ("성장주", "광통신·데이터센터용 광부품, 트랜시버, 광송수신기"),
    "TER": ("혼합주", "반도체 테스트 장비, 자동화 테스트, 협동로봇"),
    "ANET": ("혼합주", "네트워크, 데이터센터 스위칭, AI 네트워킹, 이더넷 스위치"),
    "IREN": ("성장주", "AI 컴퓨팅·비트코인 채굴, 데이터센터, GPU 클라우드, HPC"),
    "NBIS": ("성장주", "AI 인프라, AI 클라우드, GPU 클러스터, 데이터센터"),
    "LPTH": ("성장주", "광학·포토닉스, 적외선·열화상 부품, 방산 광학"),
    "CONL": ("스윙주", "가상화폐, 핀테크, 코인베이스 2x 레버리지 ETF"),
    "GLW": ("성장주", "광통신 인프라, 특수유리, 광케이블, AI 데이터센터 광섬유"),
    "VST": ("성장주", "전력 발전, 원전·가스, AI 데이터센터 전력수요, AI 인프라"),
    "ASX": ("성장주", "반도체 후공정, 패키징·테스트·EMS, 첨단패키징"),
    "CRCL": ("성장주", "가상화폐, 핀테크, 스테이블코인, USDC"),
    "SGML": ("성장주", "리튬, 2차전지 원자재, EV 배터리 소재"),
    "AEHR": ("성장주", "반도체, 반도체 테스트 장비, 후공정 검사"),
    "MP": ("성장주", "희토류, EV 모터 소재, 자석 원료"),
    "PLAB": ("성장주", "반도체, 포토마스크, 첨단 노드, 파운드리 공급망"),
    "SKYT": ("성장주", "미국 파운드리, 특수공정, 국방·AI 엣지 반도체"),
    "SMTC": ("성장주", "광인터커넥트, 데이터센터 통신, AI 연결성"),
    "COHR": ("성장주", "광학·레이저, 광인터커넥트, AI 데이터센터 부품"),
    "CIEN": ("성장주", "광네트워크, 장거리 전송, 데이터센터 연결"),
    "FORM": ("성장주", "반도체 테스트·계측, 프로브 카드·장비"),
    "CRDO": ("성장주", "데이터센터, AI 인프라, 고속 인터커넥트"),
    "ACLS": ("성장주", "반도체 장비, 이온주입기"),
    "ONTO": ("성장주", "반도체 공정 제어·검사, 메트롤로지, 첨단 패키징"),
    "INTC": ("성장주", "반도체, 데이터센터·AI 서버 칩, 파운드리, 네트워크·5G"),
    "STX": ("성장주", "AI 인프라, 대용량 HDD, 스토리지, 데이터센터 저장장치"),
}

CURATED_BY_NAME: tuple[tuple[str, tuple[str, str]], ...] = (
    ("삼성전자", ("혼합주", "반도체, 메모리·파운드리, 스마트폰, 소비자 가전")),
    ("SK하이닉스", ("성장주", "반도체, 메모리, HBM, AI 메모리, DRAM")),
    ("레인보우로보틱스", ("성장주", "협동로봇, 자동화, AI 로보틱스")),
    ("두산에너빌리티", ("성장주", "원전, 에너지, SMR, 가스터빈")),
    ("한국전력", ("가치주", "원전·에너지, 전력망, AI 기반 전력수요 관리")),
    ("현대차", ("가치주", "자동차, 전기차, 수소차, 로보틱스")),
    ("한화에어로스페이스", ("성장주", "방산, 항공엔진, K-방산, 우주 산업·발사체")),
    ("한화오션", ("성장주", "조선, 방산, LNG선, 잠수함")),
    ("한미반도체", ("성장주", "반도체 장비, HBM 패키징, TC본더, 열압착 본딩")),
    ("SK이노베이션", ("성장주", "정유, 전기차 배터리, 데이터센터 냉각·전력 인프라")),
    ("Samsung", ("혼합주", "반도체, 메모리·파운드리, 스마트폰, 소비자 가전")),
    ("NVIDIA", ("성장주", "반도체, AI GPU, 데이터센터, CUDA")),
    ("Tesla", ("성장주", "전기차, 에너지, AI, FSD, 로보택시, 로봇(Optimus)")),
    ("Alphabet", ("혼합주", "AI, 광고, 클라우드, Waymo, TPU, Gemini")),
    ("Microsoft", ("혼합주", "소프트웨어·클라우드, AI, Azure, Copilot")),
    ("Broadcom", ("혼합주", "반도체, 네트워크·AI 인프라, ASIC, 광트랜시버")),
    ("Direxion Daily Semiconductor", ("성장주", "반도체 레버리지 ETF")),
    ("2X Ether", ("스윙주", "가상화폐, 핀테크, 이더리움 2x 레버리지 ETF")),
    ("Solana", ("스윙주", "가상화폐, 핀테크, Solana 2x 레버리지 ETF")),
)

KEYWORD_RULES: tuple[tuple[tuple[str, ...], tuple[str, str]], ...] = (
    (("신탁", "집합투자", "리츠"), ("가치주", "리츠·인프라펀드, 부동산·대체투자")),
    (("케미컬", "화학", "합성고무", "플라스틱", "기초 화학"), ("성장주", "화학, 소재, 합성수지·정밀화학")),
    (("비철금속", "구리", "알루미늄", "금속"), ("성장주", "비철금속, 구리·알루미늄, 산업 소재")),
    (("전선", "케이블", "절연선"), ("성장주", "전력 인프라, 전선·케이블, 전력망")),
    (("소프트웨어", "보안", "인증", "클라우드"), ("성장주", "소프트웨어·클라우드, 보안, AI 플랫폼")),
    (("신발", "의류", "패션"), ("혼합주", "소비재, 패션·의류, 브랜드·OEM")),
    (("식품", "음료", "푸드", "소매"), ("혼합주", "소비재, 식품·유통, 브랜드 커머스")),
    (("HBM", "DRAM", "NAND", "메모리"), ("성장주", "반도체, 메모리, DRAM, NAND, HBM")),
    (("반도체", "파운드리", "포토마스크", "패키지기판", "웨이퍼", "PCB"), ("성장주", "반도체, 반도체 장비·소재, 첨단 패키징")),
    (("전기차", "배터리", "양극재", "2차전지", "리튬"), ("성장주", "2차전지, 전기차 배터리, 배터리 소재")),
    (("로봇", "로보틱스", "자동화"), ("성장주", "로봇, 자동화, AI 로보틱스")),
    (("방산", "무기", "유도", "레이더", "항공엔진", "드론", "무인기"), ("성장주", "방산, 항공우주, 드론·무인체계")),
    (("조선", "LNG", "선박", "잠수함"), ("성장주", "조선, LNG선, 해양 플랜트, 방산 선박")),
    (("원전", "SMR", "발전", "전력", "가스터빈"), ("성장주", "원전·에너지, 전력 인프라, 발전 설비")),
    (("데이터센터", "AI 인프라", "냉각", "UPS", "광통신", "트랜시버"), ("성장주", "AI 인프라, 데이터센터 전력·냉각, 광통신")),
    (("자동차", "완성차", "수소차", "PBV"), ("가치주", "자동차, 전기차, 모빌리티")),
    (("건설", "토목", "플랜트", "EPC", "주택"), ("성장주", "건설, 토목·인프라, 플랜트")),
    (("철강", "후판", "강재"), ("성장주", "철강, 자동차강판, 조선·건설용 강재")),
    (("물류", "해운", "운송", "SCM"), ("성장주", "종합물류, 해운, 3PL·SCM")),
    (("바이오", "의약품", "재생의료", "헬스케어"), ("성장주", "바이오, 제약·헬스케어")),
    (("화장품", "뷰티", "건기식"), ("성장주", "뷰티테크, 화장품·건기식, D2C 브랜드")),
    (("은행", "보험", "증권", "금융", "지주"), ("가치주", "금융, 은행·보험·증권, 지주회사")),
    (("REIT", "리츠"), ("가치주", "리츠, 부동산 임대, 배당형 자산")),
    (("ETF", "2X", "3X", "Bull", "Bear", "Daily"), ("스윙주", "레버리지·테마 ETF")),
    (("Acquisition", "SPAC", "Warrant", "Rights", "Units"), ("스윙주", "스팩·권리증권, 이벤트성 상장상품")),
    (("Bitcoin", "Ether", "Crypto", "Coin", "Solana", "블록체인", "가상화폐"), ("스윙주", "가상화폐, 핀테크, 블록체인")),
    (("Software", "Cloud", "AI", "Artificial Intelligence"), ("성장주", "소프트웨어·클라우드, AI 플랫폼")),
    (("Semiconductor", "Micro Devices", "Optoelectronics", "Photonics"), ("성장주", "반도체, 광전자·포토닉스, 데이터센터")),
    (("Energy", "Solar", "Fuel Cell", "Hydrogen"), ("성장주", "에너지, 신재생·수소, 데이터센터 전력")),
    (("Electric", "Auto", "Motor"), ("성장주", "전기차, 자동차, 모빌리티")),
    (("Pharma", "Therapeutics", "Biologics", "Bio", "Medical", "Health", "AbbVie"), ("성장주", "바이오, 제약·헬스케어")),
    (("Bancorp", "Bank", "Financial", "Capital", "Asset Management", "AllianceBernstein"), ("가치주", "금융, 은행·자산운용·증권")),
    (("Insurance", "American Corporation"), ("가치주", "보험·금융, 배당형 가치주")),
    (("REIT", "Realty", "Assets Trust", "Properties"), ("가치주", "리츠, 부동산 임대, 배당형 자산")),
    (("Gold", "Lithium", "Mining", "Materials", "Alcoa"), ("성장주", "원자재, 광산·금속 소재, 배터리 공급망")),
    (("Education", "Creativity"), ("성장주", "교육 서비스, 에듀테크")),
    (("Beverage", "Ambev"), ("혼합주", "소비재, 음료·주류, 글로벌 브랜드")),
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _valid(value: Any) -> str:
    cleaned = _clean(value)
    return "" if cleaned in ("", "-") else cleaned


def _curated(row: dict[str, Any]) -> tuple[str, str] | None:
    ticker = _clean(row.get("ticker")).upper()
    name = _clean(row.get("name"))
    if ticker in CURATED_BY_TICKER:
        return CURATED_BY_TICKER[ticker]
    for keyword, classification in CURATED_BY_NAME:
        if keyword.lower() in name.lower():
            return classification
    return None


def _rule_based(row: dict[str, Any]) -> tuple[str, str] | None:
    haystack = " ".join(
        _clean(row.get(key))
        for key in ("name", "industry", "rawIndustry", "products", "market")
    )
    lower_haystack = haystack.lower()
    for keywords, classification in KEYWORD_RULES:
        if any(keyword.lower() in lower_haystack for keyword in keywords):
            return classification
    return None


def classify_stock(row: dict[str, Any]) -> dict[str, str]:
    classification = _curated(row) or _rule_based(row)
    if classification:
        category, industry = classification
    else:
        category = "성장주" if row.get("market") == "KR" else "혼합주"
        industry = _valid(row.get("products")) or _valid(row.get("rawIndustry")) or _valid(row.get("industry"))
        if not industry and row.get("market") == "US":
            name = _clean(row.get("name"))
            if any(token in name for token in ("Warrant", "Rights", "Units")):
                category = "스윙주"
                industry = "스팩·권리증권, 이벤트성 상장상품"
            elif "ETF" in name:
                category = "스윙주"
                industry = "ETF, 테마·지수형 상장상품"
            else:
                industry = "해외 보통주, 개별 사업영역 추가 확인 필요"
        if not industry:
            industry = "상장기업, 개별 사업영역 추가 확인 필요"
    if category not in CATEGORY_VALUES:
        category = "성장주"
    return {
        "category": category,
        "industry": industry if industry else "-",
    }
