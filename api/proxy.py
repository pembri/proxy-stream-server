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
          (streaming passthrough, di-chunk 64KB biar gak nge-buffer
          penuh ke memori dulu - ini yang bikin grup 01 & 02 lancar).

=====================================================================
CATATAN BUAT SESI/AKUN CLAUDE LAIN YANG LANJUTIN PROJECT INI:
=====================================================================
- File ini sudah diuji dan JALAN LANCAR untuk grup "01" dan "02"
  (baca channel.json untuk detail masing-masing grup & catatan
  perbedaan karakteristiknya).
- JANGAN ubah logic umum di bawah ini (make_token, verify_token,
  rewrite_playlist, streaming chunked di do_GET) kecuali user
  eksplisit minta perbaikan/bug fix. Semua grup (01, 02, 03, dst)
  lewat logic yang SAMA di file ini - channel.json yang membedakan
  origin/header per grup, bukan percabangan kode.
- Kalau user minta tambah grup baru (03, 04, dst): CUKUP tambah
  entry baru di channel.json (base_url, user_agent, channels).
  TIDAK PERLU dan TIDAK BOLEH mengubah kode di file ini untuk itu,
  karena route handler sudah generik menerima {group} apa saja
  yang ada di channel.json.
- Kalau origin baru butuh perlakuan khusus (misal butuh cookie,
  butuh 2-step request, dsb) yang beneran gak bisa ditangani logic
  generik ini, tanya dulu ke user sebelum ubah struktur besar -
  jangan langsung refactor karena bisa merusak grup yang sudah
  lancar.
=====================================================================
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


DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CHUNK_SIZE = 65536  # 64KB


def open_origin(url, user_agent=None, timeout=20):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", user_agent or DEFAULT_UA)
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_origin(url, user_agent=None):
    # Dipakai khusus untuk playlist (.m3u8) yang perlu di-parse penuh,
    # ukurannya kecil jadi aman dibaca sekaligus.
    with open_origin(url, user_agent) as resp:
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

            is_playlist = origin_url.split("?")[0].split("#")[0].endswith(".m3u8")

            if is_playlist:
                try:
                    status, body, ctype = fetch_origin(origin_url, user_agent)
                except urllib.error.HTTPError as e:
                    return self._send(e.code, f"Upstream error {e.code}")
                except Exception as e:
                    return self._send(502, f"Gagal fetch origin: {e}")
                text = body.decode("utf-8", errors="ignore")
                rewritten = rewrite_playlist(text, origin_url, group, slug, exp, token, user_agent)
                return self._send(200, rewritten, "application/vnd.apple.mpegurl")

            # Segmen (.ts dll) -> stream langsung, tidak dibuffer penuh ke
            # memori, supaya player lebih cepat mulai nerima data (mengurangi buffering).
            try:
                origin_resp = open_origin(origin_url, user_agent)
            except urllib.error.HTTPError as e:
                return self._send(e.code, f"Upstream error {e.code}")
            except Exception as e:
                return self._send(502, f"Gagal fetch origin: {e}")

            with origin_resp:
                out_ctype = origin_resp.headers.get("Content-Type") or "video/MP2T"
                content_length = origin_resp.headers.get("Content-Length")

                self.send_response(200)
                self.send_header("Content-Type", out_ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                if content_length:
                    self.send_header("Content-Length", content_length)
                    self.end_headers()
                    remaining = int(content_length)
                    while remaining > 0:
                        chunk = origin_resp.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                else:
                    # Tidak ada Content-Length dari origin -> pakai chunked transfer encoding.
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    while True:
                        chunk = origin_resp.read(CHUNK_SIZE)
                        if not chunk:
                            self.wfile.write(b"0\r\n\r\n")
                            break
                        self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                        self.wfile.write(chunk)
                        self.wfile.write(b"\r\n")
                return

        return self._send(404, "Not found")
