"""
Google Calendar API を使ってカレンダー操作を行うモジュール

主な機能:
- 指定期間のイベントを取得
- 空き時間スロットを検索
- 新しい予定をカレンダーに登録
- ユーザー情報の取得
"""

from datetime import date, datetime, timedelta, timezone
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# 日本標準時（UTC+9）
JST = timezone(timedelta(hours=9))

# プリセット時間帯（UIのクイック選択用）
PRESET_TIME_RANGES = {
    "午前（9〜12時）": (9, 12),
    "午後（13〜18時）": (13, 18),
    "夜（18〜22時）": (18, 22),
    "終日（9〜22時）": (9, 22),
}

# 日本語の曜日
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _parse_google_datetime(dt_str: str) -> datetime:
    """
    Google Calendar APIの日時文字列をJST（タイムゾーンなし）のdatetimeに変換する

    Google APIはUTC（Zサフィックス）またはオフセット付き形式で返す
    例: "2024-06-21T10:00:00+09:00", "2024-06-21T01:00:00Z"
    """
    if dt_str.endswith("Z"):
        dt = datetime.fromisoformat(dt_str[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(dt_str)
    return dt.astimezone(JST).replace(tzinfo=None)


def _build_service(credentials: Credentials):
    """Google Calendar APIサービスを生成する"""
    return build("calendar", "v3", credentials=credentials)


def get_user_info(credentials: Credentials) -> dict:
    """Googleアカウントのユーザー情報（名前・メールアドレス）を取得する"""
    service = build("oauth2", "v2", credentials=credentials)
    return service.userinfo().get().execute()


def _get_events(credentials: Credentials, start_date: date, end_date: date) -> list:
    """
    指定した期間のカレンダーイベントをすべて取得する

    Google APIはUTCで時刻を受け取るため、日本時間の0時をUTCに変換して渡す
    """
    service = _build_service(credentials)

    # 開始日の0:00 JSTをUTCで表現
    start_jst = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=JST)
    end_jst = datetime.combine(end_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=JST)

    time_min = start_jst.astimezone(timezone.utc).isoformat()
    time_max = end_jst.astimezone(timezone.utc).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,   # 繰り返し予定も個別に展開
            orderBy="startTime",
        )
        .execute()
    )
    return events_result.get("items", [])


def _extract_busy_times(events: list) -> list[tuple[datetime, datetime]]:
    """
    イベントリストからブロック済み時間帯（開始・終了のタプル）を抽出する

    キャンセルされたイベントや削除済みイベントは除外する
    """
    busy_times = []

    for event in events:
        # キャンセル・削除済みイベントはスキップ
        if event.get("status") == "cancelled":
            continue

        start_info = event.get("start", {})
        end_info = event.get("end", {})

        if "dateTime" in start_info:
            # 時刻指定のイベント
            event_start = _parse_google_datetime(start_info["dateTime"])
            event_end = _parse_google_datetime(end_info["dateTime"])
            busy_times.append((event_start, event_end))

        elif "date" in start_info:
            # 終日イベント → その日全体をブロック
            event_date = date.fromisoformat(start_info["date"])
            event_start = datetime.combine(event_date, datetime.min.time())
            event_end = event_start + timedelta(days=1)
            busy_times.append((event_start, event_end))

    return busy_times


def _format_slot(slot_start: datetime, slot_end: datetime) -> str:
    """スロットを表示用の文字列に変換する（例: 6/21（土）20:00〜21:00）"""
    weekday = WEEKDAYS_JP[slot_start.weekday()]
    return (
        f"{slot_start.month}/{slot_start.day}（{weekday}）"
        f"{slot_start.strftime('%H:%M')}〜{slot_end.strftime('%H:%M')}"
    )


def get_free_slots(
    credentials: Credentials,
    start_date: date,
    end_date: date,
    time_ranges: list[tuple[int, int]],
    duration_minutes: int,
    max_slots: int = 5,
) -> list[dict]:
    """
    指定した期間・時間帯リスト・打ち合わせ時間に基づいて空きスロットを最大 max_slots 件返す

    Args:
        credentials: Google認証情報
        start_date: 検索開始日
        end_date: 検索終了日
        time_ranges: 希望時間帯のリスト。例: [(9, 12), (18, 22)]
        duration_minutes: 打ち合わせ時間（分）
        max_slots: 返すスロットの最大数

    Returns:
        空きスロットのリスト。各要素は {"start": datetime, "end": datetime, "display": str}
    """
    # カレンダーイベントを取得してブロック済み時間を抽出
    events = _get_events(credentials, start_date, end_date)
    busy_times = _extract_busy_times(events)

    slot_duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=30)  # 30分刻みで候補を検索

    # 開始時刻順に並べ替え（日の中で時間帯を順番に処理するため）
    sorted_ranges = sorted(
        [(s, e) for s, e in time_ranges if s < e],  # 開始 < 終了 のみ有効
        key=lambda x: x[0],
    )

    if not sorted_ranges:
        return []

    free_slots = []
    current_date = start_date

    while current_date <= end_date and len(free_slots) < max_slots:
        # その日の各時間帯を順番に検索
        for start_hour, end_hour in sorted_ranges:
            if len(free_slots) >= max_slots:
                break

            day_start = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=start_hour)
            day_end = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=end_hour)
            check_time = day_start

            while check_time + slot_duration <= day_end and len(free_slots) < max_slots:
                slot_start = check_time
                slot_end = check_time + slot_duration

                # このスロットが既存予定と重複するか確認
                is_free = True
                for busy_start, busy_end in busy_times:
                    if not (slot_end <= busy_start or slot_start >= busy_end):
                        is_free = False
                        break

                if is_free:
                    free_slots.append({
                        "start": slot_start,
                        "end": slot_end,
                        "display": _format_slot(slot_start, slot_end),
                    })
                    check_time += slot_duration  # 見つかったら打ち合わせ時間分進める
                else:
                    check_time += step  # 30分刻みで次を探す

        current_date += timedelta(days=1)

    return free_slots


def create_calendar_event(
    credentials: Credentials,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    description: str = "",
) -> dict:
    """
    Googleカレンダーに新しい予定を作成する

    Args:
        credentials: Google認証情報
        title: 予定のタイトル
        start_dt: 開始日時（JST、タイムゾーンなし）
        end_dt: 終了日時（JST、タイムゾーンなし）
        description: 予定の説明（省略可）

    Returns:
        作成された予定の情報（Google APIのレスポンス）
    """
    service = _build_service(credentials)

    event_body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "Asia/Tokyo",
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "Asia/Tokyo",
        },
    }

    created_event = service.events().insert(calendarId="primary", body=event_body).execute()
    return created_event
