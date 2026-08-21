# CryptoSlate → Discord Auto Notifier

Bot gratis (tanpa server, tanpa biaya) yang otomatis kirim artikel baru dari
CryptoSlate ke channel Discord kamu, jalan tiap 15 menit via GitHub Actions.

## Cara kerja
1. `main.py` cek RSS feed CryptoSlate (`https://cryptoslate.com/feed/`)
2. Bandingin dengan artikel yang udah pernah dikirim (`last_seen.json`)
3. Artikel baru dikirim ke Discord lewat webhook, dalam bentuk embed
   (judul, ringkasan, gambar, link)
4. GitHub Actions jalanin script ini otomatis tiap 15 menit, gratis

## Setup
Lihat panduan step-by-step yang diberikan di chat.

## Ganti sumber berita
Untuk memantau situs lain, ganti nilai `FEED_URL` di `main.py` dengan
URL RSS feed situs tersebut.
