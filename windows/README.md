# Windows kurulum sihirbazı (Inno Setup)

Bu klasördeki `SesVer.iss`, SesVer için klasik "İleri → İleri → Kur → Bitti"
tarzı bir Windows kurulum sihirbazı tanımlar.

**Önemli:** Bu dosya Mac'te yazıldı ve test edilmedi — derleme ve test Windows'ta
yapılmalı. Aşağıdaki adımları izleyin.

## Derleme adımları (Windows'ta)

1. [Inno Setup'ı](https://jrsoftware.org/isinfo.php) indirip kurun (ücretsiz, ~3 MB).
2. `SesVer.iss` dosyasına çift tıklayın — Inno Setup Compiler açılır.
3. Üstteki **Compile** (ya da F9) düğmesine basın.
4. Derleme bitince `windows\Output\SesVer-Kurulum.exe` oluşur.

## Ne yapar

- Dosyaları `%LOCALAPPDATA%\SesVer` altına kopyalar (yönetici hakkı istemez).
- Başlat Menüsü ve (isteğe bağlı) Masaüstü kısayolu oluşturur.
- Kurulum bitince "SesVer'u Başlat" seçeneğiyle `baslat.bat`'ı çalıştırır —
  asıl Python ortamı/bağımlılık kurulumu (birkaç dakika) o noktada, zaten
  test edilmiş `baslat.bat` mantığıyla yapılır.
- Python 3.10–3.12 bulunamazsa kurulum başında uyarır ve python.org'u açmayı önerir.
- Kaldırma (Denetim Masası → Programlar) `.venv`/`outputs` klasörlerini de temizler.

## Test etmeniz gerekenler

Bunlar Windows olmadan doğrulanamadı:

- [ ] Sihirbaz gerçekten açılıyor mu, Türkçe mi görünüyor
- [ ] Python bulunamama uyarısı doğru tetikleniyor mu (Python'u geçici kaldırıp deneyin)
- [ ] Kurulum sonrası kısayol gerçekten `baslat.bat`'ı doğru çalışma dizininden açıyor mu
- [ ] Kaldırma işlemi `.venv`'i gerçekten temizliyor mu

Bir sorun çıkarsa Inno Setup'ın kendi hata mesajını/ekran görüntüsünü paylaşın.
