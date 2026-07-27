"""
Vercel Python Serverless Function - Stream Proxy Relay
=======================================================
Fungsi:
- Menyembunyikan URL asli sumber stream (ogietv & astra103)
- Menghasilkan/memvalidasi token dengan masa berlaku 24 jam
- Meneruskan (relay) isi m3u8 / segmen dari sumber asli tanpa
  membocorkan URL/token sumber ke client

Struktur URL publik yang dipakai client:
  /api/proxy?group=01&slug=tvn-movies&exp=<unix_ts>&token=<hmac>

Catatan: file channel.json berisi daftar channel + origin_url
(URL asli) yang dipetakan dari slug+group. origin_url TIDAK
PERNAH dikirim ke client dalam bentuk apapun.
"""

import os
import re
import json
import time
import hmac
import hashlib
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urljoin

# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------

# WAJIB di-set sebagai Environment Variable di Vercel: SECRET_KEY
# Jangan hardcode secret asli di sini.
SECRET_KEY = os.environ.get("SECRET_KEY", "CHANGE_ME_IN_VERCEL_ENV")

TOKEN_TTL_SECONDS = 24 * 60 * 60  # 24 jam

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

CHANNEL_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "channel.json")

_CHANNELS_CACHE = None
_CHANNELS_INDEX = None


def load_channels():
    """Load & cache channel.json, index by (group, slug)."""
    global _CHANNELS_CACHE, _CHANNELS_INDEX
    if _CHANNELS_CACHE is None:
        with open(CHANNEL_JSON_PATH, "r", encoding="utf-8") as f:
            _CHANNELS_CACHE = json.load(f)
        _CHANNELS_INDEX = {}
        for c in _CHANNELS_CACHE:
            _CHANNELS_INDEX[(c["group"], c["slug"])] = c
    return _CHANNELS_CACHE, _CHANNELS_INDEX


def make_token(group, slug, exp):
    """Buat HMAC token untuk group+slug+exp."""
    msg = f"{group}:{slug}:{exp}".encode("utf-8")
    sig = hmac.new(SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return sig


def verify_token(group, slug, exp, token):
    if not exp or not token:
        return False, "missing exp/token"
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False, "invalid exp"
    if time.time() > exp_int:
        return False, "token expired"
    expected = make_token(group, slug, exp_int)
    if not hmac.compare_digest(expected, token):
        return False, "invalid token"
    return True, None


def generate_signed_path(group, slug):
    """Helper untuk generate URL publik baru (dipakai saat build playlist publik)."""
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    token = make_token(group, slug, exp)
    return f"/stream/live/{group}/{slug}/master.m3u8?exp={exp}&token={token}"


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def http_get(url, max_redirects=5):
    """
    Fetch URL, follow redirect (302) secara manual di server-side,
    supaya URL/token asli tidak pernah dikirim ke client.
    Return: (status_code, headers_dict, body_bytes, final_content_type)
    """
    current_url = url
    for _ in range(max_redirects):
        req = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                return resp.status, dict(resp.headers), body, content_type
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if not location:
                    raise
                current_url = urljoin(current_url, location)
                continue
            raise
        except Exception:
            raise
    raise Exception("Too many redirects")


def rewrite_m3u8_body(body_text, base_url):
    """
    Jika body adalah playlist m3u8 (bukan segmen video), pastikan
    referensi relatif di dalamnya tetap valid dengan meresolvenya
    terhadap base_url asli (server-side only). Untuk master.m3u8
    yang mengandung sub-playlist, ini penting agar player tetap
    bisa lanjut streaming.

    Catatan: sub-URL hasil resolve TETAP di-relay lewat proxy ini
    (endpoint /api/segment) supaya origin asli tidak bocor ke client.
    """
    lines = body_text.splitlines()
    out_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # ini baris URL (sub-playlist atau segmen)
            resolved = urljoin(base_url, stripped)
            proxied = "/api/segment?u=" + _encode_segment_url(resolved)
            out_lines.append(proxied)
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _encode_segment_url(url):
    """Encode URL asli segmen dengan token singkat supaya tidak plain-text di client."""
    import base64
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    payload = json.dumps({"u": url, "exp": exp})
    raw = payload.encode("utf-8")
    sig = hmac.new(SECRET_KEY.encode("utf-8"), raw, hashlib.sha256).digest()
    packed = base64.urlsafe_b64encode(raw + b"::" + sig).decode("utf-8")
    return packed


def _decode_segment_url(packed):
    """Decode & verifikasi token segmen. Return url asli atau None jika invalid/expired."""
    import base64
    try:
        raw_with_sig = base64.urlsafe_b64decode(packed.encode("utf-8"))
        raw, sig = raw_with_sig.rsplit(b"::", 1)
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, sig):
            return None, "invalid signature"
        payload = json.loads(raw.decode("utf-8"))
        if time.time() > payload.get("exp", 0):
            return None, "segment link expired"
        return payload.get("u"), None
    except Exception:
        return None, "malformed segment token"


# ---------------------------------------------------------------------------
# Vercel handler
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)

            route = qs.get("route", [None])[0]

            # Route: relay sub-playlist / segmen .ts hasil rewrite master.m3u8
            if parsed.path == "/api/segment" or route == "segment":
                packed = qs.get("u", [None])[0]
                if not packed:
                    self._send_json(400, {"error": "missing u"})
                    return
                origin_url, err = _decode_segment_url(packed)
                if not origin_url:
                    self._send_json(403, {"error": err})
                    return

                status, headers, body, content_type = http_get(origin_url)

                if "mpegurl" in content_type.lower() or origin_url.endswith(".m3u8"):
                    body_text = body.decode("utf-8", errors="ignore")
                    rewritten = rewrite_m3u8_body(body_text, origin_url)
                    out = rewritten.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.end_headers()
                    self.wfile.write(out)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.end_headers()
                    self.wfile.write(body)
                return

            # Path bisa berupa /stream/live/<group>/<slug>/master.m3u8
            m = re.match(r"^/stream/live/(\d{2})/([a-z0-9-]+)/master\.m3u8$", parsed.path)
            if m:
                group, slug = m.group(1), m.group(2)
            else:
                # fallback: hasil rewrite Vercel mengirim group & slug lewat query string
                group = qs.get("group", [None])[0]
                slug = qs.get("slug", [None])[0]
                if not group or not slug:
                    self._send_json(404, {"error": "not found"})
                    return
            exp = qs.get("exp", [None])[0]
            token = qs.get("token", [None])[0]

            ok, err = verify_token(group, slug, exp, token)
            if not ok:
                self._send_json(403, {"error": err})
                return

            _, index = load_channels()
            channel = index.get((group, slug))
            if not channel:
                self._send_json(404, {"error": "channel not found"})
                return

            origin_url = channel["origin_url"]

            status, headers, body, content_type = http_get(origin_url)

            if "mpegurl" in content_type.lower() or origin_url.endswith(".m3u8"):
                body_text = body.decode("utf-8", errors="ignore")
                rewritten = rewrite_m3u8_body(body_text, origin_url)
                out = rewritten.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.end_headers()
                self.wfile.write(out)
            else:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

        except Exception as e:
            self._send_json(500, {"error": "internal error", "detail": str(e)})

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))
