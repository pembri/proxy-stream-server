"""
api/proxy.py
Proxy + URL-hider untuk channel IPTV.

Alur:
1. GET /stream-hls/channel/{group}/{slug}/master.m3u8
   -> generate token (berlaku 24 jam) lalu 302 redirect ke:
   /stream/live/{group}/{slug}/master.m3u8?exp=...&token=...

2. GET /stream/live/{group}/{slug}/{apapun}?exp=...&token=...[&u=...]
   -> validasi token & masa berlaku, lalu fetch konten asli dari origin
      (base_url + path di channel.json, atau dari param "u" untuk
      sub-resource / variant playlist / segmen .ts hasil rewrite),
      lalu:
        - kalau isinya .m3u8: rewrite semua URI di dalamnya supaya
          tetap lewat proxy ini (origin asli tidak pernah terlihat
          di response maupun di address bar).
        - kalau bukan .m3u8 (misal .ts): diteruskan apa adanya
          (streaming passthrough).
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

TOKEN_TTL_SECONDS = 24 * 60 * 60  # 24 jam
SECRET_KEY = os.environ.get("PROXY_SECRET_KEY", "ganti-secret-key-ini-di-env-vercel")

CHANNELS_PATH = os.path.join(os.path.dirname(__file__), "..", "channel.json")
with open(CHANNELS_PATH, "r", encoding="utf-8") as f:
    CHANNELS = json.load(f)


def make_token(group, slug, exp, u=""):
    msg = f"{group}:{slug}:{exp}:{u}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_token(group, slug, exp, token, u=""):
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if time.time() > exp_int:
        return False
    expected = make_token(group, slug, exp_int, u)
    return hmac.compare_digest(expected, token or "")


def encode_u(url):
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("utf-8").rstrip("=")


def decode_u(u):
    padding = "=" * (-len(u) % 4)
    return base64.urlsafe_b64decode((u + padding).encode("utf-8")).decode("utf-8")


def get_channel_origin(group, slug):
    grp = CHANNELS.get(group)
    if not grp:
        return None, None
    rel = grp.get("channels", {}).get(slug)
    if not rel:
        return None, None
    return grp["base_url"] + rel, grp.get("user_agent")


def get_group_ua(group):
    grp = CHANNELS.get(group)
    return grp.get("user_agent") if grp else None


def fetch_origin(url, user_agent=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read(), resp.headers.get("Content-Type", "")


def rewrite_playlist(body_text, origin_url, group, slug, exp, token, user_agent):
    base = origin_url.rsplit("/", 1)[0] + "/"
    out_lines = []
    for line in body_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        abs_url = urllib.parse.urljoin(base, stripped)
        u = encode_u(abs_url)
        new_exp = exp
        new_token = make_token(group, slug, new_exp, u)
        proxied = (
            f"/stream/live/{group}/{slug}/{abs_url.rsplit('/', 1)[-1]}"
            f"?exp={new_exp}&token={new_token}&u={u}"
        )
        out_lines.append(proxied)
    return "\n".join(out_lines)


class handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="text/plain; charset=utf-8", extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        parts = [p for p in path.split("/") if p]

        # --- Route A: entry point (masih pakai path lama, belum ada token) ---
        # /stream-hls/channel/{group}/{slug}/master.m3u8
        if len(parts) >= 5 and parts[0] == "stream-hls" and parts[1] == "channel":
            group, slug = parts[2], parts[3]
            origin_url, _ = get_channel_origin(group, slug)
            if not origin_url:
                return self._send(404, "Channel tidak ditemukan")
            exp = int(time.time()) + TOKEN_TTL_SECONDS
            token = make_token(group, slug, exp, "")
            location = f"/stream/live/{group}/{slug}/master.m3u8?exp={exp}&token={token}"
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        # --- Route B: URL final (dengan token) ---
        # /stream/live/{group}/{slug}/{file}?exp=...&token=...&u=...
        if len(parts) >= 5 and parts[0] == "stream" and parts[1] == "live":
            group, slug = parts[2], parts[3]
            exp = qs.get("exp", [None])[0]
            token = qs.get("token", [None])[0]
            u = qs.get("u", [""])[0]

            if not verify_token(group, slug, exp, token, u):
                return self._send(403, "Token tidak valid atau sudah kedaluwarsa")

            user_agent = get_group_ua(group)

            if u:
                origin_url = decode_u(u)
            else:
                origin_url, _ = get_channel_origin(group, slug)
                if not origin_url:
                    return self._send(404, "Channel tidak ditemukan")

            try:
                status, body, ctype = fetch_origin(origin_url, user_agent)
            except urllib.error.HTTPError as e:
                return self._send(e.code, f"Upstream error {e.code}")
            except Exception as e:
                return self._send(502, f"Gagal fetch origin: {e}")

            is_playlist = origin_url.split("?")[0].endswith(".m3u8") or "mpegurl" in ctype.lower()

            if is_playlist:
                text = body.decode("utf-8", errors="ignore")
                rewritten = rewrite_playlist(text, origin_url, group, slug, exp, token, user_agent)
                return self._send(200, rewritten, "application/vnd.apple.mpegurl")
            else:
                out_ctype = ctype if ctype else "video/MP2T"
                return self._send(200, body, out_ctype)

        return self._send(404, "Not found")
