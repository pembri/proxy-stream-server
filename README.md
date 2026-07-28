# vidiraplay proxy — catatan project

## Status saat ini
- **Grup 01** (`103.148.44.38:8001`) — jalan, tapi kadang buffering (bitrate 4-5Mbps, cuma 1 variant, gak ada pilihan rendah).
- **Grup 02** (`103.58.160.157:8278`) — jalan lancar. Origin ini butuh `User-Agent` khusus (lihat `channel.json` -> `"02".user_agent`), kalau gak dikirim origin bisa nolak/berulah.
- Domain proxy yang dipakai: `proxy-stream-server.vidiraplay.biz.id` (custom domain di Vercel, project `proxy-stream-server`).
- Secret token (`PROXY_SECRET_KEY`) di-set lewat Environment Variables di dashboard Vercel — JANGAN taruh secret di kode.

## Struktur file
- `api/proxy.py` — logic proxy generik: redirect awal (buat token 24 jam) -> serve/stream ulang isi origin, rewrite semua URI di dalam .m3u8 supaya tetap lewat proxy (origin gak keliatan langsung di address bar/response). Segmen `.ts` di-stream chunk 64KB, bukan dibuffer penuh (ini yang bikin lancar, jangan diubah ke cara buffer-penuh lagi kecuali disuruh).
- `channel.json` — satu-satunya tempat nambah/edit sumber & channel. Format per grup: `base_url`, `user_agent` (null kalau gak perlu), `channels` (mapping slug -> path relatif).
- `vercel.json` — rewrite semua path `/stream-hls/*` dan `/stream/*` ke `api/proxy.py`.
- `requirements.txt` — sengaja kosong, cuma syarat Vercel detect Python runtime. Proxy ini cuma pakai standard library Python.

## Aturan main kalau nambah grup/sumber baru (03, 04, dst)
1. **Test dulu sumbernya manual** (curl/Termux) sebelum masuk ke channel.json — cek: status code, apakah butuh header khusus (UA/Referer/Cookie), apakah nama file variant/segmen berubah-ubah tiap request (kalau iya, berarti emang harus selalu fetch fresh, sudah otomatis ditangani proxy).
2. **Cukup tambah entry baru di `channel.json`**, jangan ubah entry `"01"` / `"02"` yang sudah ada, dan jangan ubah kode di `proxy.py` — route handler-nya generik, terima grup apa saja yang ada di channel.json.
3. **Kalau ada channel yang sebenarnya sama dengan channel di grup lain** (misal "TVRI" vs "TVRI Nasional"), **samakan slug-nya** supaya konsisten (pola yang sudah dipakai: `tvri`, `tvone`, dst — cek channel.json untuk daftar lengkap slug yang sudah baku).
4. **Kalau ada nama channel dobel dalam 1 grup**, slug kedua & seterusnya dikasih akhiran `-2`, `-3` (contoh: `pbs-kids`, `pbs-kids-2`, `formosa-tv`, `formosa-tv-2`).
5. Setelah nambah grup baru, update juga 2 file gabungan (`gabungan_angka_transvision.m3u8` dan `gabungan_angka_transvision_original.m3u8`) supaya channel baru ikut kepakai di playlist utama.

## Yang JANGAN dilakukan tanpa diminta eksplisit
- Jangan refactor `proxy.py` jadi arsitektur lain (misal ganti ke framework/serverless pattern lain) — sudah pas dengan constraint Vercel Python runtime + requirements.txt kosong.
- Jangan gabung/samakan logic grup 01 dan 02 walau kelihatan mirip — karakteristik origin-nya beda (lihat catatan buffering di atas).
- Jangan ganti cara streaming segmen `.ts` balik ke buffer-penuh (`resp.read()`) — itu penyebab buffering yang sudah diperbaiki.
