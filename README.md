# vidiraplay proxy — catatan project

## Status saat ini (ringkasan per grup)
- **Grup 01** (`103.148.44.38:8001`) — jalan lancar, 49 channel. Sempat buffering terus-menerus dulu, penyebabnya BUKAN kode proxy, tapi region Vercel function yang defaultnya di US (jauh dari origin & pemirsa yang di Indonesia) — tiap fetch segmen nambah ~0.85 detik cuma buat latency jaringan, signifikan karena durasi tiap segmen live cuma 2.88 detik. Fixed dengan `"regions": ["sin1"]` (Singapore) di `vercel.json`. **CATATAN: fitur pilih region custom ini butuh Vercel plan Pro** — kalau balik ke Hobby/gratis, config ini bisa keabaikan dan buffering serupa bisa muncul lagi (cek plan dulu kalau kejadian lagi, bukan bug kode).
  Origin ini juga punya keunikan: nama file variant/segmen di master.m3u8 **berubah tiap kali di-fetch** (rotasi anti-cache) — kadang link yang sudah diresolve basi dalam hitungan detik. Ini ditangani otomatis oleh mekanisme **re-resolve `idx`** di `proxy.py` (lihat bagian "Cara kerja proxy" di bawah).
- **Grup 02** — 8 channel, gabungan 2 sumber (sumber lama `103.58.160.157:8278` sudah MATI TOTAL, diganti):
  - `cdn-server-rctiplus.vidiraplay.biz.id` → rcti, mnctv, gtv, inews (multi-bitrate 144p-720p, proxy dari RCTI+)
  - `cdn-transmedia-server.vidiraplay.biz.id` → trans-tv, trans-7, cnn-indonesia, cnbc-indonesia (proxy ke video.detik.com / live.cnbcindonesia.com, single-bitrate 720p)
  - Base_url grup ini dikosongkan (`""`), tiap channel pakai URL absolute penuh di `path` karena dua sumbernya beda domain.
  - Kedua sumber ini gak butuh User-Agent khusus.
  - `rctiplus` kadang balikin 500 intermiten (masalah di backend RCTI+/Akamai sendiri, sudah dikonfirmasi terjadi juga langsung dari HP tanpa lewat proxy — di luar kendali kita, bukan bug proxy).
- **Grup 03** (`cdn-server-vidio.vidiraplay.biz.id`, proxy dari Vidio) — 30 channel, gak butuh User-Agent khusus. Worker ini sudah handle rewrite audio-track (`EXT-X-MEDIA`) sendiri. **Penting soal penamaan** — ada channel yang mirip nama tapi BEDA channel, jangan disamakan slug-nya:
  - `btv` (grup 03) = channel BTV asli — BEDA dengan `berita-satu` (grup 03 juga) yang merupakan channel Berita Satu. Dulu ada salah kaprah slug `btv` dipakai buat Beritasatu di grup 02 versi lama, itu SALAH dan sudah tidak relevan lagi (grup 02 versi lama sudah dihapus total).
  - `musica` (grup 03) BEDA dengan `musik-indonesia` (grup 01) — dua channel musik yang berbeda, jangan digabung.
  - Aljazeera di sini pakai feed English, disamakan slug-nya dengan `aljazeera-english` (grup 02).
- **Grup 04** (`ogietv.biz.id`) — 113 channel. Sempat dites di awal project dan MATI TOTAL, baru hidup lagi belakangan. Karakteristik khusus:
  - **AES-128 encrypted HLS** — tiap playlist punya baris `#EXT-X-KEY:...URI="/key/..."` dengan URI RELATIF. Ini WAJIB di-rewrite juga (bukan cuma baris segmen biasa), kalau tidak player gak bisa fetch key buat dekripsi dan video gagal total. Ditangani oleh `rewrite_key_line()` di `proxy.py` — generik, bukan cuma buat ogietv, sumber AES-128 lain di masa depan otomatis kebantu juga.
  - Fix ini juga yang mengungkap bug lain: origin gak selalu kasih header `Content-Length` (kasus nyata: file key AES-128, cuma 16 byte). Jalur lama proxy pakai `Transfer-Encoding: chunked` manual buat kasus ini, ternyata bikin Vercel Python runtime CRASH (`FUNCTION_INVOCATION_FAILED`). Sudah diganti fallback baca-penuh-ke-memori (aman, karena kasus tanpa Content-Length biasanya file kecil) — lihat catatan di `proxy.py` bagian streaming segmen.
  - **Sempat dicoba mode `direct_subresources`** (sub-playlist/segmen/key diarahkan LANGSUNG ke origin, gak lewat proxy) buat coba benerin `fragParsingError` di beberapa channel (misal trans-tv-2) — **GAGAL, sudah di-nonaktifkan lagi** (`direct_subresources: false` di channel.json grup 04). Penyebab gagalnya: `ogietv.biz.id` TIDAK mengirim header `Access-Control-Allow-Origin` sama sekali, jadi browser/player berbasis web SELALU blokir fetch langsung ke domain itu (CORS). Proxy kita justru WAJIB tetap dipakai buat grup ini karena proxy selalu nambahin `Access-Control-Allow-Origin: *` sendiri. Flag `direct_subresources` di kode TETAP ADA (jangan dihapus, siapa tau berguna buat origin lain yang CORS-nya open), tapi JANGAN diaktifkan buat grup 04 lagi kecuali origin-nya kebukti berubah support CORS.
  - Penamaan slug FHD/HD: channel dengan 1 varian saja → slug polos, tanpa akhiran. Channel dengan 2 varian (FHD & HD) → **yang PERTAMA (FHD, kualitas tertinggi) dapet slug POLOS (tanpa akhiran), yang KEDUA (HD) dapet akhiran `-2`** — misal `trans-tv` (FHD) & `trans-tv-2` (HD), `rcti` (FHD) & `rcti-2` (HD). Ini KONSISTEN dengan konvensi dedup di grup lain (bukan `-1`/`-2` untuk keduanya).
  - "CGTN Documentary" di sumber ini sebenarnya cuma channel CGTN biasa (nama dari providernya salah) — sudah dikoreksi jadi slug+nama `cgtn`.
  - Gak butuh User-Agent khusus.
- Domain-domain yang dipakai (semua 1 project Vercel yang sama, `proxy-stream-server`, cuma beda custom domain):
  - `proxy-stream-server.vidiraplay.biz.id` — **testing only**, TIDAK PERNAH dipublish, TIDAK ADA Referer check.
  - `api-stream.vidiraplay.biz.id` — **publik**, ditanam di website, WAJIB Referer dari `vidiraplay.biz.id`/subdomainnya.
  - **PENTING**: sub-playlist/segmen/key hasil rewrite SELALU absolute ke `proxy-stream-server.vidiraplay.biz.id` (lihat `PROXY_STREAM_DOMAIN` di proxy.py), APAPUN domain titik masuknya. Jadi walau masuk lewat `api-stream` (yang wajib Referer), isi playlist & data video sesudahnya SELALU lewat `proxy-stream-server` yang TIDAK ada Referer check — ini SENGAJA (keputusan user), supaya player yang gak forward header Referer ke request susulan (banyak player kayak gitu) tetap bisa lanjut streaming. **Konsekuensinya: Referer check cuma efektif ngamanin titik masuk, bukan bulk data video-nya** — siapa pun yang nemu URL `proxy-stream-server` hasil rewrite bisa hotlink tanpa Referer sama sekali. Ini trade-off yang disadari & diterima user, JANGAN diubah tanpa diminta.
- Secret token (`PROXY_SECRET_KEY`) di-set lewat Environment Variables di dashboard Vercel — JANGAN taruh secret di kode.

## Cara kerja proxy (ringkas alur teknis)
`api/proxy.py` punya 3 rute, semuanya generik (tidak ada percabangan per-grup):
- **Route A** — `/stream-hls/channel/{group}/{slug}/master.m3u8`. Titik masuk "testing" (format lama, jelas kelihatan ini link streaming).
- **Route B** — `/stream/live/{group}/{slug}/{file}?exp=...&token=...&u=...&idx=...`. URL internal buat sub-playlist & segmen, origin selalu disembunyikan di parameter `u` (base64). Ini TIDAK PERNAH diketik manual, selalu muncul otomatis dari hasil rewrite playlist.
- **Route C** — `/{group}/{slug}` (vanity, contoh `/03/sctv`). Titik masuk "publik", sengaja dibuat mirip endpoint REST API biasa (tanpa embel-embel "stream-hls"/"master.m3u8") biar gak langsung ketauan ini link streaming kalau di-capture.

Route A dan C fungsinya IDENTIK (generate token 24 jam, langsung serve konten — **tidak** redirect 302 lagi, supaya hemat 1 round-trip), cuma beda bentuk path. Keduanya berakhir memanggil method bersama `_serve_live()`.

Mekanisme lain yang berjalan di dalam `_serve_live()` / `rewrite_playlist()`:
- **Streaming chunked** buat segmen `.ts` (64KB per chunk, tidak dibuffer penuh ke memori) — ini kunci utama biar gak buffering, JANGAN diubah balik ke `resp.read()` penuh.
- **Fix "2 tanda tanya"** — nama file di URL hasil rewrite dibikin generik (`playlist.m3u8` / `segment.ts`), TIDAK memakai nama asli dari origin, karena beberapa origin (misal rctiplus) punya URL variant yang sendirinya mengandung query string (`?url=...`) — kalau ditempel apa adanya lalu ditambah `?exp=...&token=...` lagi, jadi 2 tanda `?` dalam 1 URL dan bikin parsing gagal (gejala: stuck loading). Detail origin lengkap tetap disimpan di parameter `u`.
- **Re-resolve via `idx`** — tiap baris variant di MASTER playlist ditandai posisinya (`idx`, 0-based). Kalau origin balikin 404 pas variant/sub-playlist itu di-fetch ulang (link basi — kasus grup 01), proxy otomatis fetch ulang master ASLI dari `channel.json`, ambil variant di posisi `idx` yang sama, retry sekali — transparan buat player. Ini HANYA berlaku untuk baris yang berasal dari master top-level (`is_top_level=True` saat rewrite), bukan buat segmen `.ts` biasa.
- **Rewrite `#EXT-X-KEY` (AES-128)** — buat stream terenkripsi (kasus grup 04/ogietv), baris `#EXT-X-KEY:...URI="..."` juga di-rewrite (bukan cuma baris segmen biasa) lewat `rewrite_key_line()`, karena URI kunci dekripsinya sering RELATIF — kalau dibiarkan, player bakal resolve itu relatif ke domain PROXY (bukan origin), fetch key gagal, video gak bisa didekripsi sama sekali.
- **URL sub-resource SELALU absolute ke `PROXY_STREAM_DOMAIN`** (`proxy-stream-server.vidiraplay.biz.id`), bukan path relatif — supaya konsisten diakses lewat domain testing (tanpa Referer check) walau masternya dibuka dari domain publik (`api-stream`, yang wajib Referer). Lihat catatan trade-off keamanan di bagian "Status saat ini" di atas.
- **Flag `direct_subresources` per-grup** (`get_group_direct_subresources()`) — kalau `true` di channel.json, sub-playlist/segmen/key TIDAK diproxy, langsung dikasih URL origin asli (cuma titik masuk/master yang tetap diproxy). Dibuat buat coba benerin kasus channel yang datanya rusak kalau ikut diproxy, TAPI mensyaratkan origin punya CORS terbuka (`Access-Control-Allow-Origin`) — kalau origin gak punya itu, browser/player bakal blokir fetch langsung dan malah tambah gagal. **Grup 04 sudah dicoba, GAGAL karena ogietv gak ada CORS, jadi flag ini `false` untuk grup 04.** Default `false` untuk semua grup (harus eksplisit diaktifkan per grup, dan WAJIB dites CORS origin-nya dulu sebelum diaktifkan).
- **Fallback tanpa `Content-Length`** — kalau origin gak kasih header `Content-Length` (jarang, contoh: file key AES-128 yang cuma 16 byte), proxy baca penuh response ke memori dulu baru kirim dengan `Content-Length` yang dihitung sendiri. **JANGAN** diganti balik ke `Transfer-Encoding: chunked` manual (nulis hex-length ke `wfile` langsung) — itu pernah bikin Vercel Python runtime crash (`FUNCTION_INVOCATION_FAILED`) waktu dites di grup 04.
- **Hotlink protection per-domain** (`_check_referer`) — cek header `Host` request masuk lewat domain apa:
  - Kalau `Host` ada di `TESTING_DOMAINS_NO_REFERER_CHECK` (isinya `proxy-stream-server.vidiraplay.biz.id`) → SKIP check, bebas diakses tanpa Referer (buat testing manual).
  - Domain lain (termasuk `api-stream.vidiraplay.biz.id`) → WAJIB header `Referer` atau `Origin` yang hostname-nya persis `vidiraplay.biz.id` atau subdomainnya (`ALLOWED_REFERER_DOMAIN`). Kalau tidak ada/tidak cocok → `403 Forbidden`.
  - **CATATAN: ini BUKAN proteksi mutlak** — Referer/Origin bisa dipalsukan manual oleh yang paham teknis (beberapa app punya opsi custom header). Menaikkan standar, bukan menutup total.
  - Berlaku di SEMUA rute (A, B, C) sekaligus, generik.

## Struktur file
- `api/proxy.py` — semua logic di atas. Generik untuk semua grup, jangan ditambah percabangan `if group == "xx"` kecuali benar-benar perlu & sudah didiskusikan ke user.
- `channel.json` — satu-satunya tempat nambah/edit sumber & channel. Format per grup: `base_url`, `user_agent` (null kalau gak perlu), `channels` (mapping slug -> `{"path": "...", "name": "..."}`. `path` dibaca `proxy.py` buat fetch origin — bisa berupa path relatif (digabung dengan `base_url`) ATAU URL absolute penuh kalau `base_url` dikosongkan `""` (kasus grup 02). `name` cuma dibaca generator playlist buat judul, TIDAK dibaca `proxy.py`.
- `vercel.json` — rewrite `/stream-hls/*`, `/stream/*`, dan vanity `/:group/:slug` (2 segmen) ke `api/proxy.py`, plus `"regions": ["sin1"]` (Singapore — lihat catatan buffering grup 01 di atas).
- `requirements.txt` — sengaja kosong, cuma syarat Vercel detect Python runtime. Proxy ini cuma pakai standard library Python.
- `scripts/generate_playlists.py` — baca `channel.json`, generate **3 file**:
  - `playlist.m3u8` → domain testing (`proxy-stream-server`, format `/stream-hls/channel/...`), bebas Referer, buat testing manual.
  - `playlist-original.m3u8` → URL origin asli (tanpa proxy sama sekali), buat referensi/debug.
  - `playlist-referer.m3u8` → domain publik (`api-stream`, format vanity `/grup/slug`), **WAJIB diakses dengan Referer** dari `vidiraplay.biz.id` — kalau ditest pakai curl polos bakal 403, itu WAJAR bukan bug. Ini yang ditanam di website publik.
- `.github/workflows/generate-playlists.yml` — otomatis jalanin `generate_playlists.py` dan commit ketiga file playlist tiap kali `channel.json` berubah (push ke branch main). Abis commit masuk, Vercel auto-redeploy.

## Aturan main kalau nambah grup/sumber baru (04, 05, dst)
1. **Test dulu sumbernya manual** (curl/Termux) sebelum masuk ke channel.json — cek: status code, apakah butuh header khusus (UA/Referer/Cookie), apakah nama file variant/segmen berubah-ubah tiap request (kalau iya, itu sudah otomatis ditangani mekanisme `idx` re-resolve, tidak perlu kode tambahan).
2. **Cukup tambah entry baru di `channel.json`**, jangan ubah entry grup yang sudah ada, dan jangan ubah kode di `proxy.py` — route handler-nya generik, terima grup apa saja yang ada di channel.json.
3. **Cek dulu apakah ada channel yang sebenarnya SAMA dengan channel di grup lain** (misal "TVRI" vs "TVRI Nasional") → **samakan slug-nya**. Tapi HATI-HATI jangan asal samakan berdasarkan nama/singkatan mirip — cek dulu ke user apakah itu channel yang sama atau kebetulan mirip nama/singkatan (contoh nyata: "BTV" vs "Berita Satu" ternyata channel BEDA meski BTV sering diasosiasikan dengan Beritasatu; "Musica" vs "Musik Indonesia" juga beda channel).
4. **Kalau ada nama channel dobel dalam 1 grup**, channel PERTAMA/kualitas tertinggi dapet slug polos (tanpa akhiran), yang kedua & seterusnya dikasih akhiran `-2`, `-3` (contoh: `pbs-kids`, `pbs-kids-2`; atau `trans-tv` FHD & `trans-tv-2` HD).
5. **Isi field `name` di setiap channel baru**, biar judulnya rapi di playlist.
6. Ketiga file playlist **otomatis ke-generate ulang oleh GitHub Actions** begitu `channel.json` di-push ke branch main — TIDAK PERLU generate manual. Kalau mau test lokal dulu, jalankan `python3 scripts/generate_playlists.py`.
7. Kalau origin baru butuh User-Agent khusus, isi `user_agent` di grup itu. Kalau butuh proteksi lain yang lebih rumit (cookie session, dst), diskusikan dulu ke user sebelum nambah kode baru di `proxy.py` — lihat poin larangan di bawah.

## Kalau sebuah SUMBER MATI (origin down/expired) — gimana cek & apa yang boleh diubah
1. **Cek dulu itu beneran mati atau cuma channel tertentu.** Test manual (curl/Termux) ke beberapa channel berbeda dari grup yang sama:
   - Kalau SEMUA channel di grup itu gagal (403/404/timeout/body kosong terus-terusan) → sumber/origin-nya yang mati.
   - Kalau cuma 1-2 channel doang → kemungkinan channel itu aja yang dipindah/dimatiin provider, sumbernya masih hidup.
2. **Pola pengecekan "mati beneran" vs "sementara/rate-limit/gangguan":** ulangi test 2-3x dengan jeda. Kalau hasilnya konsisten gagal di semua percobaan DAN semua channel, baru dianggap mati. Kalau ternyata cuma gangguan sementara (pernah kejadian ke RCTI+ dan grup 01 - lihat status di atas), jangan buru-buru ubah kode/hapus channel - tunggu konfirmasi dari user dulu apakah itu memang gangguan sesaat atau perlu tindakan.
3. **Kalau terbukti mati:** JANGAN dihapus otomatis. Laporkan ke user channel/grup mana yang mati, tunggu keputusan user (mau dihapus, ditunggu nyala lagi, atau diganti sumber baru).

## Cara HAPUS grup atau channel (tanpa ganggu grup lain)
- **Hapus 1 channel:** hapus key slug itu (beserta `path` & `name`) dari `"channels"` di grup terkait pada `channel.json`. Playlist otomatis ke-update lewat GitHub Actions.
- **Hapus 1 grup penuh:** hapus seluruh key grup itu dari `channel.json`. `proxy.py` TIDAK PERLU diubah — grup yang sudah dihapus otomatis dapat 404 kalau masih diakses.
- Setelah hapus apa pun, update juga `_readme` di channel.json dan bagian "Status saat ini" di README ini.

## Cara GANTI sumber suatu grup (origin lama mati, diganti origin baru) tanpa ganggu grup lain
1. **Test origin baru dulu dari nol** — jangan asumsi origin baru butuh header yang sama dengan origin lama di grup itu.
2. **Update HANYA field di dalam grup itu** di `channel.json` (`base_url`, `user_agent`, `channels`). Slug (nama key) sebisa mungkin dipertahankan sama supaya URL publik yang sudah ditanam di website tetap valid.
3. **Grup lain TIDAK BOLEH ikut diubah** — baik di `channel.json` maupun `proxy.py`.
4. **Kalau origin baru butuh logic khusus** yang gak bisa ditangani mekanisme generik yang ada (cookie session, 2-step auth, dst), ini BUTUH kode tambahan di `proxy.py` sebagai jalur terpisah khusus grup itu — diskusikan dulu ke user, jangan ubah logic umum (`make_token`, `verify_token`, `rewrite_playlist`, `_serve_live`, `_check_referer`, streaming chunked, re-resolve `idx`).
5. Push perubahan `channel.json` — playlist otomatis ke-generate ulang.

## Yang JANGAN dilakukan tanpa diminta eksplisit
- Jangan hapus grup/channel apa pun cuma karena kelihatan/diduga mati — selalu konfirmasi ke user dulu.
- Jangan ganti origin suatu grup pakai asumsi origin baru "pasti sama perlakuannya" dengan origin lama — selalu test ulang dari nol.
- Jangan refactor `proxy.py` jadi arsitektur lain — sudah pas dengan constraint Vercel Python runtime + requirements.txt kosong.
- Jangan gabung/samakan logic antar grup walau kelihatan mirip — karakteristik origin-nya beda-beda (buffering, rotasi link, dst).
- Jangan ganti cara streaming segmen `.ts` balik ke buffer-penuh (`resp.read()`).
- Jangan hapus mekanisme re-resolve `idx` atau balikin ke redirect 302 di Route A/C — itu penyebab masalah yang sudah diperbaiki.
- Jangan pakai `Transfer-Encoding: chunked` manual lagi buat kasus origin tanpa `Content-Length` — pernah bikin Vercel Python runtime crash. Fallback yang benar: baca penuh ke memori, kirim dengan `Content-Length` yang dihitung sendiri.
- Jangan hapus rewrite `#EXT-X-KEY` (`rewrite_key_line`) — itu wajib buat stream AES-128 terenkripsi (grup 04 dan sumber sejenis di masa depan), tanpa ini video gak bisa didekripsi sama sekali.
- Jangan nambah percabangan kode khusus per-grup di `proxy.py` (`if group == "xx"`) tanpa didiskusikan dulu ke user.
- Jangan hapus/ubah domain di `TESTING_DOMAINS_NO_REFERER_CHECK` atau `ALLOWED_REFERER_DOMAIN` tanpa diminta eksplisit — itu pengaturan keamanan yang sengaja dipisah publik vs testing.
- Jangan aktifkan `direct_subresources: true` di channel.json manapun tanpa dites CORS origin-nya dulu (cek `Access-Control-Allow-Origin` di response header origin) — kalau origin gak ada CORS, mode ini bikin video makin gagal (kasus nyata: grup 04/ogietv).
- Jangan ubah `PROXY_STREAM_DOMAIN` jadi relatif lagi (path doang tanpa domain) — sub-resource sengaja SELALU absolute ke domain testing, ini keputusan user yang disengaja (trade-off keamanan, lihat "Status saat ini").
- Jangan samakan slug channel cuma berdasarkan nama/singkatan yang terdengar mirip — selalu konfirmasi ke user dulu (lihat kasus BTV vs Berita Satu, Musica vs Musik Indonesia).
