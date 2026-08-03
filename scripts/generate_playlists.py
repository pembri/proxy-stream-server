#!/usr/bin/env python3
"""
scripts/generate_playlists.py

Generate 3 file playlist dari channel.json + channel_codes.json:
  - playlist.m3u8           -> URL testing (proxy-stream-server, format
                                /hls/ch/{group}{kode}/master.m3u8, TANPA
                                Referer/IP/UA check - cuma token+exp)
  - playlist-original.m3u8  -> URL ORIGIN asli (origin kelihatan, buat referensi)
  - playlist-referer.m3u8   -> URL gerbang publik (api-stream, format
                                /hls/ch/{group}{kode}/master.m3u8, WAJIB
                                Referer+IP+UA - lihat catatan di api/proxy.py)

Dipanggil otomatis oleh GitHub Actions (.github/workflows/generate-playlists.yml)
setiap kali channel.json berubah (nambah, ubah, atau hapus channel/grup) -
workflow itu jalanin generate_codes.py (mode fill-missing) DULU sebelum
script ini, biar channel baru otomatis dapet kode sebelum playlist dibuat.

Bisa juga dijalankan manual:
    python3 scripts/generate_codes.py      # pastikan kode sudah ada
    python3 scripts/generate_playlists.py

CATATAN PENTING:
- Script ini baca channel.json DAN channel_codes.json, TIDAK PERNAH
  mengubah keduanya, dan TIDAK ADA hubungannya dengan logic proxy di
  api/proxy.py (proxy tetap jalan apa adanya, tidak peduli file playlist
  ini ada atau tidak). Aman dijalankan berkali-kali kapan saja.
- Kalau suatu channel BELUM punya kode di channel_codes.json (lupa jalanin
  generate_codes.py dulu), channel itu DILEWATI (skip) dari playlist,
  bukan error - supaya channel lain tetap ke-generate normal. Pesan
  peringatan dicetak ke console.
- playlist-referer.m3u8 isinya link yang BAKAL DITOLAK (403) kalau dites
  pakai curl polos tanpa header Referer/UA yang sesuai - itu WAJAR, bukan
  bug. Testing manual tetap pakai playlist.m3u8 (domain proxy-stream-server).
"""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
CHANNEL_JSON = os.path.join(ROOT, "channel.json")
CODES_JSON = os.path.join(ROOT, "channel_codes.json")
OUT_PROXY = os.path.join(ROOT, "playlist.m3u8")
OUT_ORIGINAL = os.path.join(ROOT, "playlist-original.m3u8")
OUT_REFERER = os.path.join(ROOT, "playlist-referer.m3u8")

# Domain testing (TIDAK PERNAH dipublish) - bebas Referer/IP/UA, tetap wajib token+exp
PROXY_DOMAIN = "proxy-stream-server.vidiraplay.biz.id"
# Domain publik (WAJIB Referer+IP+UA) - ditanam di website
API_STREAM_DOMAIN = "api-stream.vidiraplay.biz.id"


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def channel_path_and_name(entry, slug):
    # entry bisa berbentuk {"path": "...", "name": "..."} (schema baru)
    # atau string path polos (schema lama) - dua-duanya didukung.
    if isinstance(entry, dict):
        return entry.get("path", ""), entry.get("name", slug)
    return entry, slug


def build():
    channels = load_json(CHANNEL_JSON)
    codes = load_json(CODES_JSON, default={})

    proxy_lines = ["#EXTM3U"]
    original_lines = ["#EXTM3U"]
    referer_lines = ["#EXTM3U"]

    group_keys = sorted(k for k in channels.keys() if not k.startswith("_"))
    skipped = []

    for group in group_keys:
        grp = channels[group]
        base_url = grp.get("base_url", "")
        user_agent = grp.get("user_agent")
        group_title = f"Grup {group}"
        group_codes = codes.get(group, {})

        for slug in sorted(grp.get("channels", {}).keys()):
            rel, display = channel_path_and_name(grp["channels"][slug], slug)
            code = group_codes.get(slug)
            if not code:
                skipped.append(f"{group}/{slug}")
                continue

            combined = f"{group}{code}"
            original_url = base_url + rel
            proxy_url = f"https://{PROXY_DOMAIN}/hls/ch/{combined}/master.m3u8"
            referer_url = f"https://{API_STREAM_DOMAIN}/hls/ch/{combined}/master.m3u8"

            proxy_lines.append(f'#EXTINF:-1 group-title="{group_title}",{display}')
            proxy_lines.append(proxy_url)

            original_lines.append(f'#EXTINF:-1 group-title="{group_title}",{display}')
            if user_agent:
                original_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
            original_lines.append(original_url)

            referer_lines.append(f'#EXTINF:-1 group-title="{group_title}",{display}')
            referer_lines.append(referer_url)

    with open(OUT_PROXY, "w", encoding="utf-8") as f:
        f.write("\n".join(proxy_lines) + "\n")

    with open(OUT_ORIGINAL, "w", encoding="utf-8") as f:
        f.write("\n".join(original_lines) + "\n")

    with open(OUT_REFERER, "w", encoding="utf-8") as f:
        f.write("\n".join(referer_lines) + "\n")

    total = sum(len(channels[g].get("channels", {})) for g in group_keys) - len(skipped)
    print(f"Generated {OUT_PROXY}, {OUT_ORIGINAL}, dan {OUT_REFERER} - total {total} channel di {len(group_keys)} grup.")
    if skipped:
        print(f"PERINGATAN: {len(skipped)} channel dilewati (belum punya kode di channel_codes.json): {', '.join(skipped)}")
        print("Jalankan 'python3 scripts/generate_codes.py' dulu buat generate kode-nya.")


if __name__ == "__main__":
    build()
