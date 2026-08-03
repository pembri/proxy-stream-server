#!/usr/bin/env python3
"""
scripts/generate_codes.py

Generate/kelola kode acak per channel di channel_codes.json. Kode ini
dipakai buat URL gerbang masuk baru yang menggabungkan {group}{kode}
jadi 1 string (contoh: grup "01" + kode "d2c68a3d..." -> path
"01d2c68a3d..."), biar batas antara grup dan kode gak kelihatan jelas.

DUA MODE:
  python3 scripts/generate_codes.py
      -> mode FILL-MISSING (default). Cuma generate kode buat channel
         yang BELUM punya kode di channel_codes.json (channel baru di
         channel.json). Channel yang SUDAH punya kode TIDAK diubah.
         Ini yang jalan OTOMATIS tiap channel.json berubah (lihat
         .github/workflows/generate-playlists.yml).

  python3 scripts/generate_codes.py --refresh-all
      -> mode REFRESH-ALL. Generate ulang kode buat SEMUA channel
         (termasuk yang sudah ada), bikin semua URL lama otomatis
         basi/invalid. Ini HARUS dijalankan MANUAL oleh user lewat
         GitHub Actions (workflow_dispatch), TIDAK PERNAH otomatis.

Kode = 32 karakter hex (128-bit random), dibuat pakai modul `secrets`
(cryptographically secure), BUKAN random biasa.
"""

import json
import os
import secrets
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
CHANNEL_JSON = os.path.join(ROOT, "channel.json")
CODES_JSON = os.path.join(ROOT, "channel_codes.json")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def new_code():
    return secrets.token_hex(16)  # 32 karakter hex


def build(refresh_all):
    channels = load_json(CHANNEL_JSON)
    codes = {} if refresh_all else load_json(CODES_JSON, default={})

    group_keys = sorted(k for k in channels.keys() if not k.startswith("_"))

    added = 0
    for group in group_keys:
        if group not in codes:
            codes[group] = {}
        for slug in channels[group].get("channels", {}).keys():
            if refresh_all or slug not in codes[group]:
                codes[group][slug] = new_code()
                added += 1

    # Bersihkan entry code buat channel/grup yang sudah dihapus dari channel.json
    for group in list(codes.keys()):
        if group not in group_keys:
            del codes[group]
            continue
        valid_slugs = set(channels[group].get("channels", {}).keys())
        for slug in list(codes[group].keys()):
            if slug not in valid_slugs:
                del codes[group][slug]

    with open(CODES_JSON, "w", encoding="utf-8") as f:
        json.dump(codes, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(v) for v in codes.values())
    mode = "REFRESH-ALL" if refresh_all else "FILL-MISSING"
    print(f"[{mode}] {added} kode baru dibuat, total {total} kode di {len(codes)} grup.")


if __name__ == "__main__":
    refresh_all = "--refresh-all" in sys.argv
    build(refresh_all)
