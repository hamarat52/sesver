# Değişiklikler

## 1.3.1 (2026-11-08)

- Mac kurulumu README'de baştan yazıldı: SesVer artık Apple onaylı bir DMG olarak iniyor. İndirip Uygulamalar'a sürüklemeniz ve açmanız yeterli; "Yine de Aç" adımı yok.
- İlk kurulumda inen her şey sabit sürümle ve bilinen bir SHA-256 özetiyle iniyor: Python, PyTorch ve tüm paketler. Bir dosyanın özeti tutmazsa kurulum durur, hiçbir şey çalıştırılmaz ve SesVer bunu açıkça söyler.
- Uygulamaya özel Python 3.11.18'e güncellendi; artık "en yeni sürüm" sorgusu yapılmıyor, tek bir doğrulanmış sürüm iniyor.
- Ses modeli ve yazıya dökme modeli belirli bir sürüme sabitlendi. Modeli zaten indirdiyseniz yeniden inmez.
- Hızlı Mod paketleri de SHA-256 özetiyle kuruluyor.
- Mac'te macOS 14 (Sonoma) ya da daha yenisi gerekir; daha eski macOS'ta kurulum başlamadan açık bir mesaj çıkar. Eski bir kurulum varsa SesVer onunla açılmaya devam eder.
