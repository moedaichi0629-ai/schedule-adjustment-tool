"""
日程調整支援ツール - メインアプリ

Googleカレンダーと連携し、空き時間の候補と送信用文章を自動生成するWebアプリです。
フリーランス・経営者・営業の方の日程調整を効率化します。
"""

# SSL証明書の設定（WindowsでSSLエラーが起きる問題の対策）
# 他のimportより先に実行する必要があるため、ここに記述
import os
import ssl
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# ssl.create_default_context をパッチしてcertifiのCA証明書を使わせる
_orig_ssl_context = ssl.create_default_context
def _patched_ssl_context(purpose=ssl.Purpose.SERVER_AUTH, *args, **kwargs):
    ctx = _orig_ssl_context(purpose, *args, **kwargs)
    ctx.load_verify_locations(certifi.where())
    return ctx
ssl.create_default_context = _patched_ssl_context

from datetime import date, timedelta

import streamlit as st
from dotenv import load_dotenv

import auth
import calendar_service
import message_generator

# .envファイルから環境変数を読み込む
load_dotenv()

# ページの基本設定
st.set_page_config(
    page_title="日程調整支援ツール",
    page_icon="📅",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# カスタムCSS（全体のデザイン調整・モバイル対応）
st.markdown(
    """
    <style>
    .main-title { font-size: 2rem; font-weight: bold; margin-bottom: 0.2rem; }
    .subtitle { color: #666; font-size: 0.95rem; margin-bottom: 1.5rem; }
    .slot-item { padding: 0.4rem 0; font-size: 1.05rem; }
    .copy-hint { color: #888; font-size: 0.8rem; margin-top: 0.3rem; }

    /* モバイル対応 */
    @media (max-width: 640px) {
        .main-title { font-size: 1.4rem; }
        .subtitle { font-size: 0.85rem; }
        .block-container { padding: 1rem 0.75rem 2rem; }
        [data-testid="stButton"] > button {
            min-height: 2.75rem;
            font-size: 1rem;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input {
            font-size: 1rem;
        }
        [data-testid="stSelectbox"] select {
            font-size: 1rem;
        }
        [data-testid="stTab"] button {
            font-size: 0.85rem;
            padding: 0.4rem 0.5rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# OAuth コールバック処理（最初に実行）
# ─────────────────────────────────────────────
def handle_oauth_callback() -> bool:
    """
    Googleからのリダイレクト（OAuth コールバック）を処理する

    URLに ?code=... が含まれている場合にトークン交換を実行する。
    Returns: True なら処理済み（rerun が必要）
    """
    params = st.query_params

    if "code" not in params or auth.is_authenticated():
        return False

    code = params["code"]
    with st.spinner("Googleアカウントで認証中..."):
        try:
            auth.exchange_code_for_token(code)
            # URLのクエリパラメータをクリアして再描画
            st.query_params.clear()
            return True
        except Exception as e:
            st.error(
                f"認証に失敗しました。もう一度ログインボタンを押してください。\n詳細: {e}"
            )
            st.stop()


# ─────────────────────────────────────────────
# ログインページ
# ─────────────────────────────────────────────
def show_login_page() -> None:
    """ログイン前のトップページを表示する"""
    st.markdown('<div class="main-title">📅 日程調整支援ツール</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">Googleカレンダーと連携して、空き時間の候補と送信用文章を自動生成します</div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # 機能紹介
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### できること")
        st.markdown(
            "- ✅ 空き時間を自動で抽出\n"
            "- ✅ 候補日を最大5件提案\n"
            "- ✅ LINE・メール用の文章を生成\n"
            "- ✅ 確定した予定をカレンダー登録"
        )
    with col2:
        st.markdown("#### こんな方におすすめ")
        st.markdown(
            "- 👔 フリーランス・個人事業主\n"
            "- 📊 営業・コンサルタント\n"
            "- 👩‍💼 面談・商談が多い方\n"
            "- 📱 毎回の日程調整が面倒な方"
        )

    st.markdown("---")
    st.markdown("### Googleアカウントでログイン")
    st.markdown("カレンダーの読み取りと予定の登録に、Googleアカウントへのアクセスが必要です。")

    try:
        auth_url, redirect_uri = auth.get_authorization_url()
        st.caption(f"🔧 リダイレクトURI: `{redirect_uri}`")
        # target="_self" で同じタブで開く（OAuthに必須）
        st.markdown(
            f"""
            <a href="{auth_url}" target="_self" style="
                display: inline-block;
                padding: 0.6rem 1.4rem;
                background-color: #4285F4;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-size: 1rem;
                font-weight: 500;
                margin-top: 0.5rem;
            ">
                🔐 Googleでログイン
            </a>
            """,
            unsafe_allow_html=True,
        )
    except FileNotFoundError as e:
        st.error(str(e))
        st.markdown(
            """
            **設定手順:**
            1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
            2. 「APIとサービス」→「ライブラリ」で **Google Calendar API** を有効化
            3. 「APIとサービス」→「認証情報」でOAuth 2.0クライアントIDを作成
               - アプリの種類: **ウェブアプリケーション**
               - 承認済みのリダイレクトURI: `http://localhost:8501`
            4. JSONをダウンロードして `client_secrets.json` という名前で保存
            5. このフォルダ（schedule-adjustment-tool/）に配置して再起動
            """
        )
    except Exception as e:
        st.error(f"認証URLの生成に失敗しました: {e}")


# ─────────────────────────────────────────────
# メインアプリ（ログイン後）
# ─────────────────────────────────────────────
def show_main_app() -> None:
    """ログイン後のメインUIを表示する"""
    creds = auth.get_credentials()
    if creds is None:
        # トークンが無効な場合はログアウト
        auth.logout()
        st.rerun()
        return

    # ── ヘッダー（ユーザー名・ログアウト） ──
    try:
        if "user_info" not in st.session_state:
            with st.spinner("ユーザー情報を取得中..."):
                st.session_state["user_info"] = calendar_service.get_user_info(creds)
        user_info = st.session_state["user_info"]
        user_name = user_info.get("name", "ユーザー")
    except Exception:
        user_name = "ユーザー"

    header_col, logout_col = st.columns([4, 1])
    with header_col:
        st.markdown('<div class="main-title">📅 日程調整支援ツール</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="subtitle">ようこそ、{user_name} さん</div>', unsafe_allow_html=True)
    with logout_col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("ログアウト", use_container_width=True):
            auth.logout()
            st.rerun()

    st.markdown("---")

    # ── セクション1: 空き時間の検索条件入力 ──
    st.subheader("① 空き時間を検索")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input(
            "開始日",
            value=date.today() + timedelta(days=1),
            min_value=date.today(),
        )
    with col2:
        end_date = st.date_input(
            "終了日",
            value=date.today() + timedelta(days=14),
            min_value=date.today(),
        )

    # ── 希望時間帯（複数追加可） ──
    st.markdown("**希望時間帯**（複数追加できます）")

    # 時間帯リストを一意なIDで管理（インデックスではなくIDを使うと削除が安全）
    if "tr_ids" not in st.session_state:
        st.session_state["tr_ids"] = [0]
        st.session_state["tr_counter"] = 1
        st.session_state["tr_s_0"] = 18  # デフォルト: 夜18時
        st.session_state["tr_e_0"] = 22

    # 各時間帯の入力行を表示（スマートフォン対応: 3列レイアウト）
    ids_to_delete = []
    for uid in list(st.session_state["tr_ids"]):
        c1, c2, c3 = st.columns([3, 3, 1])
        with c1:
            st.number_input(
                "開始（時）", min_value=0, max_value=23,
                key=f"tr_s_{uid}", label_visibility="collapsed",
            )
        with c2:
            st.number_input(
                "終了（時）", min_value=1, max_value=24,
                key=f"tr_e_{uid}", label_visibility="collapsed",
            )
        with c3:
            # 最低1つは残す
            if len(st.session_state["tr_ids"]) > 1:
                if st.button("✕", key=f"tr_del_{uid}"):
                    ids_to_delete.append(uid)
        s = st.session_state.get(f"tr_s_{uid}", 0)
        e = st.session_state.get(f"tr_e_{uid}", 1)
        label = f"⏰ {s}:00 〜 {e}:00"
        if s >= e:
            label += " ⚠️ 開始≥終了"
        st.caption(label)

    # 削除処理（ボタンが押されたIDを除去してrerun）
    if ids_to_delete:
        for uid in ids_to_delete:
            st.session_state["tr_ids"].remove(uid)
        st.rerun()

    # 時間帯を追加するボタン
    if st.button("＋ 時間帯を追加", key="btn_add_tr"):
        new_id = st.session_state["tr_counter"]
        st.session_state["tr_counter"] += 1
        st.session_state["tr_ids"].append(new_id)
        # 新しい時間帯のデフォルト値を設定
        st.session_state[f"tr_s_{new_id}"] = 9
        st.session_state[f"tr_e_{new_id}"] = 12
        st.rerun()

    # 現在の時間帯リストを取得（バリデーション済み）
    time_ranges = [
        (st.session_state[f"tr_s_{uid}"], st.session_state[f"tr_e_{uid}"])
        for uid in st.session_state["tr_ids"]
    ]
    valid_ranges = [(s, e) for s, e in time_ranges if s < e]

    # ── 打ち合わせ時間（自由入力） ──
    duration_minutes = st.number_input(
        "打ち合わせ時間（分）",
        min_value=15,
        max_value=480,
        value=60,
        step=15,
        help="15分単位で入力できます（例：30、45、60、90、120）",
    )

    if st.button("🔍 空き時間を検索", type="primary", use_container_width=True):
        if start_date > end_date:
            st.error("開始日は終了日より前の日付を設定してください。")
        elif not valid_ranges:
            st.error("有効な時間帯がありません。開始時刻を終了時刻より小さくしてください。")
        else:
            with st.spinner("カレンダーを確認中... しばらくお待ちください"):
                try:
                    free_slots = calendar_service.get_free_slots(
                        creds,
                        start_date,
                        end_date,
                        valid_ranges,
                        int(duration_minutes),
                        max_slots=5,
                    )
                    st.session_state["free_slots"] = free_slots
                    # 検索条件が変わったのでメッセージ・登録情報をリセット
                    st.session_state.pop("messages", None)
                    st.session_state.pop("registered_event", None)
                    st.session_state.pop("confirmation_messages", None)
                except Exception as e:
                    st.error(f"カレンダーの取得中にエラーが発生しました。\n詳細: {e}")

    # ── セクション2: 候補日の表示 ──
    if "free_slots" not in st.session_state:
        return  # まだ検索していない

    free_slots = st.session_state["free_slots"]

    st.markdown("---")
    st.subheader("② 候補日")

    if not free_slots:
        st.info(
            "指定した期間・時間帯に空きが見つかりませんでした。\n"
            "期間を延ばすか、希望時間帯を変更してみてください。"
        )
        return

    for i, slot in enumerate(free_slots, 1):
        st.markdown(f'<div class="slot-item"><b>{i}.</b> {slot["display"]}</div>', unsafe_allow_html=True)

    # ── セクション3: 送信用文章の生成 ──
    st.markdown("---")
    st.subheader("③ 送信用文章を生成")

    # ── モード選択ラジオボタン ──
    msg_mode = st.radio(
        "文章作成モード",
        options=["自分から候補日を送る", "相手の文章に返信する"],
        help="「自分から」は候補日をそのまま送る文章を作成します。「返信する」は相手のメッセージに合わせた返信文を作成します。",
    )

    # モードが切り替わったら以前の生成結果をリセット
    if st.session_state.get("last_msg_mode") != msg_mode:
        st.session_state.pop("messages", None)
        st.session_state["last_msg_mode"] = msg_mode

    # ── 返信モードのみ：相手の文章入力欄を表示 ──
    received_message = ""
    if msg_mode == "相手の文章に返信する":
        st.caption("相手から届いたメッセージを貼り付けると、内容に合わせた返信文を生成します。")
        received_message = st.text_area(
            "相手から届いた文章",
            placeholder=(
                "例：来週どこかで打ち合わせできますか？\n"
                "可能な日程をいくつか教えてください。"
            ),
            height=120,
            key="received_message_input",
        )

    # ── 文章生成ボタン ──
    if st.button("✉️ 送信用文章を生成する", use_container_width=True):
        # 返信モードで相手の文章が未入力の場合はエラー
        if msg_mode == "相手の文章に返信する" and not received_message.strip():
            st.error("相手から届いた文章を入力してください。")
        else:
            with st.spinner("文章を生成中..."):
                if msg_mode == "相手の文章に返信する":
                    # 返信モード：受信メッセージと候補日をもとに返信文を生成
                    messages = message_generator.generate_reply_messages(
                        free_slots, received_message.strip()
                    )
                else:
                    # 送信モード：候補日をもとに送信文を生成
                    messages = message_generator.generate_messages(free_slots)

                st.session_state["messages"] = messages

    # ── 生成結果のタブ表示 ──
    if "messages" in st.session_state:
        messages = st.session_state["messages"]

        # モードに応じてラベルを変える
        if st.session_state.get("last_msg_mode") == "相手の文章に返信する":
            section_label = "返信文（4種類）"
        else:
            section_label = "送信文（4種類）"

        st.caption(f"✅ {section_label}を生成しました。タブを切り替えてコピーしてください。")

        tab1, tab2, tab3, tab4 = st.tabs(
            ["📱 LINE（短め）", "📱 LINE（丁寧）", "📧 メール（短め）", "📧 メール（丁寧）"]
        )

        with tab1:
            st.text_area(
                "コピーしてそのまま使えます",
                value=messages.get("line_short", ""),
                height=200,
                key="ta_line_short",
            )
        with tab2:
            st.text_area(
                "コピーしてそのまま使えます",
                value=messages.get("line_polite", ""),
                height=240,
                key="ta_line_polite",
            )
        with tab3:
            st.text_area(
                "コピーしてそのまま使えます",
                value=messages.get("email_short", ""),
                height=200,
                key="ta_email_short",
            )
        with tab4:
            st.text_area(
                "コピーしてそのまま使えます",
                value=messages.get("email_polite", ""),
                height=280,
                key="ta_email_polite",
            )
        st.markdown(
            '<div class="copy-hint">※ テキストエリアをクリックして Ctrl+A → Ctrl+C でコピーできます</div>',
            unsafe_allow_html=True,
        )

    # ── セクション4: カレンダーに予定を登録 ──
    st.markdown("---")
    st.subheader("④ カレンダーに登録")
    st.caption("日程が確定したら、Googleカレンダーに直接登録できます。")

    # 候補日の選択肢を作成
    slot_options = {f"{i}. {slot['display']}": slot for i, slot in enumerate(free_slots, 1)}
    selected_label = st.selectbox("登録する候補日を選択", options=list(slot_options.keys()))
    selected_slot = slot_options[selected_label]

    event_title = st.text_input(
        "予定のタイトル",
        placeholder="例：〇〇社との商談、田中さんとの打ち合わせ",
    )
    event_description = st.text_area(
        "備考・メモ（任意）",
        placeholder="例：オンラインMTG / Zoom: https://... / 場所: 新宿〇〇ビル",
        height=80,
    )

    if st.button("📆 Googleカレンダーに登録", type="primary", use_container_width=True):
        if not event_title.strip():
            st.error("予定のタイトルを入力してください。")
        else:
            with st.spinner("カレンダーに登録中..."):
                try:
                    calendar_service.create_calendar_event(
                        creds,
                        event_title.strip(),
                        selected_slot["start"],
                        selected_slot["end"],
                        event_description.strip(),
                    )
                    # 登録成功：確認メッセージ生成用に情報を保存
                    st.session_state["registered_event"] = {
                        "title": event_title.strip(),
                        "slot": selected_slot,
                    }
                    st.session_state.pop("confirmation_messages", None)
                    st.success(
                        f"✅ 登録完了！\n\n"
                        f"「{event_title}」を **{selected_slot['display']}** でGoogleカレンダーに登録しました。\n\n"
                        "↓ 下の「⑤ 確認メッセージを生成」で相手への連絡文を作れます。"
                    )
                except Exception as e:
                    st.error(f"カレンダーへの登録中にエラーが発生しました。\n詳細: {e}")

    # ── セクション5: カレンダー登録後の確認メッセージ ──
    if "registered_event" in st.session_state:
        reg = st.session_state["registered_event"]
        st.markdown("---")
        st.subheader("⑤ 確認メッセージを生成")
        st.caption("確定した日時をもとに、相手へ送る「日程確定のご連絡」文章を作成します。")

        # 登録済み予定の情報を表示
        st.info(
            f"📅 **{reg['slot']['display']}** に「{reg['title']}」を登録済みです。"
        )

        # ZoomなどのURL入力
        meeting_url = st.text_input(
            "ミーティングURL（任意）",
            placeholder="例：https://zoom.us/j/123456789  /  https://meet.google.com/xxx",
            help="Zoom・Google Meet・Teams などのURLを入力すると確認メッセージに含まれます。",
            key="meeting_url_input",
        )

        if st.button("📨 確認メッセージを生成する", use_container_width=True):
            with st.spinner("確認メッセージを生成中..."):
                confirmation = message_generator.generate_confirmation_messages(
                    title=reg["title"],
                    slot_display=reg["slot"]["display"],
                    meeting_url=meeting_url.strip(),
                )
                st.session_state["confirmation_messages"] = confirmation

        # 生成結果のタブ表示
        if "confirmation_messages" in st.session_state:
            conf = st.session_state["confirmation_messages"]
            st.caption("✅ 確認メッセージを生成しました。タブを切り替えてコピーしてください。")

            ctab1, ctab2, ctab3, ctab4 = st.tabs(
                ["📱 LINE（短め）", "📱 LINE（丁寧）", "📧 メール（短め）", "📧 メール（丁寧）"]
            )
            with ctab1:
                st.text_area("", value=conf.get("line_short", ""), height=200, key="cta_line_short")
            with ctab2:
                st.text_area("", value=conf.get("line_polite", ""), height=240, key="cta_line_polite")
            with ctab3:
                st.text_area("", value=conf.get("email_short", ""), height=200, key="cta_email_short")
            with ctab4:
                st.text_area("", value=conf.get("email_polite", ""), height=280, key="cta_email_polite")
            st.markdown(
                '<div class="copy-hint">※ テキストエリアをクリックして Ctrl+A → Ctrl+C でコピーできます</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────
# エントリーポイント
# ─────────────────────────────────────────────
def main() -> None:
    """アプリのメインエントリーポイント"""

    # OAuthコールバックの処理（URLにcodeが含まれる場合）
    if handle_oauth_callback():
        st.rerun()
        return

    # 永続化ファイルからセッションを復元（ブラウザリフレッシュ後も認証を維持）
    if not auth.is_authenticated():
        auth.restore_session_from_file()

    # 認証状態に応じてページを切り替え
    if auth.is_authenticated():
        show_main_app()
    else:
        show_login_page()


if __name__ == "__main__":
    main()
