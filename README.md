# Simpan Video

Pengunduh video open source yang sederhana dan elegan. Tempel tautan dari media sosial,
pilih kualitas, lalu simpan videonya ke komputermu. Dibangun di atas
[yt-dlp](https://github.com/yt-dlp/yt-dlp), yang mendukung ribuan situs
(YouTube, Instagram, TikTok, Facebook, X/Twitter, Vimeo, Reddit, dan banyak lagi).

Semua berjalan di komputermu sendiri. Server hanya bisa diakses dari `127.0.0.1`
dan tidak ada data yang dikirim ke pihak lain.

## Fitur

- Tempel tautan, pratinjau muncul otomatis (judul, thumbnail, durasi)
- Pilih Video (Terbaik, 1080p, 720p, dan seterusnya) atau Audio (MP3)
- Antrean unduhan dengan progres, kecepatan, sisa waktu, dan tombol batal
- Tampilan terang dan gelap mengikuti pengaturan perangkat
- Satu file Python dan satu file HTML, tanpa framework tambahan

## Cara memakai

Kebutuhan: Python 3.8 atau lebih baru.

```bash
pip install -r requirements.txt
python app.py
```

Browser akan terbuka otomatis di `http://127.0.0.1:8765/`.

Opsi tambahan:

```bash
python app.py --dir ~/Videos/Unduhan   # folder simpan sendiri
python app.py --port 9000              # port lain
python app.py --no-browser             # jangan buka browser otomatis
```

Folder bawaan: `~/Downloads/Simpan Video`.

### ffmpeg (disarankan)

ffmpeg dibutuhkan untuk kualitas tertinggi (video dan audio digabung) serta konversi MP3.
Tanpa ffmpeg, aplikasi tetap jalan tetapi hanya mengambil format yang sudah menyatu.

- Windows: `winget install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

## Pemecahan masalah

Situs sering mengubah sistemnya. Jika unduhan gagal tanpa sebab jelas, perbarui yt-dlp:

```bash
pip install -U yt-dlp
```

Video privat atau yang butuh login tidak bisa diunduh.

## Penggunaan yang bertanggung jawab

Unduh hanya konten milikmu atau yang diizinkan oleh pemiliknya, dan patuhi aturan layanan
serta hukum hak cipta di wilayahmu. Pengembang tidak bertanggung jawab atas penyalahgunaan.

## Lisensi

MIT. Lihat berkas `LICENSE`.
