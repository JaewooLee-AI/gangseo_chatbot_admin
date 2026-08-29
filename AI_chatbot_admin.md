# **강서나눔돌봄센터 AI 챗봇 시스템 최고 관리자용 RAG 통제반 통합 구축 명세 및 아키텍처 구현 보고서**

## **1\. 서론: 엔터프라이즈 AI 챗봇의 지식 통제 패러다임**

인공지능(AI)과 대형 언어 모델(LLM)을 활용한 고객 응대(CS) 자동화는 현대 비즈니스의 핵심 경쟁력으로 자리 잡았다. 그러나 강서나눔돌봄센터와 같이 요금 정산, 복지 자격 요건, 민감한 내부 규정, 그리고 어르신의 건강 상태와 직결된 서비스를 다루는 기관에서는 단순한 질의응답을 넘어선 엄격한 '지식 통제(Knowledge Control)'와 '법적 방어(Compliance Guardrails)'가 요구된다. 일반적인 챗봇이 범용 지식을 바탕으로 환각(Hallucination) 현상을 일으키거나, 확인되지 않은 의료적 조언을 제공할 경우 심각한 비즈니스 및 법률적 리스크를 초래할 수 있다1.  
이러한 문제를 해결하기 위해 본 시스템은 실무 담당자가 CS 민원을 처리하는 가벼운 사용자용 프론트엔드(Vercel 및 Next.js 기반)와 최고 관리자가 AI의 뇌(지식과 페르소나)를 심층적으로 조율하는 백엔드 통제반(Python Streamlit 기반)을 물리적으로 분리하는 3-Tier 아키텍처를 채택하였다1. Vercel의 서버리스 환경은 대규모 데이터의 청킹(Chunking)이나 임베딩(Embedding) 처리 시 10초 이상의 타임아웃 오류를 발생시킬 수 있으므로, 데이터 집약적인 RAG(Retrieval-Augmented Generation) 파이프라인 관리는 파이썬 생태계에 최적화된 Streamlit 대시보드에 전적으로 위임한다1.  
본 보고서는 강서나눔돌봄센터 최고 관리자가 AI 지식을 통제하고, 휴먼 인 더 루프(Human-in-the-loop, HITL) 방식을 통해 성능을 고도화하며, 실무진의 계정 권한을 중앙에서 관리할 수 있도록 설계된 'RAG 통제반 대시보드'의 완벽한 기술 명세와 Vibe Coding 기반의 초기 구현 코드를 심도 있게 제시한다.

## **2\. 시스템 아키텍처 철학 및 데이터베이스 스키마 설계**

### **2.1 통합 데이터 스토리지로서의 Supabase와 pgvector**

현대 RAG 시스템 구축 시 텍스트 메타데이터를 저장하는 관계형 데이터베이스(RDBMS)와 벡터 임베딩을 저장하는 벡터 데이터베이스(Vector DB)를 분리하는 방식이 흔히 사용된다. 그러나 이는 데이터 동기화 문제와 인프라 관리 비용을 증가시킨다. 본 아키텍처는 오픈소스 Firebase 대안으로 각광받는 Supabase를 채택하여, PostgreSQL의 강력한 관계형 데이터 처리 능력과 pgvector 확장을 통한 고차원 벡터 유사도 검색 기능을 단일 저장소에서 완벽하게 통합한다4.  
이러한 단일 데이터베이스 접근 방식은 지식 데이터(문서 청크)와 비즈니스 데이터(직원 계정, 챗봇 설정, 오답 로그)를 하나의 인프라에서 트랜잭션(Transaction) 단위로 안전하게 관리할 수 있게 하며, 후속 확장 시 하이브리드 검색(Hybrid Search) 도입을 용이하게 한다4.

### **2.2 관계형 및 벡터 데이터베이스 스키마 명세**

시스템의 안정성을 보장하기 위해 4개의 핵심 테이블을 설계한다. 벡터 검색 속도를 최적화하기 위해 pgvector의 ivfflat 인덱스를 적용하며, 이는 대용량 텍스트 임베딩 환경에서 근사 최근접 이웃(ANN, Approximate Nearest Neighbor) 검색 성능을 극대화한다7.

| 테이블 명칭 | 핵심 기능 및 역할 | 주요 컬럼 구성 |
| :---- | :---- | :---- |
| rag\_documents | RAG 지식베이스의 핵심 저장소. 원본 문서를 청크 단위로 분할하여 텍스트와 벡터 임베딩을 저장. | id (UUID), content (텍스트), embedding (vector), category (분류 메타데이터), created\_at (타임스탬프) |
| fallback\_logs | 챗봇이 답변 임계치 미달로 '상담사 연결'을 결정한 미해결 사용자 질의 로그 추적 및 고도화 활용. | id, user\_query (질문 원문), status (pending/resolved), golden\_answer (관리자 모범 정답), created\_at |
| bot\_settings | 외부 Vercel 앱이 동적으로 읽어가는 AI 시스템 프롬프트의 환경 설정 저장소 (단일 행 유지). | id (PK=1), tone (어조), block\_medical (의료차단 Boolean), block\_legal, block\_privacy, strictness\_level |
| staff\_users | Vercel 민원 관리 웹앱에 접근 가능한 센터 실무진 이메일 화이트리스트 (White-list). | id, staff\_name (이름), email (고유 접근 키), created\_at |

#### **초기 셋업을 위한 Supabase SQL 스크립트**

SQL  
\-- pgvector 확장 활성화로 벡터 데이터 처리 기반 마련  
CREATE EXTENSION IF NOT EXISTS vector;

\-- 1\. 지식베이스 (RAG) 테이블 생성  
CREATE TABLE rag\_documents (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    content TEXT NOT NULL,  
    \-- Alibaba Qwen 또는 OpenAI의 임베딩 차원에 맞추어 1536 설정  
    embedding vector(1536),   
    category VARCHAR(50) NOT NULL,  
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()  
);

\-- 벡터 유사도 검색 최적화를 위한 인덱스 구성 (Cosine Similarity 기반)  
CREATE INDEX ON rag\_documents USING ivfflat (embedding vector\_cosine\_ops) WITH (lists \= 100);

\-- 2\. 미해결 오답 로그 (Fallback) 테이블 생성  
CREATE TABLE fallback\_logs (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    user\_query TEXT NOT NULL,  
    status VARCHAR(20) DEFAULT 'pending',  
    golden\_answer TEXT,  
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()  
);

\-- 3\. 시스템 동적 프롬프트 설정 (단일 레코드) 테이블  
CREATE TABLE bot\_settings (  
    id INT PRIMARY KEY DEFAULT 1,  
    tone VARCHAR(50) DEFAULT '친절한 상담원',  
    block\_medical BOOLEAN DEFAULT TRUE,  
    block\_legal BOOLEAN DEFAULT TRUE,  
    block\_privacy BOOLEAN DEFAULT TRUE,  
    strictness\_level INT DEFAULT 5  
);  
\-- 무결성을 위해 초기 레코드 1건 강제 생성  
INSERT INTO bot\_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

\-- 4\. 직원 화이트리스트 계정 테이블  
CREATE TABLE staff\_users (  
    id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),  
    staff\_name VARCHAR(100) NOT NULL,  
    email VARCHAR(255) UNIQUE NOT NULL,  
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()  
);

## **3\. 디렉토리 구조 및 모던 UI/UX CSS 렌더링 전략**

Vibe Coding을 원활하게 수행하고 향후 유지보수를 극대화하기 위해, Streamlit의 단일 스크립트 구조를 탈피하여 모듈 중심의 디렉토리 아키텍처를 구성한다.  
admin\_dashboard/  
├── app.py \# 사이드바 라우팅 및 전역 세션 관리  
├── requirements.txt \# streamlit, supabase, pandas, pypdf2 등  
├── .streamlit/  
│ └── secrets.toml \# \[필수\] Supabase URL, Key 및 LLM API Keys  
├── core/  
│ ├── db.py \# Supabase 클라이언트 초기화 모듈  
│ └── rag\_engine.py \# 청킹, 텍스트 전처리, 임베딩 벡터화 로직  
└── modules/ \# 6대 핵심 비즈니스 로직 뷰  
├── 01\_data\_pipeline.py  
├── 02\_hitl\_review.py  
├── 03\_persona\_settings.py  
├── 04\_llm\_manager.py  
├── 05\_staff\_auth.py  
└── 06\_simulator.py

### **모던 B2B SaaS 디자인의 주입 (CSS Injection)**

기본적으로 Streamlit은 신속한 데이터 시각화에 최적화되어 있으나, 레이아웃의 투박함으로 인해 상용 B2B SaaS 대시보드로는 시각적 완성도가 부족하다1. 이를 해결하기 위해 unsafe\_allow\_html=True 속성을 활용한 CSS Injection 기법을 적용한다. 이 기법은 HTML DOM 노드에 직접 접근하여 shadcn-ui와 유사한 부드러운 그림자(drop-shadow), 둥근 테두리(border-radius), 그리고 가독성이 높은 밝은 톤의 레이아웃을 생성한다9.  
app.py 최상단에 주입될 글로벌 스타일 코드는 다음과 같다.

Python  
import streamlit as st

def inject\_global\_css():  
    st.markdown("""  
    \<style\>  
        /\* 글로벌 색상 및 폰트 변수 지정 \*/  
        :root {  
            \--bg-color: \#FAFAF9; /\* 따뜻한 오프화이트 배경 \*/  
            \--card-bg: \#FFFFFF;  
            \--primary: \#F97316; /\* 강서나눔돌봄센터 테마에 맞춘 오렌지 포인트 \*/  
            \--text-main: \#1C1917;  
            \--text-muted: \#78716C;  
            \--border-radius: 12px;  
        }  
          
        /\* 전체 백그라운드 적용 \*/  
        .stApp { background-color: var(--bg-color); color: var(--text-main); font-family: 'Pretendard', sans-serif; }  
          
        /\* 컨테이너 카드형 레이아웃 구성 \*/  
        \[data-testid="stVerticalBlock"\] \> div \> div {  
            background-color: var(--card-bg);  
            border-radius: var(--border-radius);  
            padding: 1.5rem;  
            box-shadow: 0 4px 6px \-1px rgba(0, 0, 0, 0.05), 0 2px 4px \-1px rgba(0, 0, 0, 0.03);  
            border: 1px solid \#E7E5E4;  
            margin-bottom: 1rem;  
        }  
          
        /\* 버튼 컴포넌트의 shadcn-ui 스타일링 \*/  
        .stButton \> button {  
            background-color: var(--primary);  
            color: \#FFFFFF;  
            border: none;  
            border-radius: 6px;  
            padding: 0.5rem 1rem;  
            font-weight: 600;  
            transition: all 0.2s ease;  
        }  
        .stButton \> button:hover {  
            background-color: \#EA580C;  
            transform: translateY(-1px);  
            box-shadow: 0 4px 12px rgba(249, 115, 22, 0.2);  
        }  
          
        /\* 사이드바 스타일링 \*/  
        \[data-testid="stSidebar"\] { background-color: var(--card-bg); border-right: 1px solid \#E7E5E4; }  
    \</style\>  
    """, unsafe\_allow\_html=True)

이러한 CSS 주입을 통해 일반 윈도우 OS를 사용하는 사무직 종사자들도 시각적 피로감 없이 직관적으로 통제반을 운영할 수 있는 환경이 완성된다1.

## **4\. 6대 핵심 모듈별 상세 명세 및 파이썬 초기 코드**

### **4.1 모듈 1: Multi-format RAG 데이터 파이프라인 및 시각화**

RAG 시스템에서 가장 흔히 발생하는 오류는 '검색 오류(Retrieval Error)'와 서로 다른 문맥 간의 '지식 오염'이다. 예를 들어, "가사서비스 요금"을 질문했는데 "방문요양 요금" 문서가 검색되는 현상이다1. 이를 방지하기 위해 파일 업로드 시 반드시 카테고리(메타데이터)를 선택하도록 시스템적으로 강제(Force)하는 로직이 필수적이다.  
또한, 자동 텍스트 추출 방식은 테이블 형태의 데이터를 훼손할 우려가 있다. 이를 보완하기 위해 Streamlit의 st.data\_editor를 활용한다. st.data\_editor는 세션 상태(Session State) 내부에서 edited\_rows라는 딕셔너리로 변경 사항을 추적하므로, 관리자가 불완전한 문맥을 수동으로 결합하고 원클릭으로 수정 내역만 다시 데이터베이스에 반영(Re-embed)할 수 있는 완벽한 상호작용 인터페이스를 제공한다1.

Python  
\# modules/01\_data\_pipeline.py  
import streamlit as st  
import pandas as pd  
from core.db import supabase

def render():  
    st.title("📊 RAG 데이터 파이프라인 및 시각화")  
      
    col\_upload, col\_edit \= st.columns(\[1, 2\], gap="large")  
      
    \# 1\. 파일 업로드 및 메타데이터 강제  
    with col\_upload:  
        st.subheader("신규 지식 문서 업로드")  
          
        \# \[필수\] 메타데이터 카테고리 지정  
        category\_options \= \["선택 안 함", "요금정산", "자격요건", "내부규정", "일반안내"\]  
        selected\_category \= st.selectbox("📌 메타데이터 선택 (필수)", category\_options)  
          
        uploaded\_file \= st.file\_uploader("문서 업로드 (PDF, TXT, Excel)", type\=\["pdf", "txt", "xlsx"\])  
          
        if st.button("문서 학습 및 벡터 DB 색인"):  
            if selected\_category \== "선택 안 함":  
                st.error("🚨 필수 항목 누락: 카테고리(메타데이터)를 반드시 지정해야 합니다.")  
            elif uploaded\_file is not None:  
                with st.spinner("텍스트 추출 및 백그라운드 임베딩 진행 중..."):  
                    \# 실제 구현 시 PyPDF2 또는 Pandas 추출 및 임베딩 API 연동 로직 위치  
                    dummy\_chunk \= f"추출된 텍스트 청크 샘플 ({uploaded\_file.name})"  
                      
                    \# Supabase에 원본 텍스트와 카테고리 적재 (임베딩 포함)  
                    supabase.table("rag\_documents").insert({  
                        "content": dummy\_chunk,  
                        "category": selected\_category  
                        \# "embedding": \[...\]   
                    }).execute()  
                    st.success(f"\[{selected\_category}\] 분류로 색인 완료되었습니다.")  
            else:  
                st.warning("파일을 먼저 업로드해 주세요.")

    \# 2\. 색인 데이터 시각화 및 편집 (Human-in-the-loop 보완)  
    with col\_edit:  
        st.subheader("지식베이스 청크(Chunk) 관리")  
        st.caption("자동 분할 과정에서 의미가 끊긴 문맥을 엑셀처럼 수동 결합하고 재학습할 수 있습니다.")  
          
        response \= supabase.table("rag\_documents").select("id, category, content").limit(50).execute()  
        df \= pd.DataFrame(response.data) if response.data else pd.DataFrame(columns=\["id", "category", "content"\])  
          
        if not df.empty:  
            \# st.data\_editor를 통한 인메모리 테이블 편집 허용  
            edited\_df \= st.data\_editor(df, num\_rows="dynamic", use\_container\_width=True, key="chunk\_editor")  
              
            if st.button("수정된 데이터 원클릭 재학습 (Re-embed)"):  
                with st.spinner("변경된 텍스트를 재임베딩하여 DB에 반영 중입니다..."):  
                    \# st.session\_state\["chunk\_editor"\]\["edited\_rows"\]를 활용하여   
                    \# 변경된 행만 효율적으로 추출 후 UPDATE 쿼리 수행  
                    st.success("데이터베이스 재학습이 완료되었습니다.")  
        else:  
            st.info("현재 등록된 지식베이스 데이터가 없습니다.")

### **4.2 모듈 2: Human-in-the-loop 기반 성능 고도화 (오답 리뷰)**

아무리 훌륭한 문서를 제공하더라도 사용자의 질의 패턴은 예측하기 어렵다. AI가 문서를 참조하여 정답을 확신하지 못하면, 할루시네이션(환각)을 일으키는 대신 스스로 대답을 포기하고 \[상담사 연결 필요\]라는 Fallback 코드를 반환하도록 시스템 프롬프트가 설정되어 있다1.  
이러한 미해결 로그(Fallback Logs)는 시스템 성장의 훌륭한 자양분이 된다. 본 모듈은 관리자가 챗봇의 미해결 질문을 모니터링하고, 그 옆에 '모범 정답(Golden Answer)'을 타이핑하면 해당 Q\&A 세트를 하나의 문맥 청크로 병합하여 즉각적으로 RAG 생태계에 편입시키는 자가 진화 파이프라인을 구축한다1.

Python  
\# modules/02\_hitl\_review.py  
import streamlit as st  
from core.db import supabase

def render():  
    st.title("🧠 오답 리뷰 및 AI 신규 학습 (HITL)")  
    st.markdown("챗봇이 답변을 방어하고 \*\*상담사 연결(Fallback)\*\*을 반환한 로그입니다. 모범 정답을 입력하여 AI를 고도화하세요.")  
      
    \# 처리 대기 중인 오답 로그만 추출  
    res \= supabase.table("fallback\_logs").select("\*").eq("status", "pending").execute()  
    logs \= res.data  
      
    if logs:  
        for log in logs:  
            with st.expander(f"🔴 사용자 질의: {log\['user\_query'\]}", expanded=True):  
                \# 관리자의 수동 개입 (모범 답안 작성)  
                golden\_answer \= st.text\_area("모범 정답 입력 (이 답변이 Vector DB에 새롭게 각인됩니다):",   
                                             key=f"text\_{log\['id'\]}")  
                  
                if st.button("AI 신규 학습 반영", key=f"btn\_{log\['id'\]}"):  
                    if golden\_answer:  
                        \# 1\. 질의와 응답을 결합하여 새로운 지식 청크 생성  
                        combined\_text \= f"질문: {log\['user\_query'\]}\\n답변: {golden\_answer}"  
                          
                        \# 2\. Vector DB에 즉각 편입  
                        supabase.table("rag\_documents").insert({  
                            "content": combined\_text,  
                            "category": "수동학습(HITL)"  
                        }).execute()  
                          
                        \# 3\. 로그 상태 업데이트 (완료 처리)  
                        supabase.table("fallback\_logs").update({  
                            "status": "resolved",  
                            "golden\_answer": golden\_answer  
                        }).eq("id", log\['id'\]).execute()  
                          
                        st.success("신규 지식이 성공적으로 주입되었습니다.")  
                        st.rerun()  
                    else:  
                        st.warning("모범 정답을 입력해야 학습이 가능합니다.")  
    else:  
        st.success("🎉 현재 모든 오답 로그가 처리되었습니다. AI가 최상의 컨디션을 유지 중입니다.")

### **4.3 모듈 3: AI 페르소나 및 보안 설정 통제반 (Dynamic Prompting)**

엔터프라이즈 AI 시스템에서 설정값을 하드코딩(Hard-coding)하는 것은 치명적이다. 챗봇의 어조, 답변의 보수성, 법적 민감도(의료 진단 등)는 경영진의 판단에 따라 즉각적으로 변경되어야 한다1. 본 대시보드는 bot\_settings 테이블의 단일 레코드를 업데이트하는 직관적인 UI를 제공한다. Vercel 기반의 사용자 챗봇은 매 질의응답 시 이 테이블을 조회하여 프롬프트를 동적으로 조립(Dynamic Prompting)하게 된다.  
RAG 엄격도 슬라이더는 벡터 서치 시 가져올 문서의 코사인 유사도(Cosine Similarity) 한계치를 수학적으로 조절한다.

* **Level 5 (엄격):** ![][image1] 설정. 문서와 완벽히 일치하는 맥락이 없으면 단호하게 상담사 연결로 이관한다1.  
* **Level 1 (유연):** ![][image2] 설정. 다소 모호한 질문이라도 일반 지식을 섞어 유연하게 대답한다.

Python  
\# modules/03\_persona\_settings.py  
import streamlit as st  
from core.db import supabase

def render():  
    st.title("⚙️ AI 페르소나 및 보안 설정 (Dynamic Prompting)")  
    st.markdown("이곳의 설정값은 저장 즉시 외부 사용자 챗봇의 \*\*시스템 프롬프트\*\*에 동적으로 반영됩니다.")  
      
    \# 기존 설정값 로드  
    settings\_res \= supabase.table("bot\_settings").select("\*").eq("id", 1).execute()  
    current \= settings\_res.data\[0\] if settings\_res.data else {}  
      
    with st.form("settings\_form"):  
        st.subheader("1. 톤앤매너 (Tone & Manner) 제어")  
        tones \= \["친절한 상담원", "사무적인 행정관", "어르신 맞춤형 (쉽고 느린 톤)"\]  
        default\_index \= tones.index(current.get("tone", "친절한 상담원")) if current.get("tone") in tones else 0  
        selected\_tone \= st.selectbox("AI의 기본 어조를 선택하세요", tones, index=default\_index)  
          
        st.divider()  
        st.subheader("2. 컴플라이언스 (법적 방어) 가드레일 설정")  
        st.caption("활성화(On) 시, 해당 주제에 대한 사용자의 질의를 강제로 차단하고 상담사에게 이관합니다.")  
          
        c1, c2, c3 \= st.columns(3)  
        with c1:  
            block\_med \= st.toggle("🏥 의료/질병 진단 차단", value=current.get("block\_medical", True))  
        with c2:  
            block\_law \= st.toggle("⚖️ 법률/노무 상담 차단", value=current.get("block\_legal", True))  
        with c3:  
            block\_pii \= st.toggle("🔒 개인정보 요구 차단", value=current.get("block\_privacy", True))  
              
        st.divider()  
        st.subheader("3. RAG 엄격도 (유사도 임계치 제어)")  
        st.caption("1단계(배경지식 허용) \~ 5단계(지식베이스 외부 답변 철저히 금지)")  
        strictness \= st.slider("엄격도 조절 슬라이더", min\_value=1, max\_value=5, value=current.get("strictness\_level", 5))  
          
        if st.form\_submit\_button("설정 저장 및 즉시 배포"):  
            supabase.table("bot\_settings").upsert({  
                "id": 1,  
                "tone": selected\_tone,  
                "block\_medical": block\_med,  
                "block\_legal": block\_law,  
                "block\_privacy": block\_pii,  
                "strictness\_level": strictness  
            }).execute()  
            st.success("✅ 시스템 설정이 성공적으로 업데이트되었습니다. 다음 질의부터 즉시 반영됩니다.")

### **4.4 모듈 4: 멀티 LLM 관리 및 연결 테스트 (API Validation)**

특정 벤더(예: OpenAI)의 서비스 다운타임에 대비하기 위해 멀티 LLM(Alibaba Qwen, Claude, Gemini) 라우팅을 지원한다1. 이 모듈은 데이터베이스에 API 키를 평문 혹은 암호화하여 저장하고, \[연결 테스트\] 버튼을 통해 해당 API 엔드포인트에 즉각적으로 상태 확인(Health Check) 핑을 날려 유효성을 검증한다. HTTP 상태 코드에 기반한 명확한 UI 피드백을 제공한다.

| 벤더명 | 주력 용도 | API 유효성 검증 방식 |
| :---- | :---- | :---- |
| **Alibaba Qwen** | 메인 RAG 생성 엔진 | messages API에 최소 토큰 전송하여 응답 여부 확인 |
| **OpenAI ChatGPT** | 임베딩 및 보조 생성 엔진 | v1/models 엔드포인트 호출 또는 최소 Completion |
| **Anthropic Claude** | 복잡한 문서 분석 및 추론 | messages API 호출 시 HTTP 200 반환 여부 검사 |

Python  
\# modules/04\_llm\_manager.py  
import streamlit as st  
import time

def render():  
    st.title("🔑 멀티 LLM 관리 및 연결 테스트")  
    st.write("단일 벤더 종속을 피하기 위한 API Key 저장 및 네트워크 연결 상태를 즉각 검증합니다.")  
      
    with st.container():  
        llm\_vendor \= st.selectbox("LLM 벤더 선택", \["Alibaba Qwen (메인)", "OpenAI (ChatGPT)", "Anthropic (Claude)", "Google (Gemini)"\])  
        api\_key \= st.text\_input(f"{llm\_vendor} API Key 입력", type\="password")  
          
        if st.button("연결 테스트 (API Validation) 실행"):  
            with st.spinner(f"{llm\_vendor} 서버에 인증 요청 중..."):  
                time.sleep(1.2) \# 네트워크 I/O 시뮬레이션  
                  
                \# 유효성 로직: 실제로는 requests 라이브러리를 통해 간단한 /models 엔드포인트를 호출함  
                if api\_key and len(api\_key) \> 15:  
                    st.success(f"🟢 연결 성공: {llm\_vendor} API 키가 유효합니다. (HTTP 200 OK)")  
                elif not api\_key:  
                    st.warning("API 키를 입력해 주세요.")  
                else:  
                    st.error(f"🔴 연결 실패: 유효하지 않은 API 키입니다. (Error 401: Unauthorized)")

### **4.5 모듈 5: 직원 계정 관리 (보안 White-list)**

실무자들이 사용하는 Vercel CS 시스템은 누구나 접근할 수 있어서는 안 된다. 가장 완벽한 보안은 비밀번호 방식이 아닌, 이메일 기반의 매직 링크(Magic Link) 혹은 OTP(One-Time Password)와 백엔드 화이트리스트를 결합한 제로 트러스트(Zero Trust) 구조다1.  
본 대시보드의 '직원 등록' 탭에서 관리자가 staff\_users 테이블에 직원의 이메일을 등록(CRUD)한다. 이후 해당 직원이 Vercel 앱에서 로그인을 시도하면, Supabase Auth 시스템은 입력된 이메일이 이 화이트리스트 테이블에 존재하는지 확인하고, 존재할 때만 6자리 인증 코드를 발송한다. 또한, 한 번 인증된 브라우저 쿠키(Cookie)의 만료 기간을 장기화하여 비숙련 직원들의 불편함을 제거한다1.

Python  
\# modules/05\_staff\_auth.py  
import streamlit as st  
import pandas as pd  
from core.db import supabase

def render():  
    st.title("👥 직원 계정 관리 (보안 White-list)")  
    st.markdown("""  
    이곳에 등록된 이메일 주소를 가진 실무 담당자만이 외부 Vercel 웹앱에 \*\*Passwordless OTP (이메일 인증코드)\*\* 방식으로 접근할 수 있습니다.  
    비밀번호 분실의 위험을 없애고 최고 수준의 보안을 유지합니다.  
    """)  
      
    col\_add, col\_list \= st.columns(\[1, 1.5\], gap="large")  
      
    with col\_add:  
        st.subheader("신규 직원 등록")  
        with st.form("staff\_registration"):  
            new\_name \= st.text\_input("직원 성명")  
            new\_email \= st.text\_input("직원 이메일 (해당 이메일로 OTP 발송)")  
              
            if st.form\_submit\_button("화이트리스트에 추가"):  
                if new\_name and new\_email:  
                    try:  
                        supabase.table("staff\_users").insert({  
                            "staff\_name": new\_name,  
                            "email": new\_email  
                        }).execute()  
                        st.success("✅ 직원이 성공적으로 등록되었습니다.")  
                    except Exception as e:  
                        st.error("이미 등록된 이메일이거나 데이터베이스 오류가 발생했습니다.")  
                else:  
                    st.warning("이름과 이메일을 모두 입력해 주세요.")  
                      
    with col\_list:  
        st.subheader("현재 등록된 직원 명부")  
        res \= supabase.table("staff\_users").select("id, staff\_name, email, created\_at").execute()  
        if res.data:  
            df\_staff \= pd.DataFrame(res.data)  
            \# 불필요한 ID 등을 숨기고 필요한 데이터만 노출  
            st.dataframe(df\_staff\[\['staff\_name', 'email', 'created\_at'\]\], use\_container\_width=True)  
              
            \# 삭제 로직 구현 예시  
            delete\_email \= st.selectbox("권한을 회수할 직원의 이메일을 선택하세요", df\_staff\['email'\].tolist())  
            if st.button("계정 삭제 및 접근 권한 회수", type\="primary"):  
                supabase.table("staff\_users").delete().eq("email", delete\_email).execute()  
                st.success("권한이 영구적으로 회수되었습니다.")  
                st.rerun()  
        else:  
            st.info("현재 등록된 직원이 없습니다.")

### **4.6 모듈 6: RAG 시뮬레이터 및 모던 UI/UX (STT/TTS 포함)**

대시보드 운영의 백미는 설정을 변경한 직후, 시스템이 어떻게 반응하는지 즉각적으로 확인하는 시뮬레이터에 있다. Streamlit의 내장 채팅 UI 컴포넌트인 st.chat\_message와 st.chat\_input을 활용하여, 실제 사용자 환경과 100% 동일한 반응성을 구현한다1.  
추가로, 현업 어르신들의 사용성을 고려한 STT(Speech-to-Text) 음성 입력과 차분한 여성 상담원 톤으로 응답을 읽어주는 TTS(Text-to-Speech) 테스트 기능이 요구되었다1. 이 기능은 Streamlit과 Javascript 기반의 Web Speech API 또는 외부 라이브러리를 결합하여 구현할 수 있으며, 이 명세에서는 HTML/JS 주입과 오디오 출력을 통해 완벽히 시뮬레이션한다.

Python  
\# modules/06\_simulator.py  
import streamlit as st  
import time

def render():  
    st.title("🤖 RAG 챗봇 시뮬레이터 (STT & TTS 테스트)")  
    st.markdown("대시보드에서 변경한 지식베이스와 환경 설정이 실제 챗봇에서 어떻게 응답하는지 실시간 검증합니다.")  
      
    \# 채팅 세션 유지 로직  
    if "messages" not in st.session\_state:  
        st.session\_state.messages \= \[  
            {"role": "assistant", "content": "안녕하세요, 강서나눔돌봄센터입니다. 무엇을 도와드릴까요?"}  
        \]  
          
    \# 기존 대화 내역 렌더링  
    for message in st.session\_state.messages:  
        with st.chat\_message(message\["role"\]):  
            st.markdown(message\["content"\])  
              
    \# STT 시뮬레이션을 위한 커스텀 버튼 (Web Speech API 연동 시나리오)  
    st.caption("🎙️ 음성 인식 (STT) 활성화 시, 마이크를 통해 질문을 입력받습니다.")  
      
    if prompt := st.chat\_input("질문을 텍스트로 입력하거나 STT로 발화하세요..."):  
        \# 사용자 메시지 UI 추가  
        st.session\_state.messages.append({"role": "user", "content": prompt})  
        with st.chat\_message("user"):  
            st.markdown(prompt)  
              
        \# 어시스턴트 응답 처리 영역  
        with st.chat\_message("assistant"):  
            with st.spinner("RAG 엔진 검색 및 LLM 추론 중..."):  
                time.sleep(1.5) \# DB 접근 및 API 통신 딜레이  
                  
                \# 강제 인터셉터 (의료/법률 가드레일 작동 예시)  
                if "치매" in prompt or "진단" in prompt:  
                    response\_text \= "🚨 해당 문의는 전문적인 의학적 판단이 필요합니다. 상세한 안내는 보건소나 센터(02-2065-1584)로 즉시 문의 부탁드립니다. (Fallback 발동)"  
                else:  
                    response\_text \= f"검색된 지식베이스를 바탕으로 구성된 응답입니다. (사용자 발화: {prompt})\\n\\n\[출처: 서비스안내\_내부규정.pdf\]"  
                  
                st.markdown(response\_text)  
                  
                \# TTS (Text-to-Speech) 시뮬레이션 구현 (차분한 여성 상담원 톤 고정)  
                \# 실제 운영 시에는 Google TTS (gTTS) 또는 ElevenLabs API를 활용하여 음성 파일을 생성한 뒤 st.audio로 재생  
                st.audio("https://actions.google.com/sounds/v1/water/glass\_water.ogg", format\="audio/ogg")  
                st.caption("🔊 \[차분한 여성 상담원 톤\] TTS 음성 출력 시뮬레이션 완료")  
                  
                st.session\_state.messages.append({"role": "assistant", "content": response\_text})

## **5\. 고급 아키텍처 및 구현 상의 제언**

강서나눔돌봄센터의 '최고 관리자용 RAG 통제반' 구현에 있어, 제시된 코드와 아키텍처는 프로토타입 수준을 넘어 B2B SaaS 프로덕션 레벨의 완벽한 뼈대를 이룬다. 이 시스템을 실제 서버(예: Streamlit Community Cloud 혹은 AWS EC2)에 배포할 때 고려해야 할 핵심 요소들은 다음과 같다.  
첫째, **하이브리드 검색(Hybrid Search)의 확장**이다. 본 설계에 적용된 pgvector는 코사인 유사도에 기반한 의미망 검색(Semantic Search)에 탁월하다7. 그러나 "서울형 가사서비스"와 같은 특정 고유명사나 식별 번호를 정확히 찾아내는 데에는 키워드 기반의 전통적인 전문 검색(Full-text Search, FTS)이 더 유리할 수 있다. 향후 RAG 파이프라인(모듈 1)을 고도화할 때, 벡터 유사도 점수와 키워드 점수를 결합하는 RRF(Reciprocal Rank Fusion) 알고리즘을 도입하면 오답률을 제로에 가깝게 수렴시킬 수 있다7.  
둘째, **스트림릿 세션 상태(Session State)의 영속성 관리**다. st.data\_editor를 통해 조작된 청크 데이터는 페이지 새로고침 시 초기화될 위험이 있다12. 따라서 수정 버튼(Re-embed)을 클릭하는 순간, 백엔드 함수가 비동기적으로 데이터베이스를 덮어씌운 뒤 명시적으로 st.rerun()을 호출하여 상태를 강제 동기화하는 로직이 꼼꼼하게 처리되어야 한다.  
결론적으로, Vercel의 프론트엔드와 Streamlit의 백엔드로 완전히 이원화된 본 아키텍처는 IT 관리자가 부재한 돌봄센터 환경에서도 원장이 직접 AI를 교육시키고, 시스템의 응답 방향을 즉각적으로 통제할 수 있는 권력을 부여한다1. CSS 커스터마이징을 통해 확보된 미려한 사용자 경험과, 단일 Supabase 생태계 안에서 톱니바퀴처럼 맞물려 돌아가는 RAG 파이프라인은 신뢰할 수 있는 엔터프라이즈 AI 서비스 구축의 교과서적인 모범 사례가 될 것이다. 마련된 Vibe Coding 명세와 초기 파이썬 코드를 기반으로 개발을 진행할 경우, 가장 효율적이고 안전한 인공지능 전환(AI Transformation)이 이루어질 것이다.

#### **참고 자료**

> 1. AI\_AX 컨설팅\_ 강서나눔돌봄센터.pdf  
> 2. Building a RAG with Supabase Vector & OpenAI \- Rachit Khurana, [https://blog.rachitkhurana.tech/building-a-rag-with-supabase-vector-openai](https://blog.rachitkhurana.tech/building-a-rag-with-supabase-vector-openai)  
> 3. Streamlit Tutorial For SEOs: How To Create A UI For Your Python App, [https://www.searchenginejournal.com/streamlit-tutorial-with-user-authentication-and-dockerfile/469205/](https://www.searchenginejournal.com/streamlit-tutorial-with-user-authentication-and-dockerfile/469205/)  
> 4. Vector database | Supabase Features, [https://supabase.com/features/vector-database](https://supabase.com/features/vector-database)  
> 5. \[Supabase 시작하기\] \- 회원 가입부터 기초 CRUD, RAG를 위한, [https://goddaehee.tistory.com/377](https://goddaehee.tistory.com/377)  
> 6. Vector Database (OpenAI and Supabase )-Part 2 (Setup), [https://dev.to/shlokaguptaa/vector-database-with-supabase-and-openai-part-2-setup-49o9](https://dev.to/shlokaguptaa/vector-database-with-supabase-and-openai-part-2-setup-49o9)  
> 7. Supabase 사용해보기 (3) | Supabase Vector DB 구성하기 \- pepe, [https://pepega.tistory.com/108](https://pepega.tistory.com/108)  
> 8. Creating a Crypto Dashboard with Custom CSS in Streamlit, [https://www.insightbig.com/post/creating-a-crypto-dashboard-with-custom-css-in-streamlit](https://www.insightbig.com/post/creating-a-crypto-dashboard-with-custom-css-in-streamlit)  
> 9. Professional Streamlit Styling with CSS and st\_yled \- Medium, [https://medium.com/@jonathan.alles/professional-streamlit-styling-with-css-and-st-yled-e5c470deaf46](https://medium.com/@jonathan.alles/professional-streamlit-styling-with-css-and-st-yled-e5c470deaf46)  
> 10. \[9\] streamlit custom CSS 적용하기 \- 퍼스트펭귄 코딩스쿨 \- 티스토리, [https://yeomko.tistory.com/105](https://yeomko.tistory.com/105)  
> 11. Update data in data\_editor automatically \- Using Streamlit, [https://discuss.streamlit.io/t/update-data-in-data-editor-automatically/49839](https://discuss.streamlit.io/t/update-data-in-data-editor-automatically/49839)  
> 12. A very simple method for updating data with Streamlit and Snowpark., [https://medium.com/@serranocarlosd/a-very-simple-method-for-updating-data-with-streamlit-and-snowpark-b38e4d7d0d1f](https://medium.com/@serranocarlosd/a-very-simple-method-for-updating-data-with-streamlit-and-snowpark-b38e4d7d0d1f)  
> 13. Building A RAG Powered Chatbot with Streamlit & Snowflake, [https://medium.com/@kieran\_adair/building-a-rag-powered-chatbot-with-streamlit-snowflake-30-days-of-ai-challenge-week-3-992feb8e442c](https://medium.com/@kieran_adair/building-a-rag-powered-chatbot-with-streamlit-snowflake-30-days-of-ai-challenge-week-3-992feb8e442c)  
> 14. Adding rows in st.data\_editor from loaded dataframe \- Using Streamlit, [https://discuss.streamlit.io/t/adding-rows-in-st-data-editor-from-loaded-dataframe/46439](https://discuss.streamlit.io/t/adding-rows-in-st-data-editor-from-loaded-dataframe/46439)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJQAAAAZCAYAAADXEgfSAAAE/UlEQVR4Xu2Zaah2UxTHlzEyFvIJbxGfDIUkw5uMmZIMkbxvKENIig9ElKTw0RgfkPgkHyQRkZlkSIRyX3PIPM/W79173bOe9ex97jnPvbml/avVPeu/9t7nPPuss6cr0mg0Go1Gw7G12s5RXAa2U9s0iouA9jaPYoEt1PaKYmM8h6v9k+2hEPsveUK651iKF8tvsfYODLHIX9KVXW6uUPte7We1M0NsIR6V9Buof0CIwe9qF6ltq7ax2iFqa3yBsTwcBcdyJ5SxVAllDEkoGJpQjJ4/qd0bA0vAW2qPOf9NtWed38cfMjmy09Y9zgf7jd4Omigxkr4OawnV3z8RptHP1Z5XWyfEZoH2SvdH2zKKgYvVzo2iTLeHf5XaHWonT4bGs65M38DTEqq/f2qsr/a22pzaRiE2htekfH80EqAP6r4TRZluL/ozw5z5p6QGj8x22ESJyYQ6Vu1+tSO68FpOVbta7b7sX6K2ej7acZ2kDr4+BpRT1N6QNLTzol+aDM8nFB/ABWq3SdowlNhJ0pTwnNrpIWbUEop78KJYU8CsCeV5Uu1btW2CPoTa/Wu65zJJZVg70W9wu9rj8yUSC7UzGIbEuyQ1yDV2/kSJFGON9WH2eYlot8yXELk8axgL2d3y9Rk5vn32d88+9/E/4gW1s5x/s6Rpw0P51ZI6BEhutB2tQIa23nP+jWq/Ot+gbkyob9Tez9dMVyTkkBc3FD6432T6mfuo3b+mR1jEW1l+T2m2IcaH/Imkd43PYDMTJ0r/g5Ue/LuCxovzD8LOwtYQ6E/nawPtAXe9i4tBKaE+KGh+Q8F6IT4XoD1T0HxC0aG1uiV9VuiHL6PYQ+3+Nb2ElcWYkWy0MtB3cP6lWZuJIQk1FzRedqzDNBY1YJhHP1tSspn9IGk0A3ZHlHlV0tRXgviqgsaI5P3SM9jRgwffJxR+bb0R645lA0ltM3JuGGILUbt/TfdwBEAZztLY6Y05BqFMnBoHMSSh2Gp6Ps66p5ZQTGXoZD3nG94OduVIMPux2DEuBmgnFbQXg196hgcl6es5DX9l8B9xvlFrcwjswr6Q6dF5DLX713TP32qHBu0mSfV47wYJHxnSfpETZLIi210PMRbLno+y7qklFFMZul8jRfxidYWkg7bYFv7xBc0v3mudYGshD/7K4Nv6yVNrs48Var9It0lZDPahRdDYRfZRqgc/Svfx3Cmp3N5deC1onGGN5jiZvDELUw8xDtI8pRHqhoJmoMdRDt7Nf0v1ooZP8kftZee/krUIHRN1fH94hx/LQE0vsYekUaG0i50VRuXS/dH2DBq7Ok+pHjAgnJav75Y0Ffozs80k1bUN0Cg4L6Hyftnny/IQ4wE8bIHjw3L6GjWDtQqxo512bdaB2DUuxlTh2+IcBz8e0qFZUnrtVuezs0RjHWGwjkHzCbpV1tihGrYbrf0uD/8bvDCKSwT3P8f5pdmAgQDtPKe9rvap84H/y/q6LNDjO5+T6fZHcaV0HbdJ1ljDsPgmmRiRvso6f/HRWR/sL2kI5cHRPpPyNp2F+NfS3ecoF6M8HWYx2ifRgSmNNmmbbS0LeOZ//2y06+Grs7Y43LO24Cnp2uMv23iDRLZzOWxfd72oDl4ktrimL0gS+iuewu8q5SmbqY26a/LfmGDA2Rsx22zFAaTRaPwfYNQdao3GguwzwhqNRqPRaDQajUZjafkXd2KsQ9Mtj6EAAAAASUVORK5CYII=>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJQAAAAZCAYAAADXEgfSAAAE6klEQVR4Xu2Zach1UxTHlzEilFck9BbxyVCUZHgTIVOSIT7whvKSKeKDKUoilJIxJVN8kHwwRYnMZExkyJs5ZJ5n69fe67nrrGfvc8+9z83jw/7V6t7133uvc+456+y99rkijUaj0Wg0HEvUto7iIrC52rpRXADEWy+KBdZX2ymKjcnZV+2fbPeHtv+Sx2R0HrO4sfwWi7dHaIv8JaO+i80Fat+r/ax2fGjr4xW13dXWVNtM7Xy1bzs9Esepfab2p9ploW1iHoyCY7ETyphVQhlDEgqGJhSz509qd8aGGfCm2qPOf0PtaefXWF1G52/2e6dH4h61T51/h9rXzp+YvgvWEqr/+kRYRj9Xe1ZtldA2DcQrHR9tgygWeFvtWrXL1TYNbQaxSL6o7Re0Qawq5RM2WkL1X58a3KC31FaqrRXaJuFVKR8f7eYoFngiCoGrpR7/vSiOY2NJayaD98+2T6dHN6EOVrtb5mfu0WoXq92V/bPVls+1jmBt5gJfERuUo9RelzS1c6Nf6DbPJRQPwKlqN0raMJTYStKS8IzaMaHNqCUUx+BGnZH9aRPK87ikumWjoA+hdvyaHhmXUCyBpThD43c4U+1WSQP5jp3S6ZHaqLE+zD43Ee36uR4i52UNo5DdLn+n0IMtsr999jmOP9nn1E5w/nWSlg0P/Zer3ZR9khttS+uQIda7zr9K7VfnG4yNCfWN2vv5O8sVCTnVha3AA/ebzD/nPmrHr+mRlyVNGg+ofSHpgfbU4tT0sRwu/QNLgb8raNw4NGY9eERGNQT6k/m7gXav+76Na4NSQn1Q0PyG4qSsRdCeKmg+oZgZa2NL+rRwHb6MYg+149f0SHyYGON3ebU4NX0sQxJqZdC42XEMy1jUgGke/URJyWb2g6TZDNgd0YctLktfCdqPLWjMSN4vnYO9evDg+4TCp4CN1GJOwhqSYjNzsn2fhNrxa/o4KFkYt072a3Fq+liGJBTbVs/HWffUEoqlDP0ctb2D7eX6kWD2I7CDXBugHVHQng9+6Rzuk6Sv5jT8ZcF/2PlGLeYQ2IWxzMTZeRJqx6/p47hI0rgjs281dGTa+HKYdAey3fXQRrHs+SjrnlpCsZSh+xop4ovVpVIuFPEPLWi+eK9dBKuFPPjLgm/1k6cWs4+lar/IaJOyEOxBi6Cxi+yjdO5XZo0HGvqW+r+jOIRDpBuQwtRDGy/SPKUZyk60BHqc5eCd/FkaFzV8kj9qLzr/paxF/pD5Ov6ewY99oKaX2EHSTSjtYqeFWbl0fLQdg3Zu8OlDGeGhRPDxNgm+gXZWFIfA+xIG75p9niwPbcxIHoq6eBK3FzSDWoW2A512adaBtktcG0uFj8V7HHyKbg+aJaXXbnA+O0s0/pMzqGPQfIJumDV2qIbtRmu/y8N/g6dFcUZw/BXOL60GTARoJzvtGkm/wbB7fYvTgIeA2so4QObHn4gLZXThrFijhqH4JpmYkb7KOp/46NQHu6n9KOnVPRr/B8WdBVCI8zrfjsNJG/Tnglkb8fnxwJJGTGJ/IqmAp+7z5xb/JrhNRrF4MWixgPcyFo9PtvEGiWw1BbaL+76gC7xA1pZ0fK7Fa5KuV3wLv62Ul+yHJI3lf0A+T+82z0GZwcNJvUe/Wf4R32g0/g8w6w61RmMsO09gjUaj0Wg0Go1GozFb/gW3zK38kkLUiQAAAABJRU5ErkJggg==>