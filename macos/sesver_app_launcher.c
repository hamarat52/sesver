/*
 * SesVer.app/Contents/MacOS/SesVer — küçük yerel (Mach-O) başlatıcı.
 *
 * Neden bash betiği değil?
 *   Paketin çalıştırılabilir dosyası bir bash betiği olduğunda Finder/Dock'tan
 *   açılan süreç /bin/bash olur. macOS gizlilik koruması (TCC) Masaüstü/Belgeler/
 *   İndirilenler klasörlerine erişimi bu sürecin kendisine atfeder; /bin/bash bir
 *   Apple "platform ikilisi" olduğu için izin penceresi HİÇ gösterilmez ve okuma
 *   sessizce reddedilir (log: "Platform binary prompting is 'Deny'",
 *   "System Policy: bash deny file-read-data .../macos_ortak.sh"). Proje
 *   Masaüstü'ndeyken uygulama bu yüzden açılır açılmaz kapanıyordu.
 *
 *   Bu başlatıcı paketin "sorumlu süreci" olarak çalışır ve bash'i alt süreç olarak
 *   başlatıp bekler (exec ETMEZ; exec edilirse süreç yine /bin/bash olurdu). Alt
 *   süreçler (bash, python) sorumluluğu devralır; böylece TCC erişimi
 *   "SesVer" (com.hamaratlabs.sesver) adına sorar ve kullanıcının verdiği izni
 *   hatırlar.
 *
 * Akış:
 *   1) SESVER_APP_EXE = bu ikilinin tam yolu (macos_ortak.sh, python'u
 *      CFProcessPath=$SESVER_APP_EXE ile başlatıp Dock'ta SesVer görünmesini sağlar).
 *   2) Contents/Resources/sesver_app.sh okunabiliyor mu? (Uygulamanın kendi paketi
 *      TCC'den muaftır; bu denetim yalnız beklenmedik okuma hatalarını yakalar.)
 *      Okunamazsa açıklama penceresi gösterilip çıkılır (sessiz kapanma yok).
 *      Pencere dili: sistem dili (CFLocaleCopyPreferredLanguages ilk öğesi; yalnız
 *      test için SESVER_SISTEM_DILI) "tr" ile başlıyorsa Türkçe, değilse İngilizce.
 *   3) /bin/bash sesver_app.sh alt süreç olarak çalıştırılır, çıkış kodu aynen
 *      döndürülür; SIGTERM/SIGINT/SIGHUP alt sürece iletilir. İlk açılışta TCC
 *      izin penceresi ("SesVer, Masaüstü klasörünüzdeki dosyalara erişmek
 *      istiyor") bash proje kökündeki macos_ortak.sh'ı okurken çıkar; izin
 *      verilmezse sesver_app.sh yönlendirici bir hata penceresi gösterir.
 *
 * Derleme: macos/build_app_launcher.sh
 * Test derlemesi: -DSESVER_OSASCRIPT='"/yol/sahte_osascript"' pencere komutunu değiştirir
 * (yalnız test; dağıtılan ikili her zaman /usr/bin/osascript kullanır).
 */
#include <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SESVER_OSASCRIPT
#define SESVER_OSASCRIPT "/usr/bin/osascript"
#endif

extern char **environ;

static volatile pid_t g_child = 0;
static int g_turkish = 0;

static void forward_signal(int sig) {
    if (g_child > 0) kill(g_child, sig);
}

/* "tr", "tr-TR", "tr_TR" → 1; diğerleri 0. */
static int is_turkish_code(const char *code) {
    return code != NULL && strncasecmp(code, "tr", 2) == 0 &&
           (code[2] == '\0' || code[2] == '-' || code[2] == '_' || code[2] == '.');
}

static int system_is_turkish(void) {
    const char *env = getenv("SESVER_SISTEM_DILI");
    if (env != NULL && *env != '\0') return is_turkish_code(env);
    int tr = 0;
    CFArrayRef langs = CFLocaleCopyPreferredLanguages();
    if (langs != NULL) {
        if (CFArrayGetCount(langs) > 0) {
            CFStringRef first = (CFStringRef)CFArrayGetValueAtIndex(langs, 0);
            char buf[64];
            if (first != NULL && CFStringGetCString(first, buf, sizeof(buf), kCFStringEncodingUTF8)) {
                tr = is_turkish_code(buf);
            }
        }
        CFRelease(langs);
    }
    return tr;
}

/* Pencere diline göre metin seçer. */
#define TXT(tr_text, en_text) (g_turkish ? (tr_text) : (en_text))

static void show_dialog(const char *message) {
    /* Mesaj argüman olarak verilir; AppleScript koduna karışmaz. osascript'in kendi
     * "display dialog" komutu Otomasyon izni istemez. */
    char script[256];
    snprintf(script, sizeof(script),
             "display dialog (item 1 of argv) with title \"SesVer\" buttons {\"%s\"} "
             "default button 1 with icon stop",
             TXT("Tamam", "OK"));
    char *args[] = {
        SESVER_OSASCRIPT,
        "-e", "on run argv",
        "-e", script,
        "-e", "end run",
        (char *)message,
        NULL,
    };
    pid_t pid;
    if (posix_spawn(&pid, args[0], NULL, NULL, args, environ) == 0) {
        int st;
        while (waitpid(pid, &st, 0) < 0 && errno == EINTR) {
        }
    }
}

int main(void) {
    g_turkish = system_is_turkish();
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    char real_exe[PATH_MAX];
    if (_NSGetExecutablePath(exe, &size) != 0 || realpath(exe, real_exe) == NULL) {
        show_dialog(TXT("SesVer başlatıcısı kendi konumunu bulamadı.",
                        "The SesVer launcher could not find its own location."));
        return 1;
    }
    setenv("SESVER_APP_EXE", real_exe, 1);

    /* .../SesVer.app/Contents/MacOS/SesVer -> .../SesVer.app/Contents/Resources/sesver_app.sh */
    char script[PATH_MAX];
    strlcpy(script, real_exe, sizeof(script));
    char *slash = strrchr(script, '/');
    if (slash == NULL) return 1;
    *slash = '\0';
    if (strlcat(script, "/../Resources/sesver_app.sh", sizeof(script)) >= sizeof(script)) return 1;

    /* Gerçek bir okuma denemesi: access()/stat() TCC'yi tetiklemez, open() tetikler. */
    int fd = open(script, O_RDONLY);
    if (fd < 0) {
        int err = errno;
        char msg[2048];
        if (err == EPERM || err == EACCES) {
            snprintf(msg, sizeof(msg),
                     TXT("SesVer, bulunduğu klasördeki dosyaları okuma iznine sahip değil.\n\n"
                         "Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler > SesVer "
                         "altında ilgili klasörü (ör. Masaüstü Klasörü) açın ve SesVer'i tekrar başlatın.\n\n"
                         "Konum: %s",
                         "SesVer does not have permission to read the files in its folder.\n\n"
                         "In System Settings > Privacy & Security > Files and Folders > SesVer, "
                         "turn on the relevant folder (e.g. Desktop Folder) and start SesVer again.\n\n"
                         "Location: %s"),
                     script);
        } else {
            snprintf(msg, sizeof(msg),
                     TXT("SesVer başlatıcı betiği açılamadı (%s).\n\nKonum: %s",
                         "The SesVer launcher script could not be opened (%s).\n\nLocation: %s"),
                     strerror(err), script);
        }
        show_dialog(msg);
        return 1;
    }
    close(fd);

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = forward_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    /* LaunchServices'in verebileceği argümanlar (ör. -psn_...) bilerek iletilmez. */
    char *args[] = {"/bin/bash", script, NULL};
    pid_t pid;
    int rc = posix_spawn(&pid, args[0], NULL, NULL, args, environ);
    if (rc != 0) {
        char msg[512];
        snprintf(msg, sizeof(msg),
                 TXT("SesVer başlatılamadı: /bin/bash çalıştırılamadı (%s).",
                     "SesVer could not be started: /bin/bash could not be run (%s)."),
                 strerror(rc));
        show_dialog(msg);
        return 1;
    }
    g_child = pid;

    int status = 0;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) return 1;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}
