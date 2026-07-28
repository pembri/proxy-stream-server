# vidiraplay proxy — catatan project

## Status saat ini
- **Grup 01** (`103.148.44.38:8001`) — jalan, tapi kadang buffering (bitrate 4-5Mbps, cuma 1 variant, gak ada pilihan rendah).
- **Grup 02** (`103.58.160.157:8278`) — jalan lancar. Origin ini butuh `User-Agent` khusus (lihat `channel.json` -> `"02".user_agent`), kalau gak dikirim origin bisa nolak/berulah.
- Domain proxy yang dipakai: `proxy-stream-server.vidiraplay.biz.id` (custom domain di Vercel, project `proxy-stream-server`).
- Secret token (`PROXY_SECRET_KEY`) di-set lewat Environment Variables di dashboard Vercel — JANGAN taruh secret di kode.

## Struktur file
- `api/proxy.py` — logic proxy generik: redirect awal (buat token 24 jam) -> serve/stream ulang isi origin, rewrite semua URI di dalam .m3u8 supaya tetap lewat proxy (origin gak keliatan langsung di address bar/response). Segmen `.ts` di-stream chunk 64KB, bukan dibuffer penuh (ini yang bikin lancar, jangan diubah ke cara buffer-penuh lagi kecuali disuruh).
- `channel.json` — satu-satunya tempat nambah/edit sumber & channel. Format per grup: `base_url`, `user_agent` (null kalau gak perlu), `channels` (mapping slug -> `{"path": "...", "name": "..."}`. `path` dibaca `proxy.py` buat fetch origin, `name` cuma dibaca generator playlist buat judul, TIDAK dibaca `proxy.py`).
- `vercel.json` — rewrite semua path `/stream-hls/*` dan `/stream/*` ke `api/proxy.py`.
- `requirements.txt` — sengaja kosong, cuma syarat Vercel detect Python runtime. Proxy ini cuma pakai standard library Python.
- `scripts/generate_playlists.py` — baca `channel.json` (field `path` & `name`), generate `playlist.m3u8` (URL proxy) & `playlist-original.m3u8` (URL origin asli) di root repo. Bisa dijalankan manual (`python3 scripts/generate_playlists.py`) atau otomatis lewat GitHub Actions.
- `.github/workflows/generate-playlists.yml` — otomatis jalanin `generate_playlists.py` dan commit hasilnya tiap kali `channel.json` berubah (push ke branch main). Abis commit masuk, Vercel auto-redeploy, playlist langsung ke-update di:
  - `https://proxy-stream-server.vidiraplay.biz.id/playlist.m3u8` (pakai URL proxy)
  - `https://proxy-stream-server.vidiraplay.biz.id/playlist-original.m3u8` (pakai URL origin asli)

## Aturan main kalau nambah grup/sumber baru (03, 04, dst)
1. **Test dulu sumbernya manual** (curl/Termux) sebelum masuk ke channel.json — cek: status code, apakah butuh header khusus (UA/Referer/Cookie), apakah nama file variant/segmen berubah-ubah tiap request (kalau iya, berarti emang harus selalu fetch fresh, sudah otomatis ditangani proxy).
2. **Cukup tambah entry baru di `channel.json`**, jangan ubah entry `"01"` / `"02"` yang sudah ada, dan jangan ubah kode di `proxy.py` — route handler-nya generik, terima grup apa saja yang ada di channel.json.
3. **Kalau ada channel yang sebenarnya sama dengan channel di grup lain** (misal "TVRI" vs "TVRI Nasional"), **samakan slug-nya** supaya konsisten (pola yang sudah dipakai: `tvri`, `tvone`, dst — cek channel.json untuk daftar lengkap slug yang sudah baku).
4. **Kalau ada nama channel dobel dalam 1 grup**, slug kedua & seterusnya dikasih akhiran `-2`, `-3` (contoh: `pbs-kids`, `pbs-kids-2`, `formosa-tv`, `formosa-tv-2`).
5. **Isi field `name` di setiap channel baru** (bukan cuma `path`), biar judulnya rapi di playlist (kalau lupa, cuma fallback ke slug apa adanya, bukan error).
6. Playlist (`playlist.m3u8` & `playlist-original.m3u8`) **otomatis ke-generate ulang oleh GitHub Actions** begitu `channel.json` di-push ke branch main — TIDAK PERLU generate manual atau edit playlist secara langsung. Kalau mau test lokal dulu sebelum push, jalankan `python3 scripts/generate_playlists.py`.

## Kalau sebuah SUMBER MATI (origin down/expired) — gimana cek & apa yang boleh diubah
1. **Cek dulu itu beneran mati atau cuma channel tertentu.** Test manual (curl/Termux) ke beberapa channel berbeda dari grup yang sama:
   - Kalau SEMUA channel di grup itu gagal (403/404/timeout/body kosong terus-terusan) -> sumber/origin-nya yang mati.
   - Kalau cuma 1-2 channel doang -> kemungkinan channel itu aja yang dipindah/dimatiin provider, sumbernya masih hidup.
2. **Pola pengecekan "mati beneran" vs "sementara/rate-limit":** ulangi test 2-3x dengan jeda (~30 detik). Kalau hasilnya konsisten kosong/gagal di semua percobaan dan semua channel, baru dianggap mati. Jangan asumsi mati dari 1x percobaan doang (pernah kejadian: ogietv sempat kasih 302 valid di percobaan pertama, tapi ternyata memang sumbernya mati permanen setelah dicek berkali-kali dan channel lain di web/app juga mati).
3. **Kalau terbukti mati:** JANGAN dihapus otomatis oleh Claude. Laporkan ke user channel/grup mana yang mati, tunggu keputusan user (mau dihapus, ditunggu nyala lagi, atau diganti sumber baru).

## Cara HAPUS grup atau channel (tanpa ganggu grup lain)
- **Hapus 1 channel dalam grup:** hapus key slug itu (beserta `path` & `name`-nya) dari `"channels"` di grup terkait pada `channel.json`. Playlist (`playlist.m3u8` & `playlist-original.m3u8`) otomatis ke-update lewat GitHub Actions begitu perubahan ini di-push — tidak perlu edit playlist manual.
- **Hapus 1 grup penuh (misal grup 03 mati total):** hapus seluruh key grup itu (`"03": {...}`) dari `channel.json`. `proxy.py` TIDAK PERLU diubah sama sekali — karena route handler generik cuma baca channel.json, grup yang sudah dihapus otomatis dapat respons 404 "Channel tidak ditemukan" kalau masih ada yang akses.
- Setelah hapus apa pun, jangan lupa update juga `_readme` di channel.json dan bagian "Status saat ini" di README ini biar gak nyasar/bingung di sesi berikutnya.

## Cara GANTI sumber suatu grup (origin lama mati, diganti origin baru) tanpa ganggu grup lain
Karena tiap grup punya "perlakuan khusus" sendiri (grup 01 = tanpa UA khusus tapi rawan buffering; grup 02 = wajib UA khusus tapi lancar), kalau salah satu origin diganti:
1. **Test origin baru dulu dari nol** (ulangi proses testing manual: curl dengan/tanpa UA, cek redirect, cek apakah nama variant/segmen berubah tiap request, cek butuh header apa aja) — JANGAN asumsi origin baru punya kebutuhan header yang sama dengan origin lama di grup itu.
2. **Update HANYA field di dalam grup itu** di `channel.json`: `base_url` dan `user_agent` (sesuai kebutuhan origin baru, bisa jadi beda dari sebelumnya), serta isi `"channels"` (path/slug bisa jadi beda strukturnya, misal dari `/play/aXXX/index.m3u8` ke pola lain). Slug (nama key) sebisa mungkin dipertahankan sama supaya URL proxy yang sudah dipakai user (di playlist / app IPTV) tetap valid.
3. **Grup lain (yang gak diganti) TIDAK BOLEH ikut diubah** — baik base_url, user_agent, channels-nya, maupun kode di `proxy.py`. Kode proxy sudah generik per-grup (baca dari channel.json), jadi mengganti origin 1 grup secara teknis tidak menyentuh grup lain sama sekali selama cuma edit channel.json.
4. **Kalau origin baru butuh perlakuan yang gak bisa ditangani logic generik yang ada** (misal butuh cookie session, butuh 2-step request/token dari halaman lain, dsb — seperti kasus ogietv yang butuh session flow), ini BUTUH kode tambahan di `proxy.py`. Kalau begini, tambahkan sebagai jalur/percabangan khusus untuk grup itu SAJA (misal dicek `if group == "03": ...`), jangan ubah logic umum yang dipakai semua grup (`make_token`, `verify_token`, `rewrite_playlist`, streaming chunked). Diskusikan dulu ke user sebelum nambah percabangan kayak gini, karena nambah kompleksitas.
5. Push perubahan `channel.json` ke branch main — playlist otomatis ke-generate ulang lewat GitHub Actions.


## Yang JANGAN dilakukan tanpa diminta eksplisit
- Jangan hapus grup/channel apa pun cuma karena kelihatan/diduga mati — selalu konfirmasi ke user dulu, kecuali user sudah eksplisit bilang "hapus".
- Jangan ganti origin suatu grup pakai asumsi origin baru "pasti sama perlakuannya" dengan origin lama — selalu test ulang dari nol.
- Jangan refactor `proxy.py` jadi arsitektur lain (misal ganti ke framework/serverless pattern lain) — sudah pas dengan constraint Vercel Python runtime + requirements.txt kosong.
- Jangan gabung/samakan logic grup 01 dan 02 walau kelihatan mirip — karakteristik origin-nya beda (lihat catatan buffering di atas).
- Jangan ganti cara streaming segmen `.ts` balik ke buffer-penuh (`resp.read()`) — itu penyebab buffering yang sudah diperbaiki.
- Jangan nambah percabangan kode khusus per-grup di `proxy.py` (`if group == "xx"`) tanpa didiskusikan dulu ke user — logic generik yang ada harus tetap jadi default.
