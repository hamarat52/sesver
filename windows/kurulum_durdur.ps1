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
# Burada: (1) kok ONCE durdurulur, yeni alt surec dogamaz; (2) kokun torunlari ust surec
# numarasi + olusma zamaniyla (PID yeniden kullanimina karsi) tekrar tekrar bulunup durdurulur;
# (3) guvenlik agi: kok basladiktan sonra SesVer'in python-embed klasorunden baslamis her surec
# (ust sureci agacin disinda kalsa bile) durdurulur; (4) ard arda bos turlar gorulene dek
# yeniden denenir. Kurulumdan once acilmis SesVer (eski python-embed surecleri) olusma zamani
# kokten once oldugu icin dokunulmaz.
#
# Cikis: 0 = agac ve kurulum surecleri bitti; 1 = sure doldu, surec kaldi (listelenir);
# 2 = kok bulunamadi (calisan kurulum yok). Cikti ASCII (sihirbaz gunlugu, CI).
param(
    [int]$Kok = 0,
    [Parameter(Mandatory = $true)][string]$Klasor,
    [int]$SureSn = 20
)
$ErrorActionPreference = 'SilentlyContinue'
$embed = (Join-Path $Klasor 'python-embed').TrimEnd('\') + '\'
$basla = Get-Date

function Surecler { @(Get-CimInstance Win32_Process) }

$tum = Surecler
$kokler = @()
if ($Kok -gt 0) {
    $kokler = @($tum | Where-Object { [int]$_.ProcessId -eq $Kok })
} else {
    # kurulum_pid.txt yazilamadiysa: yalniz-kurulum cmd.exe'leri komut satirindan bulunur.
    $kokler = @($tum | Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*WINDOWS_BASLAT.bat*/yalniz-kurulum*' })
}
if ($kokler.Count -eq 0) {
    Write-Output "kurulum_durdur: kok surec yok (PID $Kok); calisan ilk kurulum bulunamadi"
    exit 2
}

# PID -> olusma zamani. Cocuk ancak ust surecinden sonra olusmussa agaca katilir.
$agac = @{}
foreach ($k in $kokler) { $agac[[int]$k.ProcessId] = $k.CreationDate }
$esik = ($kokler | Sort-Object CreationDate | Select-Object -First 1).CreationDate

function Kaynak($p) {
    $id = [int]$p.ProcessId
    if ($agac.ContainsKey($id) -and $agac[$id] -eq $p.CreationDate) { return 'agac' }
    if ($p.ExecutablePath -and $p.ExecutablePath.StartsWith($embed, [StringComparison]::OrdinalIgnoreCase) -and $p.CreationDate -ge $esik) { return 'klasor' }
    return $null
}

# (1) Kok once: yeni alt surec baslatamasin.
foreach ($k in $kokler) {
    Stop-Process -Id ([int]$k.ProcessId) -Force
    Write-Output ("kurulum_durdur: kok durduruldu PID {0} {1}" -f $k.ProcessId, $k.Name)
}

$bitis = $basla.AddSeconds($SureSn)
$bosTur = 0
$kalan = @()
while ($true) {
    $tum = Surecler
    # (2) Agaca yeni katilanlar (torunlar dahil; ust sureci olmus olsa da numarasi kalir).
    do {
        $eklendi = $false
        foreach ($p in $tum) {
            $id = [int]$p.ProcessId; $ust = [int]$p.ParentProcessId
            if (-not $agac.ContainsKey($id) -and $agac.ContainsKey($ust) -and $p.CreationDate -ge $agac[$ust]) {
                $agac[$id] = $p.CreationDate; $eklendi = $true
            }
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
Write-Output ("kurulum_durdur: tamam, {0} surec agacta; {1:N1} sn" -f $agac.Count, ((Get-Date) - $basla).TotalSeconds)
exit 0
