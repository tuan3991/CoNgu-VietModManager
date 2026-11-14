# -*- coding: utf-8 -*-
"""
Hồ Sơ Game Thủ - tổng hợp số liệu và huy hiệu nền tảng (tầng 2).

Chỉ đọc dữ liệu đã có sẵn (playtime.json, .congu_save, danh sách game,
bookmark, yêu cầu Việt hóa) nên hoạt động 100% offline và tức thời.
"""
import time
from datetime import datetime

BADGE_DEFS = [
    {"id": "first_session", "title": "Kẻ Khởi Đầu", "description": "Hoàn thành phiên chơi đầu tiên", "icon": "play", "tier": "bronze", "metric": "sessions", "target": 1},
    {"id": "sessions_10", "title": "Khách Quen", "description": "Mở game 10 lần", "icon": "gamepad-2", "tier": "silver", "metric": "sessions", "target": 10},
    {"id": "hours_10", "title": "Người Chơi Bền Bỉ", "description": "Tích lũy 10 giờ chơi", "icon": "clock", "tier": "bronze", "metric": "hours", "target": 10},
    {"id": "hours_50", "title": "Cày Cuốc Thứ Thiệt", "description": "Tích lũy 50 giờ chơi", "icon": "flame", "tier": "silver", "metric": "hours", "target": 50},
    {"id": "hours_100", "title": "Huyền Thoại Phòng Khách", "description": "Tích lũy 100 giờ chơi", "icon": "crown", "tier": "gold", "metric": "hours", "target": 100},
    {"id": "library_10", "title": "Nhà Sưu Tầm", "description": "Có 10 tựa game trong Thư viện", "icon": "library", "tier": "silver", "metric": "library", "target": 10},
    {"id": "translation_1", "title": "Mầm Mống Việt Hóa", "description": "Cài gói Việt hóa đầu tiên", "icon": "languages", "tier": "bronze", "metric": "translations", "target": 1},
    {"id": "translation_5", "title": "Thợ Săn Việt Hóa", "description": "Cài 5 gói Việt hóa", "icon": "medal", "tier": "silver", "metric": "translations", "target": 5},
    {"id": "translation_10", "title": "Người Bảo Tồn Cổ Ngữ", "description": "Cài 10 gói Việt hóa", "icon": "shield-check", "tier": "gold", "metric": "translations", "target": 10},
    {"id": "streak_3", "title": "Chuỗi Ngày Vàng", "description": "Chơi game 3 ngày liên tiếp", "icon": "calendar-check", "tier": "bronze", "metric": "streak", "target": 3},
    {"id": "streak_7", "title": "Tuần Lễ Bền Bỉ", "description": "Chơi game 7 ngày liên tiếp", "icon": "calendar-days", "tier": "silver", "metric": "streak", "target": 7},
    {"id": "achievements_10", "title": "Thợ Săn Thành Tựu", "description": "Mở khóa 10 thành tựu trong game", "icon": "trophy", "tier": "silver", "metric": "achievements", "target": 10},
    {"id": "achievements_50", "title": "Bộ Sưu Tập Cúp", "description": "Mở khóa 50 thành tựu trong game", "icon": "trophy", "tier": "gold", "metric": "achievements", "target": 50},
    {"id": "bookmark_5", "title": "Người Lập Kế Hoạch", "description": "Lưu 5 game vào danh sách Chưa tải", "icon": "bookmark", "tier": "bronze", "metric": "bookmarks", "target": 5},
    {"id": "request_1", "title": "Tiếng Nói Cộng Đồng", "description": "Gửi yêu cầu Việt hóa đầu tiên", "icon": "megaphone", "tier": "bronze", "metric": "requests", "target": 1},
]

METRIC_UNITS = {
    "hours": "giờ",
    "sessions": "phiên",
    "library": "game",
    "translations": "gói",
    "streak": "ngày",
    "achievements": "thành tựu",
    "bookmarks": "game",
    "requests": "yêu cầu",
}


def _format_seconds(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "0 phút"
    if seconds < 60:
        return "< 1 phút"
    if seconds < 3600:
        return f"{max(1, seconds // 60)} phút"
    if seconds < 36000:
        return f"{round(seconds / 3600, 1)} giờ"
    return f"{round(seconds / 3600)} giờ"


def _relative_time(ts, now: float = None) -> str:
    if not ts:
        return ""
    now = now or time.time()
    diff = max(0, int(now - ts))
    if diff < 60:
        return "vừa xong"
    if diff < 3600:
        return f"{diff // 60} phút trước"
    if diff < 86400:
        return f"{diff // 3600} giờ trước"
    if diff < 86400 * 7:
        return f"{diff // 86400} ngày trước"
    try:
        return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")
    except Exception:
        return ""


def _bookmark_like_key(text) -> str:
    return " ".join(str(text or "").lower().split())


def _parse_iso_ts(value):
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value)).timestamp())
    except Exception:
        return None


def _compute_progress(xp: int) -> tuple:
    """Cấp độ theo căn bậc hai: 100 XP = Cấp 2, 400 XP = Cấp 3, 900 XP = Cấp 4..."""
    level = int((max(0, xp) / 100) ** 0.5) + 1
    level_floor = ((level - 1) ** 2) * 100
    next_level = (level ** 2) * 100
    span = max(1, next_level - level_floor)
    percent = int(round((xp - level_floor) / span * 100))
    return level, level_floor, next_level, max(0, min(100, percent))


def _player_title(translations_installed: int) -> str:
    if translations_installed >= 10:
        return "Người Bảo Tồn Cổ Ngữ"
    if translations_installed >= 5:
        return "Thợ Săn Việt Hóa"
    if translations_installed >= 1:
        return "Người Giữ Lửa Việt Hóa"
    return "Tân Binh Cổ Ngữ"


def build_profile_overview(games, vault_info, manifest, playtime_snapshot,
                           achievements_progress=None, bookmarks=None,
                           loc_requests=None) -> dict:
    """
    Ghép dữ liệu thành payload cho trang Hồ Sơ.

    Trả về kèm 2 khóa nội bộ `_badge_unlock_map` / `_newly_unlocked` để tầng API
    ghi mốc mở huy hiệu vào .congu_save (không hiển thị ra frontend).
    """
    games = [g for g in (games or []) if isinstance(g, dict)]
    owned_games = [g for g in games if not g.get("is_bookmark_only")]
    games_by_id = {str(g.get("id")): g for g in owned_games}
    installed_games = [g for g in owned_games if g.get("status_code") == "INSTALLED"]
    bookmarks = bookmarks or []
    loc_requests = loc_requests or []
    achievements_progress = achievements_progress or {}
    snapshot = playtime_snapshot or {}
    vault_info = vault_info or {}
    manifest = manifest or {}
    manifest_games = manifest.get("games") if isinstance(manifest.get("games"), dict) else {}

    total_seconds = int(snapshot.get("total_seconds", 0) or 0)
    sessions = int(snapshot.get("sessions", 0) or 0)
    hours = total_seconds / 3600.0
    achievements_unlocked = int(vault_info.get("total_achievements_count", 0) or 0)

    metrics = {
        "hours": hours,
        "sessions": sessions,
        "library": len(owned_games),
        "translations": len(installed_games),
        "streak": int(snapshot.get("longest_streak", 0) or 0),
        "achievements": achievements_unlocked,
        "bookmarks": len(bookmarks),
        "requests": len(loc_requests),
    }

    xp = int(hours) + len(installed_games) * 25 + achievements_unlocked * 5 \
        + sessions * 2 + len(bookmarks) * 3 + len(loc_requests) * 10
    level, level_floor, next_level, level_percent = _compute_progress(xp)

    player_name = str(manifest.get("player_name") or vault_info.get("player_name") or "Game Thủ").strip() or "Game Thủ"

    stored_unlocks = manifest.get("profile_badges") if isinstance(manifest.get("profile_badges"), dict) else {}
    unlock_map = {}
    for badge_id, ts in stored_unlocks.items():
        try:
            unlock_map[str(badge_id)] = int(ts)
        except (TypeError, ValueError):
            continue

    now = int(time.time())
    newly_unlocked = []
    badges = []
    for spec in BADGE_DEFS:
        current = float(metrics.get(spec["metric"], 0) or 0)
        unlocked = spec["id"] in unlock_map
        if not unlocked and current >= spec["target"]:
            unlock_map[spec["id"]] = now
            newly_unlocked.append(spec["id"])
            unlocked = True

        display_current = round(current, 1) if spec["metric"] == "hours" else int(current)
        badges.append({
            "id": spec["id"],
            "title": spec["title"],
            "description": spec["description"],
            "icon": spec["icon"],
            "tier": spec["tier"],
            "unlocked": unlocked,
            "unlocked_ts": unlock_map.get(spec["id"], 0),
            "current": display_current,
            "target": spec["target"],
            "unit": METRIC_UNITS.get(spec["metric"], ""),
            "progress": max(0, min(100, int(round(current / spec["target"] * 100)))) if spec["target"] else 100,
        })

    badges.sort(key=lambda b: (not b["unlocked"], -int(b.get("unlocked_ts") or 0), -b["progress"]))

    # Top game theo giờ chơi + tiến độ thành tựu đã biết
    play_games = snapshot.get("games") if isinstance(snapshot.get("games"), dict) else {}
    top_games = []
    for gid, rec in play_games.items():
        sec = int((rec or {}).get("total_seconds", 0) or 0)
        if sec <= 0:
            continue
        game = games_by_id.get(str(gid)) or {}
        meta = manifest_games.get(gid) or {}
        appid = str(game.get("steam_appid") or "")
        progress = achievements_progress.get(str(gid)) or (achievements_progress.get(appid) if appid else None) or {}
        unlocked_list = meta.get("unlocked_achievements") or []
        a_unlocked = max(len(unlocked_list), int(progress.get("unlocked_count", 0) or 0))
        top_games.append({
            "game_id": gid,
            "title": game.get("vietnamese_title") or game.get("title") or meta.get("title") or str(gid),
            "cover_url": game.get("local_cover") or game.get("avatar_url") or "",
            "playtime_seconds": sec,
            "formatted_playtime": _format_seconds(sec),
            "achievements_unlocked": a_unlocked,
            "achievements_total": int(progress.get("total", 0) or 0),
            "last_played_ts": int(rec.get("last_played_ts") or 0),
        })
    top_games.sort(key=lambda x: -x["playtime_seconds"])
    top_games = top_games[:5]

    # Hoạt động gần đây: chơi game + thêm vào Thư viện + gửi yêu cầu Việt hóa
    activities = []
    for entry in _iter_play_rows(play_games, games_by_id, manifest_games):
        ts = int(entry.get("last_played_ts") or 0)
        if ts > 0:
            activities.append({
                "type": "play",
                "title": entry["title"],
                "game_id": entry["game_id"],
                "ts": ts,
                "detail": f"Đã chơi {entry['formatted_playtime']}",
            })
    for bm in bookmarks:
        ts = int(bm.get("added_ts") or 0)
        if ts > 0:
            activities.append({
                "type": "bookmark",
                "title": bm.get("title") or "Game đã lưu",
                "ts": ts,
                "detail": "Đã thêm vào Thư viện",
            })
    for req in loc_requests[:5]:
        ts = _parse_iso_ts(req.get("updated_at") or req.get("requested_at"))
        if ts:
            activities.append({
                "type": "request",
                "title": req.get("title") or req.get("game_id") or "Game đã yêu cầu",
                "ts": ts,
                "detail": f"Yêu cầu Việt hóa • {req.get('status_label') or 'Đang chờ duyệt'}",
            })
    # Gộp trùng theo loại + tên (một game có thể có nhiều id qua thời gian)
    deduped = {}
    for item in activities:
        key = (item["type"], _bookmark_like_key(item["title"]))
        if key not in deduped or item["ts"] > deduped[key]["ts"]:
            deduped[key] = item
    activities = sorted(deduped.values(), key=lambda x: -x["ts"])[:6]
    current_ts = int(time.time())
    for item in activities:
        item["time_label"] = _relative_time(item["ts"], current_ts)

    last_played_label = activities[0]["time_label"] if activities else ""

    return {
        "player": {
            "name": player_name,
            "initial": player_name[:1].upper(),
            "title": _player_title(len(installed_games)),
            "level": level,
            "xp": xp,
            "level_floor": level_floor,
            "next_level_xp": next_level,
            "level_percent": level_percent,
            "is_online": False,
            "last_active_label": last_played_label,
            "avatar_url": str(manifest.get("avatar_url") or "").strip(),
            "cover_url": str(manifest.get("cover_url") or "").strip(),
            "bio": str(manifest.get("bio") or "").strip(),
        },
        "stats": {
            "games_owned": len(owned_games),
            "games_installed": len(installed_games),
            "translations_installed": len(installed_games),
            "total_seconds": total_seconds,
            "formatted_playtime": _format_seconds(total_seconds),
            "hours": round(hours, 2),
            "sessions": sessions,
            "achievements_unlocked": achievements_unlocked,
            "bookmarks": len(bookmarks),
            "requests": len(loc_requests),
            "current_streak": int(snapshot.get("current_streak", 0) or 0),
            "longest_streak": int(snapshot.get("longest_streak", 0) or 0),
            "active_days": int(snapshot.get("active_days", 0) or 0),
        },
        "badge_summary": {
            "unlocked": sum(1 for b in badges if b["unlocked"]),
            "total": len(badges),
        },
        "badges": badges,
        "top_games": top_games,
        "recent_activity": activities,
        "vault": {
            "total_games": int(vault_info.get("total_games", 0) or 0),
            "total_playtime": vault_info.get("total_playtime_str", "0 phút"),
            "achievements": achievements_unlocked,
            "formatted_updated_at": vault_info.get("formatted_updated_at", "Chưa có"),
            "updated_at": int(vault_info.get("updated_at", 0) or 0),
        },
        "generated_at": current_ts,
        "_badge_unlock_map": unlock_map,
        "_newly_unlocked": newly_unlocked,
    }


def _iter_play_rows(play_games, games_by_id, manifest_games):
    """Sinh các dòng chơi game còn lại (ngoài top 5) để dựng hoạt động gần đây."""
    for gid, rec in play_games.items():
        if int((rec or {}).get("total_seconds", 0) or 0) <= 0:
            continue
        game = games_by_id.get(str(gid)) or {}
        meta = manifest_games.get(gid) or {}
        yield {
            "game_id": gid,
            "title": game.get("vietnamese_title") or game.get("title") or meta.get("title") or str(gid),
            "formatted_playtime": _format_seconds(int(rec.get("total_seconds", 0) or 0)),
            "last_played_ts": int(rec.get("last_played_ts") or 0),
        }
