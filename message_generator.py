"""
送信用文章を生成するモジュール

2つのモードに対応しています：
  - 「自分から候補日を送る」モード: 候補日をもとに文章を作成
  - 「相手の文章に返信する」モード: 受信メッセージ＋候補日をもとに返信文を作成

OpenAI APIが設定されている場合はAIで生成し、
設定されていない場合はテンプレートで生成します。
"""

import os
import json
import re
import streamlit as st


def _format_candidates(slots: list) -> str:
    """候補日スロットを箇条書きのテキストに変換する"""
    return "\n".join(f"・{slot['display']}" for slot in slots)


def _call_openai(prompt: str) -> dict:
    """
    OpenAI APIを呼び出してJSONを返す共通関数

    response_format=json_object でJSONのみを返させる。
    """
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEYが設定されていません")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    # JSON以外のテキストが混入した場合に備えて抽出
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        content = match.group()

    return json.loads(content)


# ─────────────────────────────────────────────
# モード①：自分から候補日を送る
# ─────────────────────────────────────────────

def _generate_with_openai(slots: list) -> dict:
    """
    OpenAI APIを使って「自分から候補日を送る」用の文章を4種類生成する
    """
    candidates_text = _format_candidates(slots)

    prompt = f"""あなたは丁寧なビジネスコミュニケーションの専門家です。
日程調整のメッセージを4種類作成してください。

【候補日】
{candidates_text}

【作成するメッセージのルール】
- 候補日が分かりやすく並んでいる
- 都合確認の一文がある
- 長すぎない・自然な日本語
- LINEはカジュアルで読みやすく、メールはフォーマルに
- メール（丁寧）には「件名：」も含める

【作成する4種類】
1. line_short: LINE向け・短め・カジュアル（3〜5行）
2. line_polite: LINE向け・丁寧版（5〜8行）
3. email_short: メール向け・短め本文のみ（4〜6行）
4. email_polite: メール向け・丁寧版（「件名：」＋本文、8〜12行）

必ず以下のJSON形式のみで返してください（説明文は不要）:
{{
  "line_short": "...",
  "line_polite": "...",
  "email_short": "...",
  "email_polite": "..."
}}"""

    return _call_openai(prompt)


def _generate_with_template(slots: list) -> dict:
    """
    テンプレートベースで「自分から候補日を送る」用の文章を生成する

    OpenAI APIキーがない場合や、APIエラー時のフォールバック
    """
    candidates_text = _format_candidates(slots)

    return {
        "line_short": (
            "お疲れ様です！\n"
            "以下の日程でしたら調整できます。\n\n"
            f"{candidates_text}\n\n"
            "ご都合はいかがでしょうか？"
        ),
        "line_polite": (
            "いつもお世話になっております。\n"
            "打ち合わせの日程についてご連絡いたします。\n"
            "以下の日程でしたらお時間をいただけます。\n\n"
            f"{candidates_text}\n\n"
            "ご確認いただけますと幸いです。\n"
            "ご都合のよい日程をお知らせください。\n"
            "よろしくお願いいたします。"
        ),
        "email_short": (
            "お疲れ様です。\n"
            "日程候補をご連絡いたします。\n\n"
            f"{candidates_text}\n\n"
            "いずれかご都合のよい日程をご返信ください。\n"
            "よろしくお願いいたします。"
        ),
        "email_polite": (
            "件名：打ち合わせ日程のご相談\n\n"
            "お世話になっております。\n\n"
            "打ち合わせの日程についてご連絡いたします。\n"
            "以下の日程でしたら、お時間をいただくことが可能でございます。\n\n"
            f"{candidates_text}\n\n"
            "ご都合のよろしい日程をご選択いただき、\n"
            "ご返信いただけますと幸いです。\n\n"
            "お手数をおかけいたしますが、\n"
            "どうぞよろしくお願いいたします。"
        ),
    }


def generate_messages(slots: list) -> dict:
    """
    「自分から候補日を送る」モードの文章を4種類生成する

    OpenAI APIキーがあればAI生成、なければテンプレートを使用。

    Returns:
        {"line_short": str, "line_polite": str, "email_short": str, "email_polite": str}
    """
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _generate_with_openai(slots)
        except Exception as e:
            st.warning(f"AIによる文章生成に失敗しました。テンプレートを使用します。\n詳細: {e}")

    return _generate_with_template(slots)


# ─────────────────────────────────────────────
# モード②：相手の文章に返信する
# ─────────────────────────────────────────────

def _generate_reply_with_openai(slots: list, received_message: str) -> dict:
    """
    OpenAI APIを使って「相手の文章に返信する」用の文章を4種類生成する

    受信メッセージの内容に自然につながる返信文を作成する。
    """
    candidates_text = _format_candidates(slots)

    prompt = f"""あなたは丁寧なビジネスコミュニケーションの専門家です。
以下の「相手から届いたメッセージ」に対する返信文章を4種類作成してください。

【相手から届いたメッセージ】
{received_message}

【返信に含める候補日】
{candidates_text}

【返信文章のルール】
- 相手のメッセージ内容に自然につながる書き出し（「ご連絡ありがとうございます」など）
- 候補日を分かりやすく箇条書きで記載する
- 都合確認の一文を入れる（「ご都合いかがでしょうか？」など）
- 丁寧な締め文を入れる
- LINEはカジュアルで親しみやすく、メールはフォーマルに
- メール（丁寧）には「件名：」も含める
- 長すぎず、ビジネスで使える自然な日本語

【作成する4種類】
1. line_short: LINE向け・短め・カジュアル（4〜6行）
2. line_polite: LINE向け・丁寧版（6〜9行）
3. email_short: メール向け・短め本文のみ（5〜7行）
4. email_polite: メール向け・丁寧版（「件名：」＋本文、9〜13行）

必ず以下のJSON形式のみで返してください（説明文は不要）:
{{
  "line_short": "...",
  "line_polite": "...",
  "email_short": "...",
  "email_polite": "..."
}}"""

    return _call_openai(prompt)


def _generate_reply_with_template(slots: list, received_message: str) -> dict:
    """
    テンプレートベースで「相手の文章に返信する」用の文章を生成する

    OpenAI APIキーがない場合や、APIエラー時のフォールバック
    """
    candidates_text = _format_candidates(slots)

    return {
        "line_short": (
            "ご連絡ありがとうございます！\n"
            "以下の日程でしたら調整できます。\n\n"
            f"{candidates_text}\n\n"
            "いかがでしょうか？"
        ),
        "line_polite": (
            "ご連絡いただきありがとうございます。\n"
            "日程について確認いたしました。\n"
            "以下の日程でしたらお時間をいただけます。\n\n"
            f"{candidates_text}\n\n"
            "ご都合のよい日程をお知らせください。\n"
            "よろしくお願いいたします。"
        ),
        "email_short": (
            "ご連絡いただきありがとうございます。\n"
            "以下の日程でしたら調整可能です。\n\n"
            f"{candidates_text}\n\n"
            "ご確認のほどよろしくお願いいたします。"
        ),
        "email_polite": (
            "件名：打ち合わせ日程のご返答\n\n"
            "お世話になっております。\n"
            "ご連絡いただきありがとうございます。\n\n"
            "ご依頼の件につきまして、以下の日程でしたら\n"
            "お時間をいただくことが可能でございます。\n\n"
            f"{candidates_text}\n\n"
            "ご都合のよろしい日程をご選択いただき、\n"
            "ご返信いただけますと幸いです。\n\n"
            "何卒よろしくお願いいたします。"
        ),
    }


# ─────────────────────────────────────────────
# 日程確定後の確認メッセージ
# ─────────────────────────────────────────────

def _generate_confirmation_with_openai(title: str, slot_display: str, meeting_url: str) -> dict:
    """OpenAI APIを使って確認メッセージを4種類生成する"""
    url_line = f"URL：{meeting_url}" if meeting_url.strip() else "（URLは別途ご連絡します）"

    prompt = f"""あなたは丁寧なビジネスコミュニケーションの専門家です。
日程が確定した旨を伝える確認メッセージを4種類作成してください。

【確定した予定の内容】
件名/タイトル：{title}
日時：{slot_display}
{url_line}

【メッセージのルール】
- 日程が確定したことを明確に伝える
- 日時を正確・見やすく記載する
- URLがある場合は必ず含める
- 相手への感謝や楽しみにしている旨を含める
- LINEはカジュアルで親しみやすく（絵文字可）
- メールはフォーマルに
- メール（丁寧）には「件名：」も含める
- 長すぎず、読みやすい文章にする

【作成する4種類】
1. line_short: LINE向け・短め（4〜6行）
2. line_polite: LINE向け・丁寧版（6〜9行）
3. email_short: メール向け・短め本文のみ（5〜7行）
4. email_polite: メール向け・丁寧版（「件名：」＋本文、9〜13行）

必ず以下のJSON形式のみで返してください（説明文は不要）:
{{
  "line_short": "...",
  "line_polite": "...",
  "email_short": "...",
  "email_polite": "..."
}}"""

    return _call_openai(prompt)


def _generate_confirmation_with_template(title: str, slot_display: str, meeting_url: str) -> dict:
    """テンプレートベースで確認メッセージを生成する（OpenAI不使用版）"""
    url_block = f"\nURL：{meeting_url}" if meeting_url.strip() else ""

    return {
        "line_short": (
            f"日程が確定しました！\n\n"
            f"📅 {slot_display}\n"
            f"件名：{title}"
            f"{url_block}\n\n"
            "よろしくお願いします！"
        ),
        "line_polite": (
            "日程のご確認ありがとうございます。\n"
            "以下の通り日程が確定しましたのでご連絡いたします。\n\n"
            f"📅 日時：{slot_display}\n"
            f"件名：{title}"
            f"{url_block}\n\n"
            "当日はよろしくお願いいたします。"
        ),
        "email_short": (
            f"件名：【日程確定】{title}\n\n"
            "お世話になっております。\n"
            "日程が確定しましたのでご連絡いたします。\n\n"
            f"日時：{slot_display}\n"
            f"件名：{title}"
            f"{url_block}\n\n"
            "よろしくお願いいたします。"
        ),
        "email_polite": (
            f"件名：【日程確定のご連絡】{title}\n\n"
            "お世話になっております。\n"
            "このたびはご調整いただきありがとうございます。\n\n"
            "以下の通り日程が確定しましたのでご連絡いたします。\n\n"
            f"■ 日時：{slot_display}\n"
            f"■ 件名：{title}"
            f"\n■ {url_block.strip()}" if url_block else "" +
            "\n\nご不明な点がございましたらお気軽にご連絡ください。\n"
            "当日はどうぞよろしくお願いいたします。"
        ),
    }


def generate_confirmation_messages(title: str, slot_display: str, meeting_url: str = "") -> dict:
    """
    カレンダー登録後の確認メッセージを4種類生成する

    確定した日時・タイトル・URLをもとに、相手へ送る「日程確定のご連絡」文章を作成する。

    Args:
        title: 予定のタイトル（例: 〇〇社との商談）
        slot_display: 日時の表示文字列（例: 6/22（月）18:00〜19:00）
        meeting_url: ZoomなどのURL（省略可）

    Returns:
        {"line_short": str, "line_polite": str, "email_short": str, "email_polite": str}
    """
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _generate_confirmation_with_openai(title, slot_display, meeting_url)
        except Exception as e:
            st.warning(f"AIによる文章生成に失敗しました。テンプレートを使用します。\n詳細: {e}")

    return _generate_confirmation_with_template(title, slot_display, meeting_url)


def generate_reply_messages(slots: list, received_message: str) -> dict:
    """
    「相手の文章に返信する」モードの文章を4種類生成する

    受信メッセージと候補日をもとに、自然な返信文を作成する。
    OpenAI APIキーがあればAI生成、なければテンプレートを使用。

    Args:
        slots: 空き時間スロットのリスト
        received_message: 相手から届いたメッセージのテキスト

    Returns:
        {"line_short": str, "line_polite": str, "email_short": str, "email_polite": str}
    """
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _generate_reply_with_openai(slots, received_message)
        except Exception as e:
            st.warning(f"AIによる文章生成に失敗しました。テンプレートを使用します。\n詳細: {e}")

    return _generate_reply_with_template(slots, received_message)
