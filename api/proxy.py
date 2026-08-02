"""
api/proxy.py
Proxy + URL-hider untuk channel IPTV.

=====================================================================
RUTE YANG TERSEDIA (semua generik, tidak ada percabangan per-grup):
=====================================================================
1. Route A - GET /stream-hls/channel/{group}/{slug}/master.m3u8
   Titik masuk "testing" (bentuk path jelas kelihatan ini link
   streaming). Langsung generate token (24 jam) dan LANGSUNG serve
   konten di request yang sama - TIDAK redirect 302 ke Route B lagi
   (redirect dihapus karena buang 1 round-trip yang bikin loading
   awal lebih lambat dari perlu).

2. Route B - GET /stream/live/{group}/{slug}/{file}?exp=...&token=...
              [&u=...][&idx=...]
   URL INTERNAL, muncul otomatis di dalam hasil rewrite playlist
   (sub-playlist, segmen .ts, key AES-128) - TIDAK PERNAH diketik
   manual. "u" = base64 dari URL origin asli (disembunyikan). "idx"
   = posisi variant ini di master asli (dipakai buat re-resolve
   kalau link basi, lihat _reresolve_and_retry).

3. Route C - GET /{group}/{slug}  (contoh: /03/sctv)
   Titik masuk "publik" (vanity URL), sengaja mirip REST API biasa
   (tanpa "stream-hls"/"master.m3u8") supaya kalau di-capture gak
   langsung ketauan ini link streaming. Fungsinya IDENTIK Route A,
   dipakai di domain berbeda (lihat catatan domain di bawah).

Ketiga rute berujung ke method bersama _serve_live(), yang:
  - Fetch origin (dari channel.json via "u"/slug, sesuai kasus).
  - Kalau isinya .m3u8: rewrite SEMUA URI di dalamnya (baris biasa,
    DAN URI="..." di dalam #EXT-X-KEY buat stream AES-128 terenkripsi
    kayak ogietv/grup 04 - lihat rewrite_key_line) supaya tetap lewat
    proxy, origin asli tidak pernah terlihat.
  - Kalau bukan .m3u8 (segmen .ts, file key, dll): diteruskan sebagai
    stream chunked 64KB kalau origin kasih Content-Length (irit
    memori, ini kunci utama biar gak buffering). Kalau origin TIDAK
    kasih Content-Length (jarang, misal file key 16-byte), fallback
    baca penuh ke memori baru dikirim - JANGAN pakai Transfer-Encoding
    chunked manual, itu pernah bikin Vercel Python runtime crash
    (FUNCTION_INVOCATION_FAILED).
  - Re-resolve otomatis (_reresolve_and_retry): kalau variant/sub-
    playlist basi (404) DAN request itu berasal dari top-level master
    (ada "idx"), fetch ulang master fresh dari channel.json, ambil
    variant di posisi idx yang sama, retry sekali - transparan buat
    player. Kasus nyata: origin grup 01 (103.148.44.38) menerbitkan
    nama file variant baru & sekali-pakai tiap master di-fetch.

CATATAN URL SUB-RESOURCE: semua URL hasil rewrite (segmen, sub-
playlist, key) SELALU absolute ke PROXY_STREAM_DOMAIN (domain
testing), BUKAN path relatif - walau master-nya dibuka lewat domain
publik (api-stream). Ini sengaja (keputusan user): domain publik
cuma jadi gerbang masuk yang diproteksi Referer, tapi bulk data
video sesudahnya tetap lewat domain testing yang bebas Referer -
supaya player yang gak forward Referer ke request susulan (banyak
begitu) tetap bisa lanjut streaming. KONSEKUENSI: Referer check
CUMA efektif di titik masuk, bukan di bulk data - trade-off yang
disadari & diterima, JANGAN diubah balik ke path relatif tanpa
diminta.

CATATAN direct_subresources: flag per-grup di channel.json, kalau
true sub-playlist/segmen/key TIDAK diproxy sama sekali (langsung ke
origin asli, cuma master yang diproxy). Dibuat buat coba benerin
channel yang datanya rusak kalau ikut diproxy, TAPI MENSYARATKAN
origin punya CORS terbuka (Access-Control-Allow-Origin) - kalau
tidak, browser/player malah blokir fetch dan tambah gagal. Grup 04
sudah dicoba & GAGAL karena ogietv.biz.id gak ada CORS sama sekali -
flag ini `false` untuk grup 04. JANGAN aktifkan buat grup manapun
tanpa cek CORS origin-nya dulu (curl -I, cek header
Access-Control-Allow-Origin).

=====================================================================
HOTLINK PROTECTION (_check_referer) - berlaku di SEMUA rute (A/B/C):
=====================================================================
- Domain di TESTING_DOMAINS_NO_REFERER_CHECK (proxy-stream-server.
  vidiraplay.biz.id) BEBAS diakses tanpa header Referer - domain ini
  KHUSUS TESTING, TIDAK PERNAH dipublish ke player publik.
- Domain lain (termasuk api-stream.vidiraplay.biz.id, yang DITANAM
  di website publik) WAJIB header Referer/Origin yang hostname-nya
  vidiraplay.biz.id atau subdomainnya (ALLOWED_REFERER_DOMAIN).
  Tanpa itu -> 403. INI BUKAN proteksi mutlak (bisa dipalsukan
  manual oleh yang paham teknis), cuma menaikkan standar.

=====================================================================
CATATAN BUAT SESI/AKUN CLAUDE LAIN YANG LANJUTIN PROJECT INI:
=====================================================================
- File ini sudah diuji dan JALAN LANCAR untuk grup "01", "02", "03",
  "04" (baca channel.json untuk detail & karakteristik tiap grup -
  ada catatan penting soal buffering, rotasi link, enkripsi, dll
  yang beda-beda per grup).
- JANGAN ubah logic umum di sini (make_token, verify_token,
  rewrite_playlist, rewrite_key_line, _serve_live, _check_referer,
  streaming chunked, re-resolve idx) kecuali user eksplisit minta
  perbaikan/bug fix. Semua grup lewat logic yang SAMA - channel.json
  yang membedakan origin/header per grup, bukan percabangan kode.
- Kalau user minta tambah grup baru: CUKUP tambah entry baru di
  channel.json (base_url, user_agent, channels). TIDAK PERLU dan
  TIDAK BOLEH mengubah kode di file ini untuk itu - route handler
  sudah generik menerima {group} apa saja yang ada di channel.json.
- Kalau origin baru butuh perlakuan khusus (cookie session, 2-step
  request, dsb) yang beneran gak bisa ditangani logic generik ini,
  tanya dulu ke user sebelum ubah struktur besar - jangan langsung
  refactor karena bisa merusak grup yang sudah lancar.
- Jangan hapus/ubah TESTING_DOMAINS_NO_REFERER_CHECK, PROXY_STREAM_
  DOMAIN, atau ALLOWED_REFERER_DOMAIN tanpa diminta eksplisit - itu
  pemisahan keamanan publik vs testing yang disengaja.
- Jangan aktifkan direct_subresources di channel.json manapun tanpa
  cek CORS origin-nya dulu.
=====================================================================
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12 jam (diperpendek dari 24 jam - bagian dari proteksi tambahan api-stream)
SECRET_KEY = os.environ.get("PROXY_SECRET_KEY", "ganti-secret-key-ini-di-env-vercel")
ALLOWED_REFERER_DOMAIN = "vidiraplay.biz.id"  # hotlink protection - lihat _check_referer
TESTING_DOMAINS_NO_REFERER_CHECK = {"proxy-stream-server.vidiraplay.biz.id"}  # domain testing, TIDAK pernah dipublish - dikecualikan dari SEMUA proteksi (Referer, IP binding, User-Agent check) - lihat _check_referer & do_GET

# User-Agent yang jelas-jelas bukan browser (tools/script) - ditolak di domain
# yang diproteksi (bukan domain testing). Ini heuristik ringan, BUKAN proteksi
# kuat (gampang dipalsukan), cuma nutup script paling dasar yang gak repot spoof UA.
UA_BLOCKLIST_SUBSTRINGS = [
    "curl", "wget", "python-requests", "python-urllib", "libwww-perl",
    "go-http-client", "postmanruntime", "insomnia", "httpie", "scrapy", "java/",
]

CHANNELS_PATH = os.path.join(os.path.dirname(__file__), "..", "channel.json")
with open(CHANNELS_PATH, "r", encoding="utf-8") as f:
    CHANNELS = json.load(f)


def make_token(group, slug, exp, u="", ip=""):
    """ip="" (string kosong) dipakai konsisten kalau domain testing (IP
    binding TIDAK berlaku di situ). Kalau domain diproteksi (api-stream),
    ip diisi IP asli peminta - token cuma valid dipakai dari IP yang sama."""
    msg = f"{group}:{slug}:{exp}:{u}:{ip}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_token(group, slug, exp, token, u="", ip=""):
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if time.time() > exp_int:
        return False
    expected = make_token(group, slug, exp_int, u, ip)
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
    entry = grp.get("channels", {}).get(slug)
    if not entry:
        return None, None
    # entry = {"path": "...", "name": "..."} - "name" cuma dipakai generator
    # playlist (scripts/generate_playlists.py), diabaikan di sini.
    rel = entry["path"] if isinstance(entry, dict) else entry
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


KEY_URI_RE = re.compile(r'URI="([^"]+)"')


def get_group_direct_subresources(group):
    """Cek flag 'direct_subresources' per grup di channel.json. Kalau True,
    sub-playlist/segmen/key di dalam hasil rewrite TIDAK diproxy - URL-nya
    langsung nunjuk ke origin asli (player fetch langsung ke origin).
    Dipakai buat origin yang datanya rusak/gagal kalau ikut diproxy (contoh:
    grup 04/ogietv - segmen AES-128 sempat kena fragParsingError di player
    kalau ikut lewat proxy, videonya lancar kalau segmen fetch langsung ke
    origin). Cuma titik masuk (master.m3u8) yang tetap diproxy (biar token
    generate & origin tetap disamarkan di request pertama). Default False
    (semua ikut diproxy penuh) - HARUS eksplisit diaktifkan per grup di
    channel.json, bukan behavior baku."""
    grp = CHANNELS.get(group)
    return bool(grp.get("direct_subresources")) if grp else False


def rewrite_key_line(line, base, group, slug, exp, ip="", direct=False):
    """Rewrite URI="..." di baris #EXT-X-KEY (dipakai stream ter-enkripsi
    AES-128, misal ogietv). URI di baris ini SERING kali relatif (contoh:
    "/key/xxxx") - kalau dibiarkan apa adanya, player bakal resolve URI
    itu relatif ke domain PROXY kita (bukan domain origin), bikin fetch
    key gagal total dan video gak bisa didekripsi/gak bisa play sama
    sekali. Jadi URI ini WAJIB di-resolve absolute dulu.

    URL hasil rewrite path RELATIF (bukan absolute ke domain tertentu) -
    supaya otomatis resolve ke domain yang sama dengan yang sedang diakses
    (api-stream ATAU proxy-stream-server), biar proteksi (Referer/IP/UA)
    di domain itu ikut berlaku konsisten di semua request susulan.

    Kalau direct=True (lihat get_group_direct_subresources), URI diarahkan
    LANGSUNG ke origin asli (tidak diproxy) - dipakai untuk origin yang
    datanya rusak kalau lewat proxy."""
    def replace(m):
        key_url = m.group(1)
        abs_key_url = urllib.parse.urljoin(base, key_url)
        if direct:
            return f'URI="{abs_key_url}"'
        u = encode_u(abs_key_url)
        new_token = make_token(group, slug, exp, u, ip)
        query = urllib.parse.urlencode({"exp": exp, "token": new_token, "u": u})
        proxied = f"/stream/live/{group}/{slug}/key?{query}"
        return f'URI="{proxied}"'
    return KEY_URI_RE.sub(replace, line)


def rewrite_playlist(body_text, origin_url, group, slug, exp, token, user_agent, is_top_level=False, direct=False, ip=""):
    base = origin_url.rsplit("/", 1)[0] + "/"
    out_lines = []
    idx = 0
    for line in body_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-KEY") and "URI=" in stripped:
            out_lines.append(rewrite_key_line(line, base, group, slug, exp, ip=ip, direct=direct))
            continue
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        abs_url = urllib.parse.urljoin(base, stripped)

        if direct:
            # Mode direct_subresources aktif (lihat get_group_direct_subresources) -
            # origin ini datanya rusak/gagal kalau ikut diproxy (fragParsingError
            # dkk), jadi sub-playlist/segmen langsung diarahkan ke origin asli.
            # Hanya titik masuk (master.m3u8) yang tetap diproxy.
            out_lines.append(abs_url)
            idx += 1
            continue

        u = encode_u(abs_url)
        new_exp = exp
        new_token = make_token(group, slug, new_exp, u, ip)

        # Nama file di path proxy HARUS bersih dari query string origin
        # (beberapa origin, misal rctiplus, punya URL variant yang sendirinya
        # mengandung "?url=..." - kalau ini ditempel apa adanya ke path lalu
        # ditambah "?exp=...&token=..." lagi, hasilnya ada 2 tanda "?" dalam
        # 1 URL dan bikin query exp/token/u gagal ke-parse -> stuck/loading).
        # Makanya nama file dibikin generik aja berdasarkan ekstensi,
        # detail URL asli sepenuhnya disimpan di param "u".
        path_only = abs_url.split("?", 1)[0].split("#", 1)[0]
        filename = "segment.ts" if not path_only.endswith(".m3u8") else "playlist.m3u8"

        params = {"exp": new_exp, "token": new_token, "u": u}
        if is_top_level:
            # Baris ini adalah entri variant dari MASTER playlist asli
            # (channel.json). Beberapa origin (misal 103.148.44.38 di
            # grup 01) menerbitkan nama file variant BARU & SEKALI-PAKAI
            # tiap kali master di-fetch ulang - link yang sudah diresolve
            # bisa basi cuma dalam hitungan detik. "idx" = posisi variant
            # ini di master (urutan ke berapa, 0-based, di antara baris
            # non-# saja) supaya kalau link ini basi (404), _serve_live
            # bisa fetch ulang master fresh dan ambil variant di posisi
            # yang sama, lalu retry sekali - generik buat semua grup,
            # cuma jalan kalau memang origin butuh (lihat _serve_live).
            params["idx"] = idx
        query = urllib.parse.urlencode(params)
        # Path RELATIF (bukan absolute ke domain tertentu) - biar otomatis
        # resolve ke domain yang sama dengan yang sedang diakses (api-stream
        # ATAU proxy-stream-server), supaya proteksi (Referer/IP/UA) di
        # domain itu ikut berlaku konsisten untuk request susulan.
        proxied = f"/stream/live/{group}/{slug}/{filename}?{query}"
        out_lines.append(proxied)
        idx += 1
    return "\n".join(out_lines)


def is_blocked_user_agent(ua):
    """Cek apakah User-Agent kelihatan jelas BUKAN browser (tools/script).
    Dipakai buat domain yang diproteksi (bukan domain testing). Kosong
    (tidak ada header UA sama sekali) juga dianggap blocked - browser
    beneran SELALU kirim User-Agent."""
    if not ua:
        return True
    ua_low = ua.lower()
    return any(s in ua_low for s in UA_BLOCKLIST_SUBSTRINGS)


def get_client_ip(handler):
    """Ambil IP asli client. Di Vercel, koneksi masuk lewat proxy platform
    duluan, jadi IP asli client ada di header X-Forwarded-For (entri
    PERTAMA = IP client asli), bukan di handler.client_address (itu IP
    internal Vercel). Fallback ke X-Real-IP, baru ke client_address kalau
    dua-duanya gak ada (misal waktu testing lokal)."""
    xff = handler.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    xreal = handler.headers.get("X-Real-IP", "")
    if xreal:
        return xreal.strip()
    return handler.client_address[0] if handler.client_address else ""


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

    def _is_testing_domain(self):
        host_header = (self.headers.get("Host") or "").split(":")[0].lower()
        return host_header in TESTING_DOMAINS_NO_REFERER_CHECK

    def _check_referer(self):
        """Hotlink protection: cuma terima request yang Referer/Origin-nya
        berasal dari domain vidiraplay.biz.id atau subdomainnya (misal
        iptv.vidiraplay.biz.id). Request tanpa Referer/Origin (curl polos,
        app IPTV generik yang gak kirim header ini) langsung ditolak.
        CATATAN: ini menaikkan standar proteksi, TAPI BUKAN proteksi mutlak
        - Referer/Origin bisa dipalsukan manual oleh yang paham teknis
        (beberapa app punya opsi custom header). Berlaku generik untuk
        SEMUA rute (A, B, C) - tidak spesifik 1 grup.

        KECUALI: domain di TESTING_DOMAINS_NO_REFERER_CHECK (misal
        proxy-stream-server.vidiraplay.biz.id) SENGAJA dibebaskan dari
        check ini (dan dari IP binding + UA check juga, lihat do_GET) -
        domain itu dipakai user cuma buat testing manual (curl dari
        Termux dll), TIDAK PERNAH dipublish/ditanam di player publik."""
        if self._is_testing_domain():
            return True

        ref = self.headers.get("Referer") or self.headers.get("Origin") or ""
        if not ref:
            return False
        try:
            host = urllib.parse.urlparse(ref).hostname or ""
        except Exception:
            return False
        return host == ALLOWED_REFERER_DOMAIN or host.endswith("." + ALLOWED_REFERER_DOMAIN)

    def do_GET(self):
        is_testing = self._is_testing_domain()

        if not self._check_referer():
            return self._send(403, "Forbidden")

        if not is_testing and is_blocked_user_agent(self.headers.get("User-Agent", "")):
            return self._send(403, "Forbidden")

        # ip_for_token: "" konsisten kalau domain testing (IP binding TIDAK
        # berlaku di situ), atau IP asli client kalau domain diproteksi
        # (api-stream) - dipakai buat generate & verifikasi token supaya
        # token cuma valid dipakai dari IP yang sama dengan yang minta
        # pertama kali.
        ip_for_token = "" if is_testing else get_client_ip(self)

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        parts = [p for p in path.split("/") if p]

        # --- Route A: entry point ---
        # /stream-hls/channel/{group}/{slug}/master.m3u8
        # Langsung serve konten di sini (TIDAK redirect ke Route B lagi)
        # supaya player gak buang 1 round-trip ekstra sebelum mulai load.
        # Sub-playlist & segmen di dalam hasil rewrite tetap pakai URL
        # /stream/live/... (origin tetap disembunyikan, cuma titik masuk
        # awal yang dipercepat).
        if len(parts) >= 5 and parts[0] == "stream-hls" and parts[1] == "channel":
            group, slug = parts[2], parts[3]
            origin_url, _ = get_channel_origin(group, slug)
            if not origin_url:
                return self._send(404, "Channel tidak ditemukan")
            exp = int(time.time()) + TOKEN_TTL_SECONDS
            token = make_token(group, slug, exp, "", ip_for_token)
            return self._serve_live(group, slug, exp, token, "", idx=None, ip=ip_for_token)

        # --- Route B: URL final (dengan token) ---
        # /stream/live/{group}/{slug}/{file}?exp=...&token=...&u=...[&idx=...]
        if len(parts) >= 5 and parts[0] == "stream" and parts[1] == "live":
            group, slug = parts[2], parts[3]
            exp = qs.get("exp", [None])[0]
            token = qs.get("token", [None])[0]
            u = qs.get("u", [""])[0]
            idx_raw = qs.get("idx", [None])[0]
            idx = int(idx_raw) if idx_raw is not None else None
            return self._serve_live(group, slug, exp, token, u, idx=idx, ip=ip_for_token)

        # --- Route C: vanity URL "API palsu" ---
        # /{group}/{slug}  (contoh: /03/sctv)
        # Sengaja dibuat MIRIP endpoint REST API biasa (tanpa embel-embel
        # "stream-hls"/"master.m3u8") supaya kalau ada yang capture traffic
        # player, URL-nya tidak langsung kelihatan sebagai link streaming.
        # Fungsinya IDENTIK dengan Route A - cuma bentuk path-nya beda.
        # Domain yang dipakai buat rute ini: api-stream.vidiraplay.biz.id
        # (didaftarkan sebagai custom domain terpisah di Vercel, tapi
        # tetap 1 project/deployment yang sama dengan proxy-stream-server).
        if len(parts) == 2:
            group, slug = parts[0], parts[1]
            origin_url, _ = get_channel_origin(group, slug)
            if not origin_url:
                return self._send(404, "Not found")
            exp = int(time.time()) + TOKEN_TTL_SECONDS
            token = make_token(group, slug, exp, "", ip_for_token)
            return self._serve_live(group, slug, exp, token, "", idx=None, ip=ip_for_token)

    def _reresolve_and_retry(self, group, slug, idx, user_agent):
        """Fetch ulang master ASLI channel ini dari channel.json (fresh,
        bukan dari cache/token lama), ambil baris variant ke-idx (0-based,
        di antara baris non-# saja), resolve jadi absolute URL, lalu fetch
        isinya. Return (status, body, ctype) kalau berhasil, None kalau
        gagal (supaya caller fallback ke error seperti biasa)."""
        try:
            master_origin_url, _ = get_channel_origin(group, slug)
            if not master_origin_url:
                return None
            m_status, m_body, m_ctype = fetch_origin(master_origin_url, user_agent)
            base = master_origin_url.rsplit("/", 1)[0] + "/"
            text = m_body.decode("utf-8", errors="ignore")
            count = 0
            fresh_abs_url = None
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if count == idx:
                    fresh_abs_url = urllib.parse.urljoin(base, stripped)
                    break
                count += 1
            if not fresh_abs_url:
                return None
            return fetch_origin(fresh_abs_url, user_agent)
        except Exception:
            return None

    def _serve_live(self, group, slug, exp, token, u, idx=None, ip=""):
        """Logic inti serve konten (dulu = Route B). Dipanggil langsung dari
        entry point (Route A, tanpa redirect) maupun dari URL /stream/live/...
        yang muncul di dalam playlist hasil rewrite (sub-playlist, segmen).
        "ip" = "" kalau domain testing (IP binding gak berlaku), atau IP
        asli client kalau domain diproteksi (api-stream)."""
        if not verify_token(group, slug, exp, token, u, ip):
            return self._send(403, "Token tidak valid atau sudah kedaluwarsa")

        user_agent = get_group_ua(group)
        is_top_level = u == ""  # dipanggil dari Route A (entry point) = master asli

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
                if e.code == 404 and idx is not None:
                    # Link variant ini kemungkinan basi (origin menerbitkan
                    # nama file baru & sekali-pakai tiap master di-fetch -
                    # lihat catatan di rewrite_playlist). Coba re-resolve:
                    # fetch ulang master ASLI dari channel.json, ambil
                    # variant di posisi "idx" yang sama, retry sekali.
                    retried = self._reresolve_and_retry(group, slug, idx, user_agent)
                    if retried is not None:
                        status, body, ctype = retried
                    else:
                        return self._send(e.code, f"Upstream error {e.code}")
                else:
                    return self._send(e.code, f"Upstream error {e.code}")
            except Exception as e:
                return self._send(502, f"Gagal fetch origin: {e}")
            text = body.decode("utf-8", errors="ignore")
            direct = get_group_direct_subresources(group)
            rewritten = rewrite_playlist(text, origin_url, group, slug, exp, token, user_agent, is_top_level=is_top_level, direct=direct, ip=ip)
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
                # Origin TIDAK kasih Content-Length (jarang terjadi, contoh:
                # file key AES-128 di grup 04/ogietv). Dulu di sini pakai
                # Transfer-Encoding: chunked manual (nulis hex-length +
                # data langsung ke wfile), TAPI itu bikin Vercel Python
                # runtime crash (FUNCTION_INVOCATION_FAILED) - kemungkinan
                # gak kompatibel sama cara Vercel wrap response BaseHTTP-
                # RequestHandler. Makanya fallback ke cara paling aman:
                # baca semua body ke memori dulu (biasanya file kecil kalau
                # sampai gak ada Content-Length, misal key 16 byte), baru
                # kirim dengan Content-Length yang dihitung sendiri -
                # JANGAN dikembalikan ke chunked manual lagi.
                body = origin_resp.read()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        return self._send(404, "Not found")
