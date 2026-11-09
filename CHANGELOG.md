# Değişiklikler

## 1.4.0 (2026-11-09)

- Büyük "Yazdığınız metne ses verin." karşılaması artık panelde sürekli yer kaplamıyor: SesVer açılırken ekranın ortasında kısa bir açılış ekranı olarak belirip kayboluyor, çalışma alanı sayfanın üstünden başlıyor. Tıklama ya da bir tuşla hemen geçilebilir; dil değiştirince ya da sayfayı yenileyince tekrar oynamaz. Hareket azaltma açıksa animasyonsuz gösterilir.
- Sol üstte küçük SesVer markası kalıcı olarak duruyor; uyarılar ve "AI ile üretildi" bilgisi yerinde.
- Mac: SesVer oturum kapatılırken, sistem kapanırken ya da Etkinlik Monitörü'nden kapatıldığında yanlışlıkla çıkan "SesVer beklenmedik şekilde kapandı (çıkış kodu 143)" penceresi artık gösterilmiyor. Gerçek bir hata olursa pencere yine çıkar.
- Mac: SesVer.app süreci kapatılınca (ör. Etkinlik Monitörü'nden) SesVer penceresi de kapanıyor; arkada sahipsiz açık kalmıyor.

## 1.3.1 (2026-11-08)

- Mac kurulumu README'de baştan yazıldı: SesVer artık Apple onaylı bir DMG olarak iniyor. İndirip Uygulamalar'a sürüklemeniz ve açmanız yeterli; "Yine de Aç" adımı yok.
- İlk kurulumda inen her şey sabit sürümle ve bilinen bir SHA-256 özetiyle iniyor: Python, PyTorch ve tüm paketler. Bir dosyanın özeti tutmazsa kurulum durur, hiçbir şey çalıştırılmaz ve SesVer bunu açıkça söyler.
- Uygulamaya özel Python 3.11.18'e güncellendi; artık "en yeni sürüm" sorgusu yapılmıyor, tek bir doğrulanmış sürüm iniyor.
- Ses modeli ve yazıya dökme modeli belirli bir sürüme sabitlendi. Modeli zaten indirdiyseniz yeniden inmez.
- Hızlı Mod paketleri de SHA-256 özetiyle kuruluyor.
- Mac'te macOS 14 (Sonoma) ya da daha yenisi gerekir; daha eski macOS'ta kurulum başlamadan açık bir mesaj çıkar. Eski bir kurulum varsa SesVer onunla açılmaya devam eder.
