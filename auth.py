"""
Google OAuth 2.0 認証を管理するモジュール

ユーザーのGoogleアカウント認証とトークン管理を行います。
トークンはStreamlitのセッション状態とホームディレクトリのファイルに保存します。
ファイル保存により、ブラウザリフレッシュ・Streamlit再起動後も認証状態が維持されます。

【注意】PKCEのcode_verifierは一時ファイルに保存します。
OAuthリダイレクト時にStreamlitのセッション状態がリセットされるため、
セッション状態だけでは保持できないためです。
"""

import os
import ssl
import json
import secrets
import hashlib
import base64
import tempfile
import certifi
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ローカル開発時はHTTP（非SSL）を許可する設定
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# WindowsのSSL証明書問題対策
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# Google APIへのアクセス権限（スコープ）
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501")

# PKCEのcode_verifierを保存する一時ファイルのパス
# セッション状態はOAuthリダイレクト後にリセットされるため一時ファイルを使う
_PKCE_FILE = os.path.join(tempfile.gettempdir(), "schedule_tool_pkce_verifier.json")

# トークン永続化ファイル（ブラウザリフレッシュ・Streamlit再起動後も認証を維持するため）
_TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".schedule_tool_token.json")


def _get_secrets_file() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secrets.json")


def _create_flow() -> Flow:
    """OAuthフローを作成する（Streamlit SecretsまたはローカルJSONファイルから認証情報を読み込む）"""
    # Streamlit Cloud: st.secrets から認証情報を読み込む
    if "google_client_secrets" in st.secrets:
        s = st.secrets["google_client_secrets"]
        client_config = {
            "web": {
                "client_id": s["client_id"],
                "client_secret": s["client_secret"],
                "project_id": s.get("project_id", ""),
                "auth_uri": s.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": s.get("token_uri", "https://oauth2.googleapis.com/token"),
                "auth_provider_x509_cert_url": s.get(
                    "auth_provider_x509_cert_url",
                    "https://www.googleapis.com/oauth2/v1/certs",
                ),
                "redirect_uris": [REDIRECT_URI],
            }
        }
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)

    # ローカル開発: client_secrets.json から読み込む
    secrets_file = _get_secrets_file()
    if not os.path.exists(secrets_file):
        raise FileNotFoundError(
            f"クライアントシークレットファイル '{secrets_file}' が見つかりません。\n"
            "Google Cloud ConsoleでOAuth 2.0クライアントIDを作成し、"
            "JSONをダウンロードしてプロジェクトフォルダに配置してください。"
        )
    return Flow.from_client_secrets_file(secrets_file, scopes=SCOPES, redirect_uri=REDIRECT_URI)


def _generate_pkce_pair() -> tuple[str, str]:
    """PKCEのcode_verifier と code_challenge を生成する"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _save_pkce_verifier(verifier: str) -> None:
    """code_verifierを一時ファイルに保存する（セッション跨ぎのため）"""
    with open(_PKCE_FILE, "w") as f:
        json.dump({"verifier": verifier}, f)


def _load_pkce_verifier() -> str | None:
    """一時ファイルからcode_verifierを読み出して削除する"""
    if not os.path.exists(_PKCE_FILE):
        return None
    try:
        with open(_PKCE_FILE) as f:
            data = json.load(f)
        os.remove(_PKCE_FILE)
        return data.get("verifier")
    except Exception:
        return None


def get_authorization_url() -> str:
    """Google認証ページへのURLを生成する"""
    flow = _create_flow()

    # PKCEペアを生成し、code_verifierを一時ファイルに保存
    code_verifier, code_challenge = _generate_pkce_pair()
    _save_pkce_verifier(code_verifier)

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return auth_url


def exchange_code_for_token(code: str) -> None:
    """Googleからのコードをアクセストークンに交換する"""
    flow = _create_flow()
    flow.oauth2session.verify = certifi.where()

    # 一時ファイルからcode_verifierを取得
    code_verifier = _load_pkce_verifier()

    flow.fetch_token(code=code, code_verifier=code_verifier)
    _save_credentials(flow.credentials)


def _save_token_to_file(data: dict) -> None:
    """トークンをホームディレクトリのファイルに保存する"""
    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _delete_token_file() -> None:
    """永続化ファイルを削除する（ログアウト時）"""
    try:
        if os.path.exists(_TOKEN_FILE):
            os.remove(_TOKEN_FILE)
    except Exception:
        pass


def _save_credentials(creds: Credentials) -> None:
    """認証情報をStreamlitセッション状態とファイルに保存する"""
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    st.session_state["token_data"] = data
    _save_token_to_file(data)


def get_credentials() -> Credentials | None:
    """現在の認証情報を取得する（期限切れなら自動更新）"""
    if "token_data" not in st.session_state:
        return None

    data = st.session_state["token_data"]
    creds = Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data.get("scopes", SCOPES),
    )

    if creds.expired and creds.refresh_token:
        try:
            import requests as req_lib
            session = req_lib.Session()
            session.verify = certifi.where()
            creds.refresh(Request(session=session))
            _save_credentials(creds)
        except Exception as e:
            st.error(f"認証トークンの更新に失敗しました。再度ログインしてください。\n詳細: {e}")
            logout()
            return None

    return creds


def is_authenticated() -> bool:
    return "token_data" in st.session_state


def restore_session_from_file() -> bool:
    """
    永続化ファイルからトークンを復元してセッションに読み込む

    ブラウザリフレッシュやStreamlit再起動後でも認証状態を維持するために使用。

    Returns:
        True: 復元成功（認証済み状態に）
        False: ファイルなし・読み込み失敗・トークン更新失敗
    """
    if "token_data" in st.session_state:
        return True

    if not os.path.exists(_TOKEN_FILE):
        return False

    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
    except Exception:
        _delete_token_file()
        return False

    st.session_state["token_data"] = data

    # 期限切れの場合は自動更新（失敗したらログアウト扱い）
    creds = get_credentials()
    return creds is not None


def logout() -> None:
    keys_to_remove = ["token_data", "oauth_state", "user_info", "free_slots", "messages"]
    for key in keys_to_remove:
        st.session_state.pop(key, None)
    _delete_token_file()
