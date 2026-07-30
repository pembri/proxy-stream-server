#!/usr/bin/env python3
"""
scripts/generate_playlists.py

Generate 3 file playlist dari channel.json:
  - playlist.m3u8           -> URL testing (proxy-stream-server, format lama
                                /stream-hls/channel/..., TANPA Referer check)
  - playlist-original.m3u8  -> URL ORIGIN asli (origin kelihatan, buat referensi)
  - playlist-referer.m3u8   -> URL vanity publik (api-stream, format /grup/slug,
                                WAJIB Referer vidiraplay.biz.id - lihat catatan
                                di api/proxy.py _check_referer). Ini yang
                                dipakai buat ditanam di website publik.

Dipanggil otomatis oleh GitHub Actions (.github/workflows/generate-playlists.yml)
setiap kali channel.json berubah (nambah, ubah, atau hapus channel/grup).
Bisa juga dijalankan manual:

    python3 scripts/generate_playlists.py

CATATAN PENTING:
- Script ini HANYA membaca channel.json, TIDAK PERNAH mengubahnya, dan
  TIDAK ADA hubungannya dengan logic proxy di api/proxy.py (proxy tetap
  jalan apa adanya, tidak peduli file playlist ini ada atau tidak).
  Aman dijalankan berkali-kali kapan saja.
- Tiap channel di channel.json berbentuk {"path": "...", "name": "..."}.
  "name" dipakai buat judul #EXTINF di sini. Kalau suatu channel belum
  punya "name" (cuma path string biasa / lupa diisi), judul fallback ke
  slug apa adanya - bukan error, cuma kurang rapi.
- playlist-referer.m3u8 isinya link yang BAKAL DITOLAK (403) kalau dites
  pakai curl polos tanpa header Referer - itu WAJAR, bukan bug, karena
  domain api-stream memang mewajibkan Referer dari vidiraplay.biz.id.
  Testing manual tetap pakai playlist.m3u8 (domain proxy-stream-server).
"""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
CHANNEL_JSON = os.path.join(ROOT, "channel.json")
OUT_PROXY = os.path.join(ROOT, "playlist.m3u8")
OUT_ORIGINAL = os.path.join(ROOT, "playlist-original.m3u8")
OUT_REFERER = os.path.join(ROOT, "playlist-referer.m3u8")

# Domain testing (TIDAK PERNAH dipublish) - format /stream-hls/channel/..., bebas Referer
PROXY_DOMAIN = "proxy-stream-server.vidiraplay.biz.id"
# Domain publik (WAJIB Referer vidiraplay.biz.id) - format vanity /grup/slug
API_STREAM_DOMAIN = "api-stream.vidiraplay.biz.id"


def load_channels():
    with open(CHANNEL_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def channel_path_and_name(entry, slug):
    # entry bisa berbentuk {"path": "...", "name": "..."} (schema baru)
    # atau string path polos (schema lama) - dua-duanya didukung.
    if isinstance(entry, dict):
        return entry.get("path", ""), entry.get("name", slug)
    return entry, slug


def build():
    channels = load_channels()

    proxy_lines = ["#EXTM3U"]
    original_lines = ["#EXTM3U"]
    referer_lines = ["#EXTM3U"]

    # urutkan grup by key ("01", "02", "03", ...) biar konsisten & deterministik
    group_keys = sorted(k for k in channels.keys() if not k.startswith("_"))

    for group in group_keys:
        grp = channels[group]
        base_url = grp.get("base_url", "")
        user_agent = grp.get("user_agent")
        group_title = f"Grup {group}"

        # urutkan slug channel biar output stabil (gampang di-diff di git)
        for slug in sorted(grp.get("channels", {}).keys()):
            rel, display = channel_path_and_name(grp["channels"][slug], slug)

            original_url = base_url + rel
            proxy_url = f"https://{PROXY_DOMAIN}/stream-hls/channel/{group}/{slug}/master.m3u8"
            referer_url = f"https://{API_STREAM_DOMAIN}/{group}/{slug}"

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

    total = sum(len(channels[g].get("channels", {})) for g in group_keys)
    print(f"Generated {OUT_PROXY}, {OUT_ORIGINAL}, dan {OUT_REFERER} - total {total} channel di {len(group_keys)} grup.")


if __name__ == "__main__":
    build()
