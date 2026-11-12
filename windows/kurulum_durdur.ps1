# SesVer ilk kurulum surec agacini durdurur: kurulum sihirbazindaki "Kurulumu durdur"
# (windows\SesVer.iss OrtamSureciniDurdur) ve CI iptal testi bu betigi ayni sekilde calistirir.
#
# Neden taskkill /T /F yetmiyor: taskkill agacin anlik listesini alir, once cocuklari, en son
# koku (WINDOWS_BASLAT.bat'i calistiran cmd.exe) sonlandirir. Kok o arada canlidir; bat'in o anki
# kisa omurlu python'u (pip --version, surum okuma) biterse cmd hemen sonrakini (ensurepip /
# pip install) baslatir. Yeni surec listede olmadigi icin yetim kalir ve python-embed'e kurmaya
# devam eder (CI 43265425949: "PID 8252 ... could not be terminated ... not supported", 3 sn
# sonra SesVer klasorunden python kalmisti).
#
# Burada:
# (1) Kok dogrulanir (D1): ad cmd.exe ve komut satiri WINDOWS_BASLAT.bat /yalniz-kurulum olmali.
#     PID baska bir surece gecmisse o surece ve alt sureclerine dokunulmaz.
# (2) Dogrulanan kok ONCE durdurulur, yeni alt surec dogamaz.
# (3) Kokun torunlari ust surec numarasi + olusma zamaniyla tekrar tekrar bulunup durdurulur.
#     Ust surec su an canliysa olusma zamani kayittakiyle AYNI olmali (D2: PID yeniden kullanimi).
# (4) Guvenlik agi: kurulum basladiktan sonra SesVer'in python-embed klasorunden baslamis her
#     surec durdurulur. Kurulum baslangici = dogrulanan kokun olusma zamani; kok yoksa ya da
#     dogrulanamadiysa bat'in kurulum basinda yazdigi kurulum_pid.txt'nin yazilma zamani (D3: kok
#     kendiliginden olmus, python yetim kalmis). Ikisi de yoksa tarama yapilmaz. Kurulumdan once
#     acilmis SesVer (olusma zamani esikten once) ve baska uygulamalar hic durdurulmaz.
# (5) Ard arda bos turlar gorulene dek yeniden denenir, sonra son denetim.
#
# Cikis: 0 = dogrulanan kok ve agaci bitti, kurulum sureci kalmadi; 1 = sure doldu, surec kaldi
# (listelenir); 2 = dogrulanan kok yok (yok ya da PID baska bir surecte); varsa yetim kurulum
# surecleri yine durduruldu ve hicbiri kalmadi. Cikti ASCII (sihirbaz gunlugu, CI).
param(
    [int]$Kok = 0,
    [Parameter(Mandatory = $true)][string]$Klasor,
    [int]$SureSn = 20
)
$ErrorActionPreference = 'SilentlyContinue'
$embed = (Join-Path $Klasor 'python-embed').TrimEnd('\') + '\'
$pidDosyasi = Join-Path $Klasor 'kurulum_pid.txt'
$basla = Get-Date

function Surecler { @(Get-CimInstance Win32_Process) }

# D1: yalniz WINDOWS_BASLAT.bat'i yalniz-kurulum kipinde calistiran cmd.exe kok sayilir.
function KurulumKokuMu($p) {
    return ($p -and $p.Name -eq 'cmd.exe' -and $p.CommandLine -like '*WINDOWS_BASLAT.bat*/yalniz-kurulum*')
}

$tum = Surecler
if ($Kok -gt 0) {
    $aday = @($tum | Where-Object { [int]$_.ProcessId -eq $Kok })
    $kokler = @($aday | Where-Object { KurulumKokuMu $_ })
    if ($aday.Count -gt 0 -and $kokler.Count -eq 0) {
        Write-Output ("kurulum_durdur: PID {0} kurulum cmd.exe'si degil ({1}); ona ve alt sureclerine dokunulmaz" -f $Kok, $aday[0].Name)
    }
} else {
    # kurulum_pid.txt yazilamadiysa: yalniz-kurulum cmd.exe'leri komut satirindan bulunur.
    $kokler = @($tum | Where-Object { KurulumKokuMu $_ })
}

# PID -> olusma zamani. Cocuk ancak ust surecinden sonra olusmussa agaca katilir.
$agac = @{}
foreach ($k in $kokler) { $agac[[int]$k.ProcessId] = $k.CreationDate }

$esik = $null
if ($kokler.Count -gt 0) {
    $esik = ($kokler | Sort-Object CreationDate | Select-Object -First 1).CreationDate
} else {
    Write-Output "kurulum_durdur: dogrulanan kok surec yok (PID $Kok)"
    # D3: kurulum baslangici, bat'in ilk is olarak yazdigi kurulum_pid.txt'den (sihirbaz her
    # kurulumdan once siler; dosya bir kez yazilir, LastWriteTime degismez). Yoksa tarama yok.
    $pd = Get-Item -LiteralPath $pidDosyasi
    if ($pd) { $esik = $pd.LastWriteTime }
    if ($null -eq $esik) {
        Write-Output "kurulum_durdur: kurulum baslangici bilinmiyor (kurulum_pid.txt yok); python-embed taramasi yapilmaz"
        exit 2
    }
    Write-Output ("kurulum_durdur: python-embed taramasi, kurulum baslangici {0:HH:mm:ss.fff} sonrasi" -f $esik)
}

function Kaynak($p) {
    $id = [int]$p.ProcessId
    if ($agac.ContainsKey($id) -and $agac[$id] -eq $p.CreationDate) { return 'agac' }
    if ($null -ne $esik -and $p.ExecutablePath -and $p.ExecutablePath.StartsWith($embed, [StringComparison]::OrdinalIgnoreCase) -and $p.CreationDate -ge $esik) { return 'klasor' }
    return $null
}

# Dogrulanan kok once: yeni alt surec baslatamasin.
foreach ($k in $kokler) {
    Stop-Process -Id ([int]$k.ProcessId) -Force
    Write-Output ("kurulum_durdur: kok durduruldu PID {0} {1}" -f $k.ProcessId, $k.Name)
}

$bitis = $basla.AddSeconds($SureSn)
$bosTur = 0
$kalan = @()
while ($true) {
    $tum = Surecler
    $canli = @{}
    foreach ($p in $tum) { $canli[[int]$p.ProcessId] = $p }
    # Agaca yeni katilanlar (torunlar dahil; ust sureci olmus olsa da numarasi kalir).
    do {
        $eklendi = $false
        foreach ($p in $tum) {
            $id = [int]$p.ProcessId; $ust = [int]$p.ParentProcessId
            if ($agac.ContainsKey($id) -or -not $agac.ContainsKey($ust)) { continue }
            if ($p.CreationDate -lt $agac[$ust]) { continue }
            # D2: ust PID su an canli ama baska bir surec (olusma zamani kayittakiyle ayni degil).
            if ($canli.ContainsKey($ust) -and $canli[$ust].CreationDate -ne $agac[$ust]) { continue }
            $agac[$id] = $p.CreationDate; $eklendi = $true
        }
    } while ($eklendi)
    $kalan = @($tum | Where-Object { Kaynak $_ })
    if ($kalan.Count -eq 0) {
        $bosTur++
        if ($bosTur -ge 3) { break }   # ~1 sn boyunca yeni surec dogmadi
    } else {
        $bosTur = 0
        foreach ($p in $kalan) {
            Stop-Process -Id ([int]$p.ProcessId) -Force
            $yas = [int](($p.CreationDate - $basla).TotalMilliseconds)
            Write-Output ("kurulum_durdur: durduruldu PID {0} {1} ust {2} ({3}; olusma, durdurma baslangicina gore {4} ms)" -f $p.ProcessId, $p.Name, $p.ParentProcessId, (Kaynak $p), $yas)
        }
    }
    if ((Get-Date) -ge $bitis) { break }
    Start-Sleep -Milliseconds 300
}

# Son denetim (sure dolduysa az once durdurulanlar listede kalmis olabilir: yarim saniye bekle).
if ($bosTur -lt 3) { Start-Sleep -Milliseconds 500 }
$kalan = @(Surecler | Where-Object { Kaynak $_ })
if ($kalan.Count -gt 0) {
    foreach ($p in $kalan) {
        Write-Output ("kurulum_durdur: KALDI PID {0} {1} ust {2}: {3}" -f $p.ProcessId, $p.Name, $p.ParentProcessId, $p.CommandLine)
    }
    exit 1
}
if ($kokler.Count -eq 0) {
    Write-Output ("kurulum_durdur: kok yoktu; kurulum sureci kalmadi; {0:N1} sn" -f ((Get-Date) - $basla).TotalSeconds)
    exit 2
}
Write-Output ("kurulum_durdur: tamam, {0} surec agacta; {1:N1} sn" -f $agac.Count, ((Get-Date) - $basla).TotalSeconds)
exit 0
