import io
import os
import re
import math
import random
import pandas as pd
import requests
import streamlit as st
from typing import List, Dict, Any

# PyPDF2 / pypdf 가져오기 시도
try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    try:
        import PyPDF2 as pypdf
        HAS_PYPDF = True
    except ImportError:
        HAS_PYPDF = False

def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """
    업로드된 파일(PDF, TXT, Excel/XLSX)의 확장자를 감지하여 텍스트를 추출합니다.
    """
    ext = filename.split(".")[-1].lower()
    
    if ext == "txt":
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("cp949", errors="ignore")
            
    elif ext == "pdf":
        if not HAS_PYPDF:
            return "[PDF 텍스트 추출 모듈 경고] pypdf 패키지가 로드되지 않았습니다. 기본 바이너리 파싱으로 대체합니다."
        
        try:
            pdf_file = io.BytesIO(file_bytes)
            reader = pypdf.PdfReader(pdf_file)
            extracted_text = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    extracted_text.append(f"--- [페이지 {i+1}] ---\n{page_text}")
            return "\n".join(extracted_text)
        except Exception as e:
            return f"PDF 읽기 오류: {str(e)}"
            
    elif ext in ["xlsx", "xls"]:
        try:
            excel_file = io.BytesIO(file_bytes)
            # sheet_name=None을 지정해야 모든 시트를 {시트명: DataFrame} 딕셔너리로 읽는다.
            # 기본값(sheet_name 생략)은 첫 번째 시트만 읽으므로 다중 시트 파일에서 데이터 누락이 발생한다.
            sheets = pd.read_excel(excel_file, sheet_name=None)
            rows_str = []
            for sheet_name, df in sheets.items():
                for idx, row in df.iterrows():
                    row_items = [f"{col}: {val}" for col, val in row.items() if pd.notna(val)]
                    if row_items:
                        rows_str.append(f"[시트: {sheet_name} / 행 {idx+1}] " + " | ".join(row_items))
            return "\n".join(rows_str)
        except Exception as e:
            return f"Excel 읽기 오류: {str(e)}"
            
    else:
        return f"지원되지 않는 파일 형식입니다: {filename}"

# 운영/추적용 컬럼. 검색 대상 본문에 섞이면 임베딩이 오염되므로 content에서 제외하고
# 별도 필드로 분리한다.
#  - 유형:     A_사실(RAG가 답변할 지식) / B_접수(직원이 받아적을 폼 스펙)
#  - 원본위치: 고객 원본 문서(chatbot_data.hwpx)의 표/행 위치. 각색·오기 추적용
#  - 검증상태: 원본확인 / 고객확인필요
METADATA_COLUMNS = ("유형", "원본위치", "검증상태")

DOC_TYPE_FACT = "A_사실"
DOC_TYPE_INTAKE = "B_접수"


def extract_excel_rows(file_bytes: bytes) -> List[Dict[str, str]]:
    """
    엑셀은 이미 사람이 행 단위로 정리해 둔 원자적 지식 단위이므로,
    chunk_text()의 글자 수 기반 재분할을 거치지 않고 1행 = 1청크로 반환한다.
    시트명이 곧 카테고리가 된다.

    METADATA_COLUMNS는 본문(content)에 넣지 않고 doc_type 등 별도 필드로 반환한다.
    """
    excel_file = io.BytesIO(file_bytes)
    sheets = pd.read_excel(excel_file, sheet_name=None)
    rows = []
    for sheet_name, df in sheets.items():
        # 시트명 앞의 일련번호를 떼고 공백으로 풀어써서, 임베딩이 주제 맥락을
        # 더 잘 붙잡도록 한다("1_활동지원_입사" -> "활동지원 입사").
        topic_label = re.sub(r"^\d+_", "", sheet_name).replace("_", " ")
        for _, row in df.iterrows():
            row_items = [
                f"{col}: {val}" for col, val in row.items()
                if pd.notna(val) and col not in METADATA_COLUMNS
            ]
            if row_items:
                doc_type = row.get("유형")
                rows.append({
                    "category": sheet_name,
                    "content": f"[{topic_label}] " + " | ".join(row_items),
                    "doc_type": doc_type if pd.notna(doc_type) else DOC_TYPE_FACT,
                    "verification": row.get("검증상태") if pd.notna(row.get("검증상태")) else None,
                })
    return rows

def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> List[str]:
    """
    텍스트를 의미 있는 단위(문장/줄 바꿈 기준)로 분할(Chunking)합니다.
    """
    # 줄바꿈 및 문장 구분자로 1차 분할
    sentences = re.split(r'(\n+|\.\s+)', text)
    chunks = []
    current_chunk = []
    current_length = 0
    
    for item in sentences:
        if not item:
            continue
        current_chunk.append(item)
        current_length += len(item)
        
        if current_length >= chunk_size:
            chunks.append("".join(current_chunk).strip())
            # overlap 반영 (뒤쪽 절반 유지)
            overlap_items = current_chunk[-max(1, len(current_chunk)//2):]
            current_chunk = overlap_items
            current_length = sum(len(x) for x in current_chunk)
            
    if current_chunk:
        chunks.append("".join(current_chunk).strip())
        
    return [c for c in chunks if len(c) > 10]

def _get_secret(key: str):
    try:
        val = st.secrets.get(key)
    except Exception:
        val = None
    return val or os.environ.get(key)


def _deterministic_fallback_embedding(text: str, dimension: int = 1536) -> List[float]:
    """
    OpenAI API 키가 없는 데모/Mock 환경을 위한 시드 기반 결정론적 벡터.
    실제 의미(semantic) 유사도는 반영하지 못하며, 동일 텍스트에 대해
    항상 동일한 벡터를 재현하기 위한 용도로만 사용한다.
    """
    seed = sum(ord(c) for c in text)
    random.seed(seed)
    vec = [random.gauss(0, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _get_vault_key(vendor_id: str, env_key_name: str):
    """
    04_llm_manager.py에서 Supabase Vault에 등록한 키를 우선 사용하고,
    Vault 조회가 안 되는 환경(Mock/anon 키 등)이면 secrets.toml/환경변수로 대체한다.
    """
    try:
        from core.db import supabase
        key = supabase.rpc("get_llm_api_key", {"p_vendor_id": vendor_id}).execute().data
        if key:
            return key
    except Exception:
        pass
    return _get_secret(env_key_name)


def _openai_embedding(text: str, api_key: str):
    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": "text-embedding-3-small", "input": text},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()["data"][0]["embedding"]
    return None


def _gemini_embedding(text: str, api_key: str, dimension: int):
    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": dimension,
        },
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        emb = data.get("embedding") or (data.get("embeddings") or [{}])[0]
        return emb.get("values") or emb.get("value")
    return None


def generate_embedding(text: str, dimension: int = 1536) -> List[float]:
    """
    실제 임베딩 API로 벡터를 생성한다. LLM API 관리 화면(Vault)에 등록된 키를
    OpenAI -> Gemini 순서로 우선 사용하며, 등록된 키가 없거나 호출이 실패하면
    시드 기반 결정론적 벡터로 대체(Mock 모드)한다.
    """
    openai_key = _get_vault_key("openai", "OPENAI_API_KEY")
    if openai_key:
        try:
            vec = _openai_embedding(text, openai_key)
            if vec:
                return vec
        except requests.exceptions.RequestException:
            pass

    gemini_key = _get_vault_key("gemini", "GEMINI_API_KEY")
    if gemini_key:
        try:
            vec = _gemini_embedding(text, gemini_key, dimension)
            if vec:
                return vec
        except requests.exceptions.RequestException:
            pass

    return _deterministic_fallback_embedding(text, dimension)

def parse_embedding(value):
    """
    pgvector 컬럼은 실DB(PostgREST)에서 조회하면 '[0.1,0.2,...]' 형태의
    문자열로 반환된다. Mock DB는 파이썬 list를 그대로 들고 있으므로,
    두 경우 모두 항상 float 리스트로 정규화한다.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().strip("[]")
        if not value:
            return []
        return [float(x) for x in value.split(",")]
    return list(value)


def calculate_cosine_similarity(vec1, vec2) -> float:
    """
    두 벡터 간의 코사인 유사도(Cosine Similarity)를 계산합니다.
    입력이 pgvector 문자열이어도 자동으로 float 리스트로 변환합니다.
    """
    vec1 = parse_embedding(vec1)
    vec2 = parse_embedding(vec2)
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


# LLM이 "질문 중 일부라도 참고 자료에서 근거를 찾지 못했다"고 스스로 판단했을 때
# 답변 끝에 붙이도록 지시하는 고정 마커. 자연어 문구(예: "정확한 답변을 드리기 어렵습니다")를
# 키워드 매칭으로 탐지하면 LLM의 표현이 조금만 달라져도 감지에 실패하므로,
# 표현에 의존하지 않는 고정 토큰으로 근거 부족 여부를 신호하게 한다.
ANSWER_GAP_MARKER = "[REF_GAP]"


TONE_INSTRUCTIONS = {
    "친절한 상담원": "친절하고 공손한 상담원 말투로 답변하세요.",
    "사무적인 행정관": "간결하고 사무적인 행정 공문 톤으로 답변하세요.",
    "어르신 맞춤형 (쉽고 느린 톤)": "어르신이 이해하기 쉽도록 짧고 쉬운 문장으로, 천천히 설명하듯 존댓말로 답변하세요.",
}


def generate_chat_answer(user_query: str, context_chunks: List[str], tone: str = "친절한 상담원",
                          model_name: str = "gemini-3.1-flash-lite",
                          has_intake: bool = False, has_unverified: bool = False):
    """
    검색된 RAG 컨텍스트(context_chunks)만 근거로 실제 LLM(Gemini)이 자연어 답변을 생성한다.
    사용 가능한 키가 없거나 호출이 실패하면 None을 반환하여, 호출부가 원문 청크 표시로
    안전하게 대체(fallback)할 수 있도록 한다.

    has_intake=True면 컨텍스트에 B_접수(수집 필드 명세) 자료가 섞여 있다는 뜻이다.
    이는 질문의 답이 아니라 접수 시 받아야 할 항목이므로, 사실처럼 나열하지 말고
    "접수를 도와드리겠다"는 안내로 전환하도록 지시한다.
    has_unverified=True면 아직 고객 확인을 받지 못한 임시 값이 포함된 것이므로 단정을 피한다.
    """
    api_key = _get_vault_key("gemini", "GEMINI_API_KEY")
    if not api_key:
        return None

    tone_instruction = TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["친절한 상담원"])
    context_text = "\n---\n".join(context_chunks)

    extra_rules = ""
    if has_intake:
        extra_rules += (
            '\n[참고 자료] 중 "접수 시 필요정보:"로 시작하는 항목은 사용자 질문에 대한 답이 아니라,\n'
            "센터가 접수를 처리하기 위해 사용자에게 받아야 할 항목입니다. 이런 항목은 사실처럼\n"
            "설명하지 말고, 접수를 도와드리겠다고 안내한 뒤 어떤 정보를 남겨주시면 되는지\n"
            "자연스럽게 요청하는 문장으로 바꿔 쓰세요.\n"
        )
    if has_unverified:
        extra_rules += (
            "\n[참고 자료] 중 일부는 아직 센터의 최종 확인을 받지 못한 임시 내용입니다.\n"
            "단정적으로 답하지 말고, 정확한 내용은 센터에 확인이 필요하다는 점을 함께 안내하세요.\n"
        )

    prompt = f"""당신은 강서나눔돌봄센터의 AI 상담 챗봇입니다. {tone_instruction}
아래 [참고 자료]에 있는 내용만 근거로 사용자 질문에 답변하세요.
참고 자료에 없는 내용은 추측하지 말고 모른다고 답하세요.
원문을 그대로 나열하지 말고, 사람이 읽기 편한 자연스러운 문장으로 정리해서 답변하세요.
{extra_rules}
질문의 일부라도 [참고 자료]에서 근거를 찾을 수 없다면, 답변을 다 작성한 뒤 맨 마지막 줄에
반드시 "{ANSWER_GAP_MARKER}" 를 그대로(다른 말 없이 이 문자열만) 추가하세요.
질문 전체가 [참고 자료]만으로 완전히 답변 가능하다면 이 마커를 붙이지 마세요.

[참고 자료]
{context_text}

[사용자 질문]
{user_query}"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        if resp.status_code == 200:
            candidates = resp.json().get("candidates") or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts and parts[0].get("text"):
                    return parts[0]["text"].strip()
    except requests.exceptions.RequestException:
        pass

    return None


def normalize_query(user_query: str, history: List[Dict[str, str]] = None,
                     model_name: str = "gemini-3.1-flash-lite",
                     persona_label: str = None) -> str:
    """
    벡터 검색 직전에 사용자 질의를 정규화한다: 오탈자를 교정하고, 지나치게 축약된
    단문("요금은?" 등)은 검색에 유리하도록 완전한 문장으로 보완한다.
    history가 주어지면 "그럼 2구간은요?"처럼 이전 대화에 의존하는 생략/지시
    표현도 이전 맥락을 반영해 독립적으로 검색 가능한 완전한 질문으로 풀어쓴다.

    persona_label(진입 화면에서 고른 문의 유형)은 축약된 단문을 어느 방향으로 풀지
    결정하는 근거로 쓴다. 이게 없으면 정규화가 사용자 의도와 정반대로 확장될 수 있다
    (실측: "활동지원사로 일하고 싶어요"를 고른 사용자의 "자격은?"이 "센터 이용 자격은
    어떻게 되나요?"로 풀려, 정답인 '지원 자격 요건'이 0.624로 게이트 0.70에 미달 —
    2026-09-23). 유형은 사용자가 UI로 직접 알려준 정보이므로 규칙 4의 "없는 정보
    지어내기"에 해당하지 않는다.

    키가 없거나 호출이 실패하면 원문을 그대로 반환하여 검색 파이프라인이 항상
    안전하게 동작하도록 한다.
    """
    api_key = _get_vault_key("gemini", "GEMINI_API_KEY")
    if not api_key:
        return user_query

    # 최근 3턴(사용자+챗봇 최대 6개 메시지)만 참고한다. 너무 긴 이력은 프롬프트를
    # 불필요하게 늘리고, 정규화 목적(직전 맥락의 생략 표현 해소)에는 오래된 이력이
    # 오히려 잡음이 되기 쉽다.
    history_lines = []
    for m in (history or [])[-6:]:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = "사용자" if m.get("role") == "user" else "챗봇"
        history_lines.append(f"{role}: {content}")
    history_text = "\n".join(history_lines) if history_lines else "(이전 대화 없음)"
    persona_text = persona_label or "(선택 안 함)"

    prompt = f"""다음은 강서나눔돌봄센터 AI 챗봇에 입력된 사용자 질문입니다.
검색 정확도를 높이기 위해 아래 규칙에 따라 질문을 다듬어 주세요.

규칙:
1. 오탈자나 띄어쓰기 오류를 자연스럽게 교정하세요.
2. 지나치게 축약된 단문(예: "요금은?", "자격은요?")은 문맥상 자연스러운 완전한 문장으로
   보완하세요. 이때 [사용자가 선택한 문의 유형]을 최우선 근거로 삼으세요. 예를 들어 유형이
   "활동지원사로 일하고 싶어요"인 사용자가 "자격은?"이라고 물었다면 이는 서비스 이용 자격이
   아니라 "활동지원사 지원(입사) 자격 요건"을 묻는 것입니다. 유형이 "(선택 안 함)"이면
   이 규칙은 무시하세요.
3. "그럼 2구간은요?", "거기는 얼마예요?"처럼 이전 대화를 참고해야 뜻이 통하는 생략/지시
   표현이 있다면, [이전 대화]를 참고하여 무엇을 가리키는지 명확히 풀어써서 그 자체로
   독립적으로 이해 가능한 질문으로 만드세요. 이전 대화가 없거나 현재 질문과 무관하면
   이 규칙은 무시하세요.
4. 질문의 의도나 의미를 절대 바꾸지 마세요. 특히 원문에 없는 제도명·기관명을 새로
   지어내 끼워넣지 마세요(예: "본인부담금 3구간은 얼마예요?"를 "장기요양급여 본인부담금
   3구간은 얼마예요?"로 바꾸면 안 됩니다 — 원문에 없던 "장기요양급여"라는 제도명을
   임의로 추가한 것입니다). 대화에서 이미 언급된 서비스명과 [사용자가 선택한 문의 유형]은
   사용자가 직접 알려준 정보이므로 반영해도 되지만, 그 외 근거 없는 새 정보는 추가하지 마세요.
5. 질문에 분야(장애인활동지원 / 가사서비스)가 이미 드러나 있으면, 선택한 유형은 완전히
   무시하고 질문에 쓰인 분야만 남기세요. 두 분야를 한 문장에 절대 합치지 마세요.
   (나쁜 예: 유형이 "장애인활동지원 · 활동지원사로 일하고 싶어요"인 사용자의 "가사서비스
    비용은?"을 "장애인활동지원 서비스의 가사서비스 이용 비용은 얼마인가요?"로 바꾸는 것.
    실제로 존재하지 않는 조합이라 답을 찾지 못합니다.)
   (옳은 예: 같은 상황에서 "가사서비스 이용 비용은 얼마인가요?")
6. 다른 설명 없이, 교정된 질문 문장 하나만 출력하세요.

[사용자가 선택한 문의 유형]
{persona_text}

[이전 대화]
{history_text}

[현재 사용자 질문]
{user_query}"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            # temperature=0: 같은 질문이라도 매번 다르게 정규화되면(예: "얼마예요"가 호출마다
            # 다른 문장으로 완성됨) 임베딩이 흔들려 임계치 근처에서 답변/폴백이 오락가락하는
            # 원인이 된다(실측 확인). 정규화는 "창의적 답변"이 아니라 결정론적 교정이어야 하므로
            # 온도를 0으로 고정한다.
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0}},
            timeout=10,
        )
        if resp.status_code == 200:
            candidates = resp.json().get("candidates") or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts and parts[0].get("text"):
                    normalized = parts[0]["text"].strip().strip('"').strip("'")
                    if normalized:
                        return normalized
    except requests.exceptions.RequestException:
        pass

    return user_query


GUARDRAIL_TOPIC_DESCRIPTIONS = {
    "medical": "의료/질병 진단이나 치료·투약에 대한 의학적 조언",
    "legal": "법률적 판단이나 소송·노무 분쟁에 대한 법률 상담",
    "privacy": "주민등록번호·계좌번호 등 민감한 개인정보의 수집이나 취급",
}


def check_guardrail_intent(user_query: str, topic: str,
                            model_name: str = "gemini-3.1-flash-lite") -> bool:
    """
    가드레일 키워드가 탐지된 질문에 대해, 실제로 차단 대상 '의도'인지를 LLM이 판정한다.

    단순 키워드 포함 검사만으로는 "치매 어르신도 서비스 이용할 수 있나요?"(정상적인
    서비스 자격 문의)와 "치매 약은 뭘 먹어야 하나요?"(의학적 조언 요청)를 구분할 수
    없어, 돌봄센터의 핵심 고객 문의가 대량으로 오차단된다. 실측 결과 정상 질문 6건 중
    5건이 차단되었다.

    반환값: True면 차단, False면 통과.
    판정 실패(키 없음/API 오류) 시에는 컴플라이언스 기능의 성격상 보수적으로 True(차단)를
    반환해, 기존 키워드 기반 동작과 동일한 수준의 방어를 유지한다.
    """
    api_key = _get_vault_key("gemini", "GEMINI_API_KEY")
    if not api_key:
        return True

    topic_desc = GUARDRAIL_TOPIC_DESCRIPTIONS.get(topic, topic)

    prompt = f"""당신은 강서나눔돌봄센터(장애인활동지원·가사서비스 제공 기관) AI 상담 챗봇의
컴플라이언스 판정기입니다. 아래 사용자 질문이 "{topic_desc}"을(를) 실제로 요구하는지 판정하세요.

판정 기준:
- 사용자가 전문가의 판단(진단/처방/법적 판단 등)을 챗봇에게 요구하면 BLOCK 입니다.
- 서비스 이용 자격, 신청 절차, 필요 서류, 요금, 채용/근무 조건에 대한 문의는
  질문에 질병명·법률 용어가 등장하더라도 정상 문의이므로 ALLOW 입니다.
  (예: "치매 어르신도 서비스 받을 수 있나요?" -> 서비스 자격 문의이므로 ALLOW)
  (예: "치매에 좋은 약 알려주세요" -> 의학적 조언 요구이므로 BLOCK)
  (예: "근로계약서는 언제 작성하나요?" -> 채용 절차 문의이므로 ALLOW)
  (예: "부당해고로 소송하려면 어떻게 하나요?" -> 법률 상담 요구이므로 BLOCK)

다른 설명 없이 BLOCK 또는 ALLOW 중 한 단어만 출력하세요.

[사용자 질문]
{user_query}"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=10,
        )
        if resp.status_code == 200:
            candidates = resp.json().get("candidates") or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts and parts[0].get("text"):
                    verdict = parts[0]["text"].strip().upper()
                    if "ALLOW" in verdict:
                        return False
                    if "BLOCK" in verdict:
                        return True
    except requests.exceptions.RequestException:
        pass

    return True


def extract_hitl_answer(content: str) -> str:
    """
    HITL 모범 정답 청크("질문: ...\\n답변: ...")에서 답변 부분만 추출한다.
    시맨틱 캐시 히트 시, 질문 원문을 다시 노출하지 않고 답변만 보여주기 위함이다.
    """
    match = re.search(r"답변:\s*(.+)", content, re.DOTALL)
    return match.group(1).strip() if match else content


# 진입 시점에 사용자가 선택하는 페르소나 -> 검색 대상 카테고리(엑셀 시트명) 매핑.
# 지식베이스가 이미 "서비스 종류 x 이용자/종사자" 축으로 구성되어 있어 그대로 대응된다.
PERSONA_CATEGORIES = {
    # 원본 문서(chatbot_data.hwpx)의 계층을 그대로 따른다:
    #   서비스(장애인활동지원/가사) x 관계(이용희망/이용중/취업희망/재직중)
    # 이전 4분류는 "입사 문의"와 "재직자"를 한 카테고리에 묶어, 입사 희망자 질문에
    # 사직·휴직 등 재직자 문서가 상위에 올라오는 오염이 있었다(실측: 5칸 중 3칸).
    # 0_공통(센터 주소 등)은 모든 페르소나에 함께 포함한다.
    "활동지원_이용희망": ["3_활동지원_이용신규", "5_활동지원_본인부담금", "0_공통"],
    "활동지원_이용중": ["4_활동지원_이용중", "5_활동지원_본인부담금", "0_공통"],
    "활동지원_취업희망": ["1_활동지원_입사", "0_공통"],
    "활동지원_재직중": ["2_활동지원_재직", "0_공통"],
    "가사_이용희망": ["8_가사_서비스요금", "0_공통"],
    "가사_이용중": ["9_가사_민원", "8_가사_서비스요금", "0_공통"],
    "가사_취업희망": ["6_가사_입사", "0_공통"],
    "가사_재직중": ["7_가사_재직", "0_공통"],
}

# 센터 주소·대표 연락처처럼 특정 서비스 분야에 속하지 않는 공통 정보 카테고리.
# 모든 페르소나에 포함되지만, 질문과 겹치는 단어가 적어 유사도 경쟁에서 구조적으로
# 밀린다(실측: "활동지원사 면접 언제 어디로 찾아가면 되나요?"에서 주소 청크가
# 페르소나 적용 시 9위, 전체 검색에서는 후보 30건 밖 — 2026-09-23).
COMMON_CATEGORY = "0_공통"


# gangseo_chatbot_web/lib/personas.ts의 PERSONA_LABELS와 문자열까지 동일해야 한다.
# 이 값은 화면 표시용일 뿐 아니라 normalize_query에 그대로 전달되어 질의를 어떻게
# 풀어쓸지에 영향을 준다. 예전에 두 쪽 표기가 달라(웹은 "장애인활동지원 · 활동지원사로
# 일하고 싶어요", 여기는 "활동지원사로 일하고 싶어요") 시뮬레이터에서는 멀쩡한 질의가
# 운영에서는 "장애인활동지원 서비스의 가사서비스 비용"처럼 깨지는 일이 있었다.
# 시뮬레이터로 검증한 결과를 운영에서 믿으려면 이 표가 어긋나면 안 된다.
PERSONA_LABELS = {
    "활동지원_이용희망": "장애인활동지원 · 새로 이용하고 싶어요",
    "활동지원_이용중": "장애인활동지원 · 이용하고 있어요",
    "활동지원_취업희망": "장애인활동지원 · 활동지원사로 일하고 싶어요",
    "활동지원_재직중": "장애인활동지원 · 활동지원사로 근무 중이에요",
    "가사_이용희망": "가사서비스 · 새로 이용하고 싶어요",
    "가사_이용중": "가사서비스 · 이용하고 있어요",
    "가사_취업희망": "가사서비스 · 가사관리사로 일하고 싶어요",
    "가사_재직중": "가사서비스 · 가사관리사로 근무 중이에요",
}


def infer_service_group(category: str):
    """
    카테고리(v4 엑셀 시트명)를 상위 서비스 그룹으로 매핑한다. "0_공통"은 어느
    서비스에도 속하지 않는 공통 지식(센터 주소 등)이라 판단 재료에서 제외한다.
    """
    if "활동지원" in category:
        return "활동지원"
    if "가사" in category:
        return "가사"
    return None


def detect_ambiguous_service(matches, top_n: int = 5, min_plausible: float = 0.55,
                              max_gap: float = 0.05) -> bool:
    """
    페르소나(문의 유형)를 선택하지 않은 채 "얼마예요?", "신청하고 싶어요"처럼 짧고
    일반적인 질문을 하면, 활동지원/가사 두 서비스의 문서가 거의 같은 유사도로 함께
    검색되어 실제로는 근거가 빈약한 쪽으로 우연히 답이 나갈 수 있다(실측: "얼마예요"가
    동일 질문인데도 실행할 때마다 답변/폴백을 오갔다 — 두 서비스 최고점이 0.01~0.02
    차이라 임베딩의 미세한 흔들림에 결과가 좌우됨). 이 경우 추측해서 답하는 대신
    어떤 서비스인지 먼저 물어보는 것이 더 안전하다.
    """
    best_by_group = {}
    for m in matches[:top_n]:
        group = infer_service_group(m[2])
        if not group:
            continue
        if group not in best_by_group or m[0] > best_by_group[group]:
            best_by_group[group] = m[0]
    scores = sorted(best_by_group.values(), reverse=True)
    if len(scores) < 2:
        return False
    return scores[0] >= min_plausible and scores[0] - scores[1] <= max_gap


def hybrid_search(query_text: str, query_vec: List[float], match_count: int = 30,
                   categories: List[str] = None):
    """
    검색을 서버사이드 RPC(admin_match_documents, supabase/005 참고)에 위임한다.
    pgvector ivfflat 인덱스를 활용한 벡터 후보군과, pg_trgm 트라이그램 유사도로 찾은
    키워드 후보군을 함께 받아온다. 후자는 "3구간"처럼 벡터 유사도만으로는 순위가
    밀리기 쉬운 특정 값/고유명사 질의를 구제하기 위함으로, 기존에 앱 코드에 있던
    \\d+구간 정규식 하드코딩을 일반화한 것이다.
    문서 전량을 클라이언트로 내려받아 파이썬에서 코사인을 계산하지 않으므로 인덱스를
    실제로 활용하고, 문서 수가 늘어나도 확장 가능하다.

    RPC가 아직 배포되지 않았거나(마이그레이션 미적용) 호출이 실패하면, 기존 방식인
    "전량 조회 후 클라이언트 사이드 코사인 계산"으로 안전하게 대체(fallback)한다.

    categories를 주면 해당 카테고리(페르소나) 안에서만 검색한다. 사용자가 진입 시점에
    자신의 상황을 선택했을 때 타 페르소나 문서가 컨텍스트를 잠식하는 것을 막기 위함이다.
    None/빈 리스트면 기존과 동일하게 전체를 검색한다.

    반환값: (vector_matches, keyword_matches). 둘 다
    (similarity, content, category, doc_type, verification) 튜플 리스트.
    앞 3개 위치는 기존 호출부와의 호환을 위해 그대로 유지한다.
    vector_matches는 코사인 유사도 내림차순이며 기존 임계치 게이트 로직에 그대로 사용한다.
    keyword_matches는 임계치와 무관하게 강제 포함하는 보조 후보군이며,
    폴백 경로에서는 항상 빈 리스트다.
    """
    from core.db import supabase

    def _tup(r):
        return (
            r["similarity"], r["content"], r["category"],
            r.get("doc_type") or DOC_TYPE_FACT, r.get("verification"),
        )

    try:
        res = supabase.rpc("admin_match_documents", {
            "query_embedding": query_vec,
            "query_text": query_text,
            "match_count": match_count,
            "filter_categories": categories or None,
        }).execute()
        rows = res.data if res.data is not None else []
        vector_matches = [_tup(r) for r in rows if r.get("match_source") == "vector"]
        keyword_matches = [_tup(r) for r in rows if r.get("match_source") == "keyword"]
        vector_matches.sort(key=lambda x: x[0], reverse=True)
        return vector_matches, keyword_matches
    except Exception:
        pass

    query = supabase.table("rag_documents").select(
        "content, category, embedding, doc_type, verification"
    )
    if categories:
        query = query.in_("category", categories)
    docs_res = query.execute()
    docs = docs_res.data if docs_res.data else []
    matches = []
    for doc in docs:
        doc_vec = parse_embedding(doc.get("embedding"))
        if doc_vec and len(doc_vec) == len(query_vec):
            sim = calculate_cosine_similarity(query_vec, doc_vec)
            matches.append((
                sim, doc.get("content"), doc.get("category"),
                doc.get("doc_type") or DOC_TYPE_FACT, doc.get("verification"),
            ))
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches, []
