import os
import streamlit as st
from core.db import supabase, is_mock_db

try:
    from supabase import create_client
except ImportError:
    create_client = None


def _get_auth_client():
    """
    OTP 발송/검증 전용 anon 클라이언트를 매 호출마다 새로 만든다.
    core.db.supabase(service_role, 모듈 전역 싱글턴)로 로그인 시도를 처리하면
    Streamlit의 공유 프로세스에서 동시 접속자끼리 Auth 세션이 서로 덮어써질 수 있어 분리한다.
    """
    if create_client is None:
        return None
    try:
        url = st.secrets.get("SUPABASE_URL")
        anon_key = st.secrets.get("SUPABASE_ANON_KEY")
    except Exception:
        url = None
        anon_key = None
    if not url:
        url = os.environ.get("SUPABASE_URL")
    if not anon_key:
        anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not anon_key or "your-supabase" in url:
        return None
    return create_client(url, anon_key)


def send_otp(email: str):
    email = (email or "").strip()
    if not email or "@" not in email:
        return {"error": "유효한 이메일 주소를 입력해 주세요."}

    if is_mock_db:
        return {"success": True, "is_mock": True}

    client = _get_auth_client()
    if client is None:
        return {"error": "SUPABASE_ANON_KEY가 설정되지 않아 로그인 기능을 사용할 수 없습니다. 관리자에게 문의하세요."}

    try:
        # 직원 계정은 05_staff_auth.py에서 화이트리스트 등록 시 이미 생성해 두므로,
        # 여기서는 신규 가입을 막아(should_create_user: False) 미등록 이메일을 발송 시점에 바로 거부한다.
        client.auth.sign_in_with_otp({
            "email": email,
            "options": {"should_create_user": False},
        })
    except Exception:
        return {"error": "등록되지 않은 이메일이거나 인증번호 발송에 실패했습니다. 관리자에게 계정 등록을 요청해 주세요."}
    return {"success": True}


def verify_otp(email: str, otp: str):
    email = (email or "").strip()
    otp = (otp or "").strip()
    if not otp or len(otp) < 6:
        return {"error": "이메일로 받은 인증번호를 정확히 입력해 주세요."}

    if is_mock_db:
        return {"success": True, "email": email}

    client = _get_auth_client()
    if client is None:
        return {"error": "SUPABASE_ANON_KEY가 설정되지 않아 로그인 기능을 사용할 수 없습니다."}

    try:
        client.auth.verify_otp({"email": email, "token": otp, "type": "email"})
    except Exception:
        return {"error": "잘못된 인증번호입니다. 다시 확인해 주세요."}
    finally:
        try:
            client.auth.sign_out()
        except Exception:
            pass

    return _check_admin_whitelist(email)


def _check_admin_whitelist(email: str):
    try:
        res = (
            supabase.table("staff_users")
            .select("is_active, is_admin")
            .eq("email", email)
            .execute()
        )
        row = res.data[0] if res.data else None
    except Exception:
        row = None

    if not row or not row.get("is_active") or not row.get("is_admin"):
        return {"error": "최고 관리자 권한이 없는 계정입니다. 관리자에게 권한 등록을 요청해 주세요."}

    return {"success": True, "email": email}
