import streamlit as st

def inject_ace_hotel_css():
    """
    Stitch의 Ace Hotel Chatbot Admin 디자인 시스템을 반영한 글로벌 CSS Injection.
    - Pretendard 웹폰트 전역 적용
    - JetBrains Mono 메타데이터/배지 폰트
    - Off-white (#FAFAF9), Charcoal (#1C1917), Utility Orange (#F97316) 포인트
    - Brutalist-lite Industrial B2B SaaS 카드 테두리 및 그림자
    """
    st.markdown("""
    <!-- Pretendard & JetBrains Mono CDN 폰트 불러오기 -->
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Source+Serif+4:wght@600;700&display=swap" rel="stylesheet">

    <style>
        /* ==========================================================
           글로벌 변수 및 베이스 스타일
           ========================================================== */
        :root {
            --bg-color: #FAFAF9;              /* 따뜻한 종이 질감 오프화이트 */
            --card-bg: #FFFFFF;               /* 순백색 컨테이너 */
            --primary: #F97316;               /* 유틸리티 오렌지 핵심 포인트 */
            --primary-hover: #EA580C;         /* 오렌지 호버 색상 */
            --text-main: #1C1917;             /* 짙은 차콜 텍스트 */
            --text-muted: #78716C;            /* 은은한 묵음 텍스트 */
            --border-color: #D6D3D1;          /* 1px 정밀 테두리 */
            --border-subtle: #E7E5E4;         /* 보조 테두리 */
            --olive-accent: #726D42;          /* 올리브 드랩 서브 포인트 */
            --font-body: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --font-serif: 'Source Serif 4', Georgia, serif;
            --border-radius-sm: 4px;
            --border-radius-md: 6px;
            --border-radius-lg: 10px;
        }

        /* 전체 앱 폰트 및 배경 적용 */
        html, body, [class*="st-"], .stApp {
            font-family: var(--font-body) !important;
            background-color: var(--bg-color) !important;
            color: var(--text-main) !important;
        }

        /* 메인 영역 패딩 조정 */
        .main .block-container {
            padding-top: 2rem !important;
            padding-bottom: 3rem !important;
            max-width: 1300px;
        }

        /* ==========================================================
           헤더 및 섹션 타이틀 스타일링
           ========================================================== */
        h1 {
            font-family: var(--font-body) !important;
            font-weight: 800 !important;
            letter-spacing: -0.03em !important;
            color: var(--text-main) !important;
            font-size: 2.1rem !important;
            margin-bottom: 0.5rem !important;
        }

        h2, h3 {
            font-family: var(--font-body) !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em !important;
            color: var(--text-main) !important;
        }

        h4, h5, h6 {
            font-family: var(--font-body) !important;
            font-weight: 600 !important;
        }

        /* 모노스페이스 배지 스타일 */
        .ace-badge {
            font-family: var(--font-mono);
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 0.25rem 0.6rem;
            border-radius: 4px;
            display: inline-block;
            margin-bottom: 0.5rem;
        }

        .ace-badge-orange {
            background-color: rgba(249, 115, 22, 0.12);
            color: #C2410C;
            border: 1px solid rgba(249, 115, 22, 0.3);
        }

        .ace-badge-olive {
            background-color: rgba(114, 109, 66, 0.12);
            color: #575332;
            border: 1px solid rgba(114, 109, 66, 0.3);
        }

        .ace-badge-charcoal {
            background-color: #1C1917;
            color: #FAFAF9;
        }

        /* ==========================================================
           사이드바 스타일링 (Ace Hotel Brutalist Bar)
           ========================================================== */
        [data-testid="stSidebar"] {
            background-color: #F3F4F3 !important;
            border-right: 1px solid var(--border-color) !important;
        }

        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {
            font-size: 1.25rem !important;
        }

        /* 라디오 버튼 메뉴 스타일 */
        [data-testid="stSidebar"] .stRadio > div {
            gap: 6px;
        }

        [data-testid="stSidebar"] .stRadio label {
            background-color: var(--card-bg);
            border: 1px solid var(--border-subtle);
            border-radius: var(--border-radius-md);
            padding: 0.65rem 0.9rem !important;
            font-weight: 600 !important;
            font-size: 0.92rem !important;
            cursor: pointer;
            transition: all 0.15s ease-in-out;
            color: var(--text-main) !important;
            margin-bottom: 2px;
        }

        [data-testid="stSidebar"] .stRadio label:hover {
            border-color: var(--primary) !important;
            background-color: #FFF7ED !important;
            transform: translateX(2px);
        }

        [data-testid="stSidebar"] .stRadio [data-checked="true"] + div {
            font-weight: 700 !important;
        }

        /* ==========================================================
           카드 및 컨테이너 (Brutalist Container Cards)
           ========================================================== */
        div[data-testid="column"] > div > div[data-testid="stVerticalBlock"] > div,
        .stForm {
            background-color: var(--card-bg);
            border-radius: var(--border-radius-md);
            padding: 1.25rem;
            border: 1px solid var(--border-color);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.03);
            margin-bottom: 1rem;
        }

        /* ==========================================================
           버튼 컴포넌트 (Brutalist Orange & Charcoal Buttons)
           ========================================================== */
        .stButton > button {
            background-color: var(--primary) !important;
            color: #FFFFFF !important;
            border: 1px solid #EA580C !important;
            border-radius: var(--border-radius-md) !important;
            padding: 0.55rem 1.25rem !important;
            font-weight: 700 !important;
            font-family: var(--font-body) !important;
            letter-spacing: -0.01em;
            transition: all 0.15s ease-in-out !important;
            box-shadow: 0 2px 0px rgba(28, 25, 23, 0.1);
        }

        .stButton > button:hover {
            background-color: var(--primary-hover) !important;
            border-color: #C2410C !important;
            box-shadow: 0 4px 12px rgba(249, 115, 22, 0.25) !important;
            transform: translateY(-1px);
        }

        /* 폼 제출 버튼 */
        .stFormSubmitButton > button {
            background-color: var(--text-main) !important;
            color: #FFFFFF !important;
            border: 1px solid var(--text-main) !important;
            font-weight: 700 !important;
            width: 100%;
        }

        .stFormSubmitButton > button:hover {
            background-color: var(--primary) !important;
            border-color: var(--primary) !important;
            box-shadow: 0 4px 12px rgba(249, 115, 22, 0.2) !important;
        }

        /* Secondary/Primary Type Button Overrides */
        button[kind="primary"], button[type="primary"] {
            background-color: var(--primary) !important;
        }

        button[kind="secondary"], button[type="secondary"] {
            background-color: #FFFFFF !important;
            color: var(--text-main) !important;
            border: 1px solid var(--border-color) !important;
        }

        button[kind="secondary"]:hover, button[type="secondary"]:hover {
            background-color: #F5F5F4 !important;
            border-color: var(--text-main) !important;
        }

        /* ==========================================================
           입력 폼 및 테이블 컨트롤
           ========================================================== */
        .stTextInput input, .stSelectbox select, .stTextArea textarea {
            font-family: var(--font-body) !important;
            border-radius: var(--border-radius-md) !important;
            border: 1px solid var(--border-color) !important;
            background-color: #FAFAF9 !important;
            color: var(--text-main) !important;
            padding: 0.5rem 0.75rem !important;
        }

        .stTextInput input:focus, .stSelectbox select:focus, .stTextArea textarea:focus {
            border-color: var(--primary) !important;
            box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.2) !important;
            background-color: #FFFFFF !important;
        }

        /* 모노스페이스 데이터 입력용 */
        .mono-input input {
            font-family: var(--font-mono) !important;
        }

        /* 슬라이더 커스텀 */
        .stSlider > div > div > div > div {
            background-color: var(--primary) !important;
        }

        /* 메트릭 카드 스타일링 */
        [data-testid="stMetricValue"] {
            font-family: var(--font-mono) !important;
            font-weight: 700 !important;
            color: var(--primary) !important;
        }

        [data-testid="stMetricLabel"] {
            font-family: var(--font-body) !important;
            font-weight: 600 !important;
            color: var(--text-muted) !important;
        }

        /* 모던 익스팬더 */
        .streamlit-expanderHeader {
            font-family: var(--font-body) !important;
            font-weight: 700 !important;
            border-radius: var(--border-radius-md) !important;
            background-color: #FAFAF9 !important;
            border: 1px solid var(--border-subtle) !important;
        }

        /* 코드 블록 스타일 */
        code, pre {
            font-family: var(--font-mono) !important;
            border-radius: var(--border-radius-sm) !important;
        }

        /* 데이터 프레임 / 에디터 */
        .stDataFrame {
            border: 1px solid var(--border-color) !important;
            border-radius: var(--border-radius-md) !important;
            overflow: hidden;
        }

        /* 하단 푸터 커스텀 */
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}

        /* 상단 기관 헤더 전용 대시보드 카드 */
        .header-card {
            background-color: #FFFFFF !important;
            color: #1C1917 !important;
            padding: 1.25rem 1.5rem !important;
            border-radius: var(--border-radius-md) !important;
            border: 1px solid var(--border-color) !important;
            border-left: 6px solid var(--primary) !important;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04) !important;
            margin-bottom: 1.5rem !important;
        }

        .header-card h2 {
            color: #1C1917 !important;
            margin: 0 0 0.3rem 0 !important;
            font-size: 1.6rem !important;
            font-weight: 800 !important;
            display: block !important;
        }

        .header-card p {
            color: #57534E !important;
            margin: 0 !important;
            font-size: 0.95rem !important;
            display: block !important;
        }
    </style>
    """, unsafe_allow_html=True)
