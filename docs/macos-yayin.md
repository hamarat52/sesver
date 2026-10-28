# SesVer macOS yayın hattı (Developer ID + notarize + DMG)

Geliştirici belgesi. Kullanıcıya dönük kurulum metni README.md / AI_KURULUM.md'dedir.

## 1. Mimari: iki dağıtım modu, tek başlatıcı

Paketin yerel başlatıcısı (`Contents/MacOS/SesVer`, kaynak `macos/sesver_app_launcher.c`)
`Contents/Resources/sesver_app.sh`'ı çalıştırır. Bu betik modu kendisi seçer:

| Mod | Ne zaman | Proje dosyaları | Kullanıcı verisi (python-embed, outputs, voices/seslerim, ayarlar.json) |
|---|---|---|---|
| **DMG** | `Contents/Resources/payload/.sesver_payload_version` VAR | Paketin içinde (`payload/`), `SESVER_HOME`'a eşitlenir | `SESVER_HOME` = `~/Library/Application Support/SesVer` |
| **ZIP** | payload YOK (repodaki / GitHub ZIP'indeki `SesVer.app`) | `../../..` (paketin bulunduğu proje klasörü) | Proje klasörü |

DMG modunda eşitleme (`sesver_app.sh`):
- Paket damgası `SESVER_HOME/.sesver_payload_version`'dan farklıysa (ya da `desktop.py` /
  `macos_ortak.sh` eksikse) `rsync -a payload/ SESVER_HOME/` çalışır. **`--delete` yok**: hiçbir
  dosya silinmez. `voices/seslerim`, `outputs`, `python-embed`, `.venv`, `ayarlar.json`,
  günlükler ayrıca dışlanır (payload'da zaten yoklar; ikinci kat koruma).
- Damga en son yazılır; eşitleme yarıda kalırsa sonraki açılışta yeniden denenir.
- Sonra `SESVER_HOME`'da `macos_ortak.sh` → `sesver_baslat` (Python kurulumu dahil, ZIP
  moduyla aynı mantık). Günlük: `SESVER_HOME/sesver_baslatici_log.txt`.
- `SESVER_HOME` ortam değişkeni verilirse o kullanılır (test:
  `open --env SESVER_HOME=… --env GRADIO_SERVER_PORT=7881 SesVer.app`).

Her iki modda ortak kurallar:
- **Pencere dili:** başlatıcı pencereleri (`sesver_app_launcher.c`, `sesver_app.sh`,
  `macos_ortak.sh`) sistem dili (AppleLanguages ilk öğesi) `tr` ile başlıyorsa Türkçe,
  değilse İngilizcedir; terminal/günlük satırları Türkçe kalır. Arayüz (`desktop.py`) ilk
  açılışta sistem dilinde açılır, desteklenmeyen dilde İngilizce; `ayarlar.json`'daki
  tercih her zaman önce gelir. `SESVER_SISTEM_DILI=en-US` sistem dilini taklit eder
  (**yalnız test**; normal kullanımda ayarlanmaz).
- **Intel Mac:** `uname -m` = `x86_64` ve Rosetta altında değilse
  (`sysctl.proc_translated` ≠ 1) ve tamamlanmış bir kurulum yoksa, kurulumdan önce
  "Apple Silicon gerektirir" penceresi gösterilip çıkılır; hiçbir şey indirilmez (PyTorch
  ≥ 2.5'in macOS tekerleği yalnız arm64). Rosetta altında arm64 Python indirilir.
  Testler: `tests/test_macos_baslatici.py`.

### Neden DMG modu? (App Translocation kanıtı)

Karantinalı (`com.apple.quarantine`, internetten indirilmiş) ve kullanıcının onayladığı bir
`SesVer.app` açıldığında macOS onu salt-okunur geçici bir kopyadan çalıştırdı:
`/private/var/folders/…/AppTranslocation/<UUID>/d/SesVer.app`. `../../..` artık proje klasörü
olmadığı için `desktop.py` bulunamadı. Translocation notarize edilmiş uygulamalara da uygulanır
(Finder ile taşınmadıkça). Bu yüzden "uygulama proje klasörünün içinde durur" tasarımı karantinalı
dağıtımda kırılır. DMG modunda paket kendi kendine yeterlidir: translocation zararsızdır,
`/Applications` yazılabilir olmak zorunda değildir, imzalı paket hiç değiştirilmez ve
Masaüstü/İndirilenler TCC izni sorulmaz.

ZIP modu (imzasız dönem) için iki önlem:
- `sesver_app.sh`: yol `/AppTranslocation/` içeriyorsa genel "klasörün içinde durmalı" yerine
  Türkçe yönlendirici mesaj (ilk açılışı `MACOS_BASLAT.command` ile yapın).
- `MACOS_BASLAT.command`: onaylanıp çalıştığında YALNIZ kendi klasöründeki karantina işaretini
  temizler (`xattr -dr com.apple.quarantine "$PWD"`, yalnız işaret varsa). Sonraki açılışlarda
  `SesVer.app` translocate edilmeden açılır. (`curl` ile indirilen `python-embed/` karantina
  taşımaz.)

## 2. Tek komut

```
macos/release_mac.sh <sürüm> [--dry-run]      # ör. macos/release_mac.sh 1.2.0 --dry-run
```

Adımlar: önkoşullar (xcrun, notarytool, stapler, hdiutil, clang …; git kirliyse uyarı) →
kimlik seçimi → payload (`git archive HEAD` + izin listesi) → `dist/SesVer.app` (universal
başlatıcı, Info.plist sürümü argümandan, icns, `sesver_app.sh`, payload) → tüm Mach-O'ları içten
dışa `codesign --force --options runtime --timestamp` → paketi `--entitlements
macos/SesVer.entitlements` ile imzala → (gerçek modda app notarize + staple) → DMG
(`hdiutil create … -format UDZO`, `SesVer.app` + `Applications` kısayolu) → DMG imzası →
(gerçek modda DMG notarize + staple) → doğrulama → boyut + SHA256.

Kimlik seçimi:
- Anahtarlıkta `Developer ID Application:` varsa → gerçek mod (`--dry-run` ile: Developer ID
  imzası, notarize yok).
- Yoksa ve `--dry-run` → `Apple Development:` (o da yoksa ad-hoc, timestamp'siz).
- Yoksa ve `--dry-run` değil → **KAPI** mesajı, çıkış kodu **2**; hiçbir şey derlenmez,
  `notarytool` çağrılmaz.

Notarize keychain profili: `${SESVER_NOTARY_PROFILE:-sesver-notary}`. Notarize başarısızsa
`notarytool log <id>` basılır ve betik durur.

Payload izin listesi (başka hiçbir şey girmez): kökteki `*.py`, `requirements.txt`,
`voice_design_map.json`, `macos_ortak.sh`, `locales/*.json`, `voices/hazir/**`, `LICENSE`,
`README.md`, `AI_KURULUM.md` + `.sesver_payload_version` (`<sürüm> (<git sha>)`).
`voices/seslerim/` HEAD'de görülürse yapı HATA ile durur; payload ayrıca `voices/seslerim`,
`__pycache__`, `.venv`, `python-embed*`, `outputs`, `ayarlar.json*`, `*.pyc`, günlükler,
`.DS_Store` ve kişi adı içeren dosyalar için taranır.

Çıktılar `dist/` altındadır (gitignore'da).

## 3. KAPI: Developer ID ve notarize kimlik bilgisi (bir kez, Yusuf kendisi)

1. Xcode → Settings → Accounts → Apple ID'yi seçin (Team: Muhammed Yusuf Hamarat) →
   Manage Certificates… → sol alttaki **+** → **Developer ID Application**.
   (Ücretli Apple Developer Program üyeliği ve Account Holder rolü gerekir.)
2. Team ID: Xcode → Settings → Accounts'ta takımın yanında görünür. Tahmin etmeyin: sertifika
   adındaki `G74FR6X39U` kişisel kimliktir; mevcut Apple Development sertifikasının OU (takım)
   alanı `28TVDBBT3G` olarak okundu — Developer ID aynı takımda olmalı, yine de Xcode'da
   doğrulayın. Betik gerçek modda Team ID'yi Developer ID sertifikasının OU alanından okur ve
   basar; imzadan sonra `codesign -dv` `TeamIdentifier` satırında da görünür.
3. appleid.apple.com → Giriş ve Güvenlik → Uygulamaya özel parolalar → yeni parola.
4. Terminal (parolayı komut isteyince kendiniz girin):
   `xcrun notarytool store-credentials sesver-notary --apple-id <apple-id> --team-id <TEAM_ID>`
5. `macos/release_mac.sh <sürüm>`

Ajanlar `store-credentials` çalıştırmaz, parola görmez/girmez.

## 4. Doğrulama listesi

Betik her modda basar; elle tekrar için:

```
codesign --verify --deep --strict --verbose=2 dist/SesVer.app     # valid on disk + satisfies its DR
codesign -dv --verbose=4 dist/SesVer.app                          # Authority, TeamIdentifier, flags=0x10000(runtime), Timestamp
codesign -d --entitlements - --xml dist/SesVer.app                # boş <dict/>
hdiutil verify dist/SesVer-<sürüm>-macOS.dmg                      # checksum VALID
codesign --verify --strict --verbose=2 dist/SesVer-<sürüm>-macOS.dmg
hdiutil attach -nobrowse -readonly dist/SesVer-<sürüm>-macOS.dmg  # içindeki app: codesign --verify --deep --strict; sonra hdiutil detach
spctl -a -vv dist/SesVer.app                                      # gerçek: accepted, source=Notarized Developer ID
spctl -a -t open --context context:primary-signature -vv dist/SesVer-<sürüm>-macOS.dmg
xcrun stapler validate dist/SesVer.app                            # yalnız gerçek mod
xcrun stapler validate dist/SesVer-<sürüm>-macOS.dmg              # yalnız gerçek mod
find dist/SesVer.app/Contents/Resources/payload -path '*seslerim*'   # boş olmalı
```

Kuru modda `spctl` → `rejected` **beklenir** (Developer ID + notarize yok).
Not: `hdiutil create/attach/detach` macOS 27'de "deprecated" uyarısı basar; komutlar çalışır.
`diskutil image …` karşılığına geçiş ayrı iştir.

Uçtan uca DMG modu testi (geliştirici makinesi): `dist/SesVer.app`'i scratch'e `ditto` ile
kopyalayın, `SESVER_HOME` için boş bir klasör hazırlayıp içine tamamlanmış bir `.venv`'i APFS
klonuyla koyun (`cp -cR <repo>/.venv <home>/.venv`; `sesver_kurulum_tamam.txt` içinde olmalı),
`open --env SESVER_HOME=<home> --env GRADIO_SERVER_PORT=7881 <app>` → `curl -I
http://127.0.0.1:7881/` 200.

## 5. Entitlement gerekçeleri (`macos/SesVer.entitlements`)

Dosya **bilerek boştur** (`<dict/>`): hardened runtime (`--options runtime`) açık, hiçbir istisna
istenmez.

| Anahtar | Durum | Neden |
|---|---|---|
| `com.apple.security.cs.allow-jit` | yok | Başlatıcı düz C; JIT/çalışma anında kod üretimi yok. |
| `com.apple.security.cs.allow-unsigned-executable-memory` | yok | Aynı neden. |
| `com.apple.security.cs.disable-library-validation` | yok | Başlatıcı yalnız libSystem'e bağlı; üçüncü taraf dylib yüklemez. |
| `com.apple.security.cs.allow-dyld-environment-variables` | yok | DYLD_* kullanılmaz. |
| `com.apple.security.device.audio-input` | yok | Mikrofon kullanılmaz (yalnız dosya yükleme, `app.py` `sources=["upload"]`). |
| `com.apple.security.app-sandbox` | yok | Developer ID dağıtımında zorunlu değil; Python ortamı Application Support'a kurulur ve ağdan paket indirir. |

Python (`python-embed` / `.venv`) başlatıcının `/bin/bash` alt süreci üzerinden **ayrı süreç**
olarak çalışır; hardened runtime kısıtları alt süreçlere geçmez. Bir anahtar eklenecekse gerçek
hata çıktısıyla gerekçelendirip bu tabloya yazın.

## 6. Kullanıcı talimatı taslağı (Releases sayfası)

> **macOS kurulumu**
> 1. `SesVer-<sürüm>-macOS.dmg` dosyasını indirip açın.
> 2. Açılan pencerede **SesVer**'i **Uygulamalar** (Applications) klasörüne sürükleyin.
> 3. Uygulamalar'dan **SesVer**'i açın.
>
> İlk açılışta SesVer kendi Python ortamını (~0,4 GB indirme, diskte ~1,7 GB) kurar;
> ses modeli (~5 GB) ilk **Üret**'te bir kere indirilir. Toplam indirme ~5,4 GB, diskte ~7 GB;
> en az 20 GB boş alan önerilir. Süre internet hızına bağlıdır: hızlı bağlantıda ölçülen
> ~2 dk (kurulum) + ~2 dk (model); 50 Mbit/sn'de toplam ~15 dk, 25 Mbit/sn'de ~30 dk (hesap).
> Sonraki açılışlar hızlıdır.
> Sesleriniz ve üretilen dosyalar `~/Library/Application Support/SesVer` klasöründe tutulur;
> yeni sürüme geçmek için yeni DMG'deki SesVer'i aynı şekilde Uygulamalar'a sürükleyip
> eskisinin üzerine yazmanız yeterlidir — sesleriniz korunur.

## 7. Kaldırma

1. Uygulamalar'daki `SesVer`'i Çöp Sepeti'ne taşıyın.
2. Tamamen kaldırmak için `~/Library/Application Support/SesVer` klasörünü silin
   (Finder → Git → Klasöre Git…). **Dikkat:** kaydettiğiniz sesler (`voices/seslerim`) ve
   üretilen dosyalar (`outputs`) bu klasördedir; önce yedekleyin.
3. İndirilen ses modeli Hugging Face önbelleğindedir (`~/.cache/huggingface`); başka uygulama
   kullanmıyorsa ilgili klasör silinebilir.
