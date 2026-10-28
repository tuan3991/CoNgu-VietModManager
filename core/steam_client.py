# -*- coding: utf-8 -*-
"""
CỔ NGỮ (VietModHub Pro) - Steam & SteamGridDB Client Module
------------------------------------------------------------
Cung cấp các hàm giao tiếp mạng trực tiếp với máy chủ Steam và SteamGridDB:
- steam_direct_request: Vượt chặn DPI (phân mảnh TLS ClientHello) tại Việt Nam.
- get_steam_official_Vertical_posters: Lấy link poster 600x900 nét căng chính thức của Steam.
- fetch_steamgriddb_posters: Lấy poster từ SteamGridDB theo Steam AppID.
- search_steamgriddb_by_name: Tìm poster từ SteamGridDB theo tên game.
- search_steam_online: Tìm kiếm game Steam trực tuyến (vượt chặn DPI).
"""

import os
import sys
import time
import json
import re
import socket
import ssl
import urllib.request
import urllib.parse

STEAMGRIDDB_API_KEY = "426d6282a3c5c387dbee3e4ee3a37628"


def steam_direct_request(url: str, timeout: float = 4.0) -> bytes:
    """
    Gửi HTTP GET trực tiếp tới các máy chủ Steam (store.steampowered.com, steamcommunity.com, steamstatic.com)
    sử dụng cơ chế phân mảnh ClientHello (DPI bypass) nhằm vượt qua việc các nhà mạng chặn SNI tại Việt Nam.
    """
    p = urllib.parse.urlparse(url)
    hostname = p.netloc or "store.steampowered.com"
    path = p.path or "/"
    if p.query:
        path += "?" + p.query

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        incoming = ssl.MemoryBIO()
        outgoing = ssl.MemoryBIO()
        sslobj = ctx.wrap_bio(incoming, outgoing, server_hostname=hostname)
        try:
            sslobj.do_handshake()
        except ssl.SSLWantReadError:
            pass

        client_hello = outgoing.read()
        ip = socket.gethostbyname(hostname)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, 443))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # Gửi 5 bytes đầu tiên (TLS record header), nghỉ 20ms rồi gửi phần còn lại để bypass DPI
        sock.sendall(client_hello[:5])
        time.sleep(0.02)
        sock.sendall(client_hello[5:])

        while True:
            try:
                sslobj.do_handshake()
                break
            except ssl.SSLWantReadError:
                data = sock.recv(4096)
                if not data:
                    break
                incoming.write(data)
            out = outgoing.read()
            if out:
                sock.sendall(out)

        http_req = (
            f"GET {path} HTTP/1.0\r\n"
            f"Host: {hostname}\r\n"
            f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
            f"Accept: application/json, image/*, text/plain, */*\r\n"
            f"Connection: close\r\n\r\n"
        )
        sslobj.write(http_req.encode("utf-8"))
        out = outgoing.read()
        if out:
            sock.sendall(out)

        resp_body = b""
        while True:
            try:
                data = sslobj.read(8192)
                if not data:
                    break
                resp_body += data
            except ssl.SSLWantReadError:
                raw = sock.recv(8192)
                if not raw:
                    break
                incoming.write(raw)
        sock.close()
        parts = resp_body.split(b"\r\n\r\n", 1)
        if len(parts) > 1:
            first_line = parts[0].split(b"\r\n", 1)[0].decode("latin-1", errors="ignore")
            if "200 OK" in first_line:
                return parts[1]
        return b""
    except Exception:
        # Fallback về urllib thông thường nếu mạng không bị chặn DPI
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception:
            pass
        return b""


def get_steam_official_Vertical_posters(appid: str) -> list[str]:
    """
    Gọi API IStoreBrowseService/GetItems/v1 của Steam để lấy chính xác đường dẫn
    library_600x900_2x.jpg và library_600x900.jpg kèm mã {HASH} chuẩn cho mọi game mới & cũ.
    """
    if not appid or not str(appid).isdigit():
        return []
    urls = []
    try:
        input_json = json.dumps({
            "ids": [{"appid": int(appid)}],
            "context": {"language": "english", "country_code": "US"},
            "data_request": {"include_assets": True}
        }, separators=(",", ":"))
        api_url = f"https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json={urllib.parse.quote(input_json)}"
        raw = steam_direct_request(api_url, timeout=4.0)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            items = data.get("response", {}).get("store_items", [])
            if items:
                assets = items[0].get("assets", {})
                fmt = assets.get("asset_url_format", f"steam/apps/{appid}/${{FILENAME}}")
                for key in ("library_capsule_2x", "library_capsule"):
                    fname = assets.get(key)
                    if fname:
                        rel_path = fmt.replace("${FILENAME}", fname).lstrip("/")
                        urls.append(f"https://shared.fastly.steamstatic.com/store_item_assets/{rel_path}")
                        urls.append(f"https://shared.akamai.steamstatic.com/store_item_assets/{rel_path}")
    except Exception as e:
        print(f"[SteamBrowseAPI] Error fetching hashed capsule for {appid}: {e}")

    # Fallback dự phòng: Thử tìm mã hash 40 hex từ appdetails nếu API trên không trả về assets
    if not urls:
        try:
            details_url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=en"
            raw_det = steam_direct_request(details_url, timeout=3.5)
            if raw_det:
                det = json.loads(raw_det.decode("utf-8", "ignore"))
                h_img = det.get(str(appid), {}).get("data", {}).get("header_image", "")
                m = re.search(r"/([0-9a-f]{40})/", h_img)
                if m:
                    h_code = m.group(1)
                    urls.append(f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg")
                    urls.append(f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg")
                    urls.append(f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900_2x.jpg")
                    urls.append(f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{h_code}/library_600x900.jpg")
        except Exception:
            pass

    return urls

get_steam_official_vertical_posters = get_steam_official_Vertical_posters


def fetch_steamgriddb_posters(steam_appid: str, limit: int = 4) -> list[str]:
    """Lấy danh sách poster dọc chuẩn 600x900 từ kho SteamGridDB theo Steam AppID."""
    if not STEAMGRIDDB_API_KEY or not str(steam_appid).isdigit():
        return []
    url = f"https://www.steamgriddb.com/api/v2/grids/steam/{steam_appid}?dimensions=600x900&types=static"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {STEAMGRIDDB_API_KEY}",
        "User-Agent": "CoNgu-VietModManager/2.0"
    })
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=3.5, context=ctx) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
                return [item["url"] for item in data.get("data", [])[:limit] if item.get("url")]
    except Exception as e:
        print(f"[SteamGridDB] Error: {e}")
    return []


def search_steamgriddb_by_name(query: str, max_items: int = 6) -> list[dict]:
    """Tìm kiếm trực tiếp poster 600x900 trên SteamGridDB theo tên game."""
    results = []
    if not STEAMGRIDDB_API_KEY or not query or len(query.strip()) < 2:
        return results
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        encoded_q = urllib.parse.quote(query.strip())
        url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{encoded_q}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {STEAMGRIDDB_API_KEY}",
            "User-Agent": "CoNgu-VietModManager/2.0"
        })
        with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
            games = data.get("data", [])

        for g in games[:3]:
            gid = g.get("id")
            gname = g.get("name")
            if not gid or not gname:
                continue
            g_url = f"https://www.steamgriddb.com/api/v2/grids/game/{gid}?dimensions=600x900&types=static"
            g_req = urllib.request.Request(g_url, headers={
                "Authorization": f"Bearer {STEAMGRIDDB_API_KEY}",
                "User-Agent": "CoNgu-VietModManager/2.0"
            })
            try:
                with urllib.request.urlopen(g_req, timeout=3.0, context=ctx) as g_resp:
                    grids_data = json.loads(g_resp.read().decode("utf-8", "ignore"))
                    grids = grids_data.get("data", [])
                    for idx, it in enumerate(grids[:2]):
                        p_url = it.get("url")
                        grid_id = it.get("id")
                        if p_url:
                            results.append({
                                "id": f"sgdb_{gid}_{grid_id}",
                                "steam_appid": "",
                                "name": gname,
                                "title": gname,
                                "subtitle": f"SteamGridDB #{grid_id}",
                                "source": "steamgriddb",
                                "genre": "SteamGridDB",
                                "avatar_url": p_url,
                                "header_url": p_url,
                                "capsule": p_url
                            })
                            if len(results) >= max_items:
                                return results
            except Exception:
                pass
    except Exception as e:
        print(f"[SteamGridDB Search] Error: {e}")
    return results


def search_steam_online(query: str, limit: int = 15) -> list[dict]:
    """Tìm kiếm game trực tuyến trên Steam Store và Steam Community (vượt DPI)."""
    clean_q = re.sub(r"\s+", " ", (query or "")).strip()
    if not clean_q or len(clean_q) < 2:
        return []

    encoded_q = urllib.parse.quote(clean_q)
    raw_items = []
    seen = set()

    # 1. Store Search API
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={encoded_q}&l=english&cc=US"
        raw = steam_direct_request(url, timeout=3.5)
        if raw:
            data = json.loads(raw.decode("utf-8", "ignore"))
            for it in data.get("items", [])[:limit]:
                appid = str(it.get("id", ""))
                name = it.get("name", "")
                if not appid or not name or appid in seen:
                    continue
                seen.add(appid)
                raw_items.append({
                    "appid": appid,
                    "name": name,
                    "tiny_image": it.get("tiny_image", "")
                })
    except Exception as e:
        print(f"[SteamOnline] Store search failed: {e}")

    # 2. Community SearchApps API (steamcommunity.com) nếu kết quả còn ít
    if len(raw_items) < limit:
        try:
            url = f"https://steamcommunity.com/actions/SearchApps/{encoded_q}"
            raw = steam_direct_request(url, timeout=3.0)
            if raw:
                data = json.loads(raw.decode("utf-8", "ignore"))
                if isinstance(data, list):
                    for it in data[:limit]:
                        appid = str(it.get("appid", ""))
                        name = it.get("name", "")
                        if not appid or not name or appid in seen:
                            continue
                        seen.add(appid)
                        raw_items.append({
                            "appid": appid,
                            "name": name,
                            "tiny_image": f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/capsule_sm_120.jpg"
                        })
        except Exception as e:
            print(f"[SteamOnline] Community search failed: {e}")

    return raw_items
