# Değişiklikler

## 1.4.1 (2026-11-12)

- İlk üretim mesajı artık doğru: ses modeli bilgisayarınızda kayıtlıysa yalnız "belleğe yükleniyor, indirme yapılmaz" yazar. Model gerçekten ilk kez inecekse bunu boyutuyla (yaklaşık 5 GB) bir kez söyler ve indirme sürerken "Ses modeli indiriliyor: 1.49 / 4.96 GB (%30)" gibi anlaşılır bir ilerleme gösterir. Normal üretim, klon, ses tarifi ve kuyrukta aynı.
- "0/0 B | 0/0 B | 6.4s" gibi ham ilerleme satırları arayüzde görünmüyor; durum mesajı ilerleme göstergesinin altında soluklaşmıyor, okunuyor.
- Adaylar: her aday kartında seed ve üretim süresi yazıyor ("Aday 2 · seed 22 · 41.3 saniye"), bitince toplam süre görünüyor.
- Adaylar: seed değiştirilebiliyor. Bir adayın seed'ini yazıp "Yeniden üret"e basınca yalnız o aday yeniden üretilir, diğerleri değişmez. Geçerli seed 0 ile 4294967295 arası bir tam sayı; aynı tarif, aynı cümle ve aynı seed aynı sesi verir. Kaydedilen ses, seçilen adayın gerçek seed'ini saklar.
- Aday kartları sadeleşti: oynatıcı kartın içine sığıyor, düğmeler taşmıyor, kaydırma çubuğu çıkmıyor (dar pencere ve Arapça dahil).
- Windows: kaldırırken indirilen Python ortamını ve paketleri (yaklaşık 3 GB) saklamayı seçebilirsiniz ("Sakla" varsayılan). Aynı klasöre yeniden kurunca bunlar yeniden inmez. Sessiz kaldırma eskisi gibi siler; `/BILESENLERISAKLA` ile saklar.
- Windows kurulum testleri, üstüne yeniden kurulumda ve "Sakla" ile kaldırıp yeniden kurulumda paketlerin yeniden inmediğini ölçüyor.

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
