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

def extract_excel_rows(file_bytes: bytes) -> List[Dict[str, str]]:
    """
    엑셀은 이미 사람이 행 단위로 정리해 둔 원자적 지식 단위이므로,
    chunk_text()의 글자 수 기반 재분할을 거치지 않고 1행 = 1청크로 반환한다.
    시트명이 곧 카테고리가 된다.
    """
    excel_file = io.BytesIO(file_bytes)
    sheets = pd.read_excel(excel_file, sheet_name=None)
    rows = []
    for sheet_name, df in sheets.items():
        # 시트명 앞의 일련번호를 떼고 공백으로 풀어써서, 임베딩이 주제 맥락을
        # 더 잘 붙잡도록 한다("1_장애인활동지원_종사자" -> "장애인활동지원 종사자").
        topic_label = re.sub(r"^\d+_", "", sheet_name).replace("_", " ")
        for _, row in df.iterrows():
            row_items = [f"{col}: {val}" for col, val in row.items() if pd.notna(val)]
            if row_items:
                rows.append({
                    "category": sheet_name,
                    "content": f"[{topic_label}] " + " | ".join(row_items)
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
                          model_name: str = "gemini-3.1-flash-lite"):
    """
    검색된 RAG 컨텍스트(context_chunks)만 근거로 실제 LLM(Gemini)이 자연어 답변을 생성한다.
    사용 가능한 키가 없거나 호출이 실패하면 None을 반환하여, 호출부가 원문 청크 표시로
    안전하게 대체(fallback)할 수 있도록 한다.
    """
    api_key = _get_vault_key("gemini", "GEMINI_API_KEY")
    if not api_key:
        return None

    tone_instruction = TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["친절한 상담원"])
    context_text = "\n---\n".join(context_chunks)

    prompt = f"""당신은 강서나눔돌봄센터의 AI 상담 챗봇입니다. {tone_instruction}
아래 [참고 자료]에 있는 내용만 근거로 사용자 질문에 답변하세요.
참고 자료에 없는 내용은 추측하지 말고 모른다고 답하세요.
원문을 그대로 나열하지 말고, 사람이 읽기 편한 자연스러운 문장으로 정리해서 답변하세요.

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
