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
 *      Okunamazsa Türkçe açıklama penceresi gösterilip çıkılır (sessiz kapanma yok).
 *   3) /bin/bash sesver_app.sh alt süreç olarak çalıştırılır, çıkış kodu aynen
 *      döndürülür; SIGTERM/SIGINT/SIGHUP alt sürece iletilir. İlk açılışta TCC
 *      izin penceresi ("SesVer, Masaüstü klasörünüzdeki dosyalara erişmek
 *      istiyor") bash proje kökündeki macos_ortak.sh'ı okurken çıkar; izin
 *      verilmezse sesver_app.sh yönlendirici bir hata penceresi gösterir.
 *
 * Derleme: macos/build_app_launcher.sh
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static volatile pid_t g_child = 0;

static void forward_signal(int sig) {
    if (g_child > 0) kill(g_child, sig);
}

static void show_dialog(const char *message) {
    /* Mesaj argüman olarak verilir; AppleScript koduna karışmaz. osascript'in kendi
     * "display dialog" komutu Otomasyon izni istemez. */
    char *args[] = {
        "/usr/bin/osascript",
        "-e", "on run argv",
        "-e", "display dialog (item 1 of argv) with title \"SesVer\" buttons {\"Tamam\"} "
              "default button 1 with icon stop",
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
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    char real_exe[PATH_MAX];
    if (_NSGetExecutablePath(exe, &size) != 0 || realpath(exe, real_exe) == NULL) {
        show_dialog("SesVer başlatıcısı kendi konumunu bulamadı.");
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
                     "SesVer, bulunduğu klasördeki dosyaları okuma iznine sahip değil.\n\n"
                     "Sistem Ayarları > Gizlilik ve Güvenlik > Dosyalar ve Klasörler > SesVer "
                     "altında ilgili klasörü (ör. Masaüstü Klasörü) açın ve SesVer'i tekrar başlatın.\n\n"
                     "Konum: %s",
                     script);
        } else {
            snprintf(msg, sizeof(msg), "SesVer başlatıcı betiği açılamadı (%s).\n\nKonum: %s",
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
        snprintf(msg, sizeof(msg), "SesVer başlatılamadı: /bin/bash çalıştırılamadı (%s).", strerror(rc));
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
