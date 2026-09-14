<#
.SYNOPSIS
Taeglicher Lauf fuer einen oder mehrere YouTube-Kanaele unter Windows.

.DESCRIPTION
Das Gegenstueck zu daily_run.sh. Jeder Kanal hat ein eigenes Verzeichnis unter
channels/<name>/ mit channel.json (Einstellungen) und je nach Quelle einer
Themen-Warteschlange. Pro Kanal wird gerendert und anschliessend in genau
diesen Kanal hochgeladen.

Bewusst ohne --scan: der Scan sieht alle Videos unter storage/tasks und wuerde
bei mehreren Kanaelen die Videos des einen im anderen veroeffentlichen. Statt-
dessen werden die Task-IDs aus der JSON-Zusammenfassung von cli.py gelesen und
die zugehoerigen Dateien ausdruecklich uebergeben.

.EXAMPLE
  .\scripts\daily_run.ps1
  .\scripts\daily_run.ps1 -Channel tech -DryRun
#>
[CmdletBinding()]
param(
    # Nur diese Kanaele verarbeiten. Ohne Angabe alle unter channels/.
    [string[]]$Channel,
    # Rendern, aber nicht hochladen.
    [switch]$DryRun,
    # Ueberschreibt topics_per_run aus der channel.json.
    [int]$TopicsPerRun = 0
)

$ErrorActionPreference = 'Stop'

# Die aufgerufenen Python-Skripte schreiben UTF-8. PowerShell liest die
# Ausgabe sonst in der OEM-Codepage der Konsole (auf deutschen Systemen
# cp850) und macht aus "fuer" ein "f?r" — mitten in der Beschreibung, die
# man vor dem Upload pruefen soll.
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

# Und die Gegenseite: ohne das schreibt Python weiter in der Codepage des
# Systems, waehrend PowerShell oben schon UTF-8 erwartet — aus "verschaerft"
# wird dann "versch?rft". Die Variable gilt fuer jeden Python-Aufruf dieses
# Laufs, also auch fuer cli.py und news_to_shorts.py.
$env:PYTHONIOENCODING = 'utf-8'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$uv = if ($env:UV_BIN) { $env:UV_BIN } else { "$env:USERPROFILE\.local\bin\uv.exe" }
if (-not (Test-Path $uv)) {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $found) { throw "uv nicht gefunden. UV_BIN setzen oder uv installieren." }
    $uv = $found.Source
}

function Write-Step($text) {
    Write-Host "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm') $text ===" -ForegroundColor Cyan
}

function Write-RunLog {
    <#
    .SYNOPSIS
    Schreibt einen Schritt des Laufs nach storage/logs/daily-run.jsonl.

    .DESCRIPTION
    Der geplante Lauf laeuft in einem eigenen Prozess; die Aufgabenliste der
    WebUI sieht ihn nicht. Ohne dieses Protokoll bliebe unsichtbar, wo die
    Erzeugung steht oder woran sie gescheitert ist.

    Eine Zeile je Ereignis, damit ein Abbruch mitten im Schreiben hoechstens
    die letzte Zeile beschaedigt und nicht die ganze Datei.
    #>
    param(
        [Parameter(Mandatory)][string]$Channel,
        [Parameter(Mandatory)][string]$Step,
        [string]$Message = '',
        [bool]$Ok = $true
    )

    try {
        $logFile = Join-Path (Join-Path 'storage' 'logs') 'daily-run.jsonl'
        $logDir = Split-Path -Parent $logFile
        if (-not (Test-Path $logDir)) {
            New-Item -ItemType Directory -Force $logDir | Out-Null
        }
        $entry = [ordered]@{
            time    = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            channel = $Channel
            step    = $Step
            message = $Message
            ok      = $Ok
        }
        $line = ($entry | ConvertTo-Json -Compress -Depth 4)
        $full = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $logFile))
        [System.IO.File]::AppendAllText(
            $full, $line + "`n", (New-Object System.Text.UTF8Encoding $false))
    }
    catch {
        # Das Protokoll darf den Lauf nie stoppen: es beschreibt ihn nur.
        Write-Warning "Protokoll nicht schreibbar: $($_.Exception.Message)"
    }
}

function Invoke-Native {
    <#
    .SYNOPSIS
    Ruft ein externes Programm auf und liefert Ausgabe und Rueckgabewert.

    .DESCRIPTION
    Mit $ErrorActionPreference = 'Stop' bricht PowerShell ab, sobald ein
    externes Programm nach stderr schreibt und die Ausgabe mit 2>&1
    eingesammelt wird: die stderr-Zeilen werden zu ErrorRecord-Objekten und
    gelten als Fehler. Die Python-Werkzeuge hier loggen ihren normalen
    Fortschritt nach stderr, der Lauf waere also an einer harmlosen
    Statusmeldung gestorben.

    Deshalb wird die Einstellung fuer den Aufruf zurueckgenommen, jede Zeile
    sofort in Text verwandelt, und der Erfolg allein am Rueckgabewert
    gemessen.
    #>
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @()
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $Exe @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    $lines | ForEach-Object { Write-Host $_ }
    return [pscustomobject]@{ ExitCode = $code; Lines = $lines }
}

# Set-Content -Encoding UTF8 schreibt unter Windows PowerShell 5.1 ein BOM.
# Pythons json.load stolpert darueber, deshalb hier ohne BOM schreiben.
function Write-Utf8NoBom($path, $text) {
    $full = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $path))
    [System.IO.File]::WriteAllText($full, $text, (New-Object System.Text.UTF8Encoding $false))
}

function Get-ConfigValue($config, $key, $fallback) {
    $value = $config.PSObject.Properties[$key]
    if ($null -eq $value -or -not "$($value.Value)".Trim()) { return $fallback }
    return $value.Value
}

# cli.py schreibt Fortschrittsmeldungen und die JSON-Zusammenfassung beide auf
# stdout; die Zusammenfassung ist die letzte nicht leere Zeile.
function Get-BatchSummary($outputLines) {
    for ($i = $outputLines.Count - 1; $i -ge 0; $i--) {
        $line = "$($outputLines[$i])".Trim()
        if ($line.StartsWith('{')) {
            try { return $line | ConvertFrom-Json } catch { return $null }
        }
    }
    return $null
}

function Get-ChannelNames {
    if ($Channel) { return $Channel }
    if (-not (Test-Path 'channels')) { return @() }
    return Get-ChildItem 'channels' -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName 'channel.json') } |
        Select-Object -ExpandProperty Name
}

$names = Get-ChannelNames
if (-not $names) {
    throw "Keine Kanaele gefunden. channels/<name>/channel.json anlegen (Vorlage: channels/beispiel/)."
}

foreach ($name in $names) {
    $dir = Join-Path 'channels' $name
    $configPath = Join-Path $dir 'channel.json'
    if (-not (Test-Path $configPath)) {
        Write-Warning "$name : channel.json fehlt, uebersprungen."
        continue
    }
    $cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

    $count = if ($TopicsPerRun -gt 0) { $TopicsPerRun }
             elseif ($cfg.topics_per_run) { [int]$cfg.topics_per_run }
             else { 3 }
    $manifest = Join-Path $dir 'run.json'

    Write-Step "$name : $count Video(s) vorbereiten"
    Write-RunLog -Channel $name -Step 'research' -Message "Lauf gestartet, $count Video(s) geplant"

    if ($cfg.source -eq 'news') {
        # Recherchekanal: Themen kommen aus der Websuche, nicht aus einer Liste.
        $research = Invoke-Native $uv @(
            'run', '--no-sync', 'python', 'news_to_shorts.py',
            '--count', "$count",
            '--topic', "$($cfg.topic)",
            '--channel', $name,
            '--out', $manifest,
            '--sources-out', (Join-Path $dir 'sources.json'),
            '--model', (Get-ConfigValue $cfg 'research_model' 'claude-sonnet-5')
        )
        if ($research.ExitCode -ne 0) {
            Write-Warning "$name : Recherche fehlgeschlagen."
            Write-RunLog -Channel $name -Step 'research' -Ok $false `
                -Message "Recherche fehlgeschlagen (Rueckgabewert $($research.ExitCode))"
            continue
        }
        Write-RunLog -Channel $name -Step 'research' -Message "$count Meldung(en) recherchiert"
    }
    else {
        # Warteschlangenkanal: die naechsten Zeilen aus tasks.jsonl.
        $queue = Join-Path $dir 'tasks.jsonl'
        if (-not (Test-Path $queue)) { Write-Warning "$name : $queue fehlt."; continue }
        $lines = Get-Content $queue -Encoding UTF8 | Where-Object { $_.Trim() }
        if (-not $lines) { Write-Host "$name : Warteschlange leer."; continue }

        $take = @($lines | Select-Object -First $count)
        $tasks = @($take | ForEach-Object { $_ | ConvertFrom-Json })
        # Aussehen und Stimme stehen in der channel.json, damit beide
        # Themenquellen dasselbe Format ergeben. Ein Recherchekanal holt sie
        # ueber news_to_shorts.py --channel; hier werden sie auf die Eintraege
        # der Warteschlange gelegt.
        foreach ($task in $tasks) {
            foreach ($field in @('voice_name', 'voice_rate', 'video_clip_duration',
                                 'video_clip_speed', 'video_transition_mode',
                                 'subtitle_position', 'subtitle_display_mode',
                                 'subtitle_animation', 'font_name', 'font_size',
                                 'stroke_width', 'text_fore_color',
                                 'text_background_color', 'bgm_volume')) {
                if ($cfg.PSObject.Properties[$field]) {
                    $task | Add-Member -NotePropertyName $field `
                        -NotePropertyValue $cfg.$field -Force
                }
            }
        }
        # Der Komma-Operator erzwingt ein Array; sonst serialisiert
        # ConvertTo-Json ein einzelnes Thema als Objekt und cli.py lehnt das
        # Manifest ab.
        Write-Utf8NoBom $manifest (,$tasks | ConvertTo-Json -Depth 10)
        # Erst nach dem Rendern aus der Warteschlange nehmen, damit ein
        # Abbruch keine Themen verschluckt.
        $rest = @($lines | Select-Object -Skip $take.Count)
    }

    Write-Step "$name : rendern"
    $render = Invoke-Native $uv @('run', '--no-sync', 'python', 'cli.py',
                                  '--batch-file', $manifest)
    $summary = Get-BatchSummary $render.Lines

    if (-not $summary) {
        Write-Warning "$name : keine JSON-Zusammenfassung erhalten, Upload uebersprungen."
        Write-RunLog -Channel $name -Step 'render' -Ok $false `
            -Message 'keine JSON-Zusammenfassung erhalten'
        continue
    }
    Write-Host "$name : $($summary.succeeded) von $($summary.total) erfolgreich."
    Write-RunLog -Channel $name -Step 'render' -Ok ($summary.failed -eq 0) `
        -Message "$($summary.succeeded) von $($summary.total) Video(s) erzeugt"

    if ($cfg.source -ne 'news' -and $null -ne $rest) {
        $donePath = Join-Path $dir 'tasks-done.jsonl'
        $done = @()
        if (Test-Path $donePath) {
            $done = @(Get-Content $donePath -Encoding UTF8 | Where-Object { $_.Trim() })
        }
        Write-Utf8NoBom $donePath (($done + $take) -join "`n")
        Write-Utf8NoBom (Join-Path $dir 'tasks.jsonl') ($rest -join "`n")
    }

    # Nur die Videos dieses Laufs hochladen, ausdruecklich benannt.
    $videos = @()
    foreach ($task in $summary.tasks) {
        if ($task.status -ne 'succeeded') { continue }
        $taskDir = Join-Path (Join-Path 'storage' 'tasks') $task.task_id
        if (-not (Test-Path $taskDir)) { continue }
        $videos += Get-ChildItem $taskDir -Filter 'final-*.mp4' |
            Select-Object -ExpandProperty FullName
    }
    if (-not $videos) { Write-Warning "$name : keine fertigen Videos."; continue }

    if ($DryRun) {
        Write-Step "$name : Probelauf, kein Upload"
        Write-RunLog -Channel $name -Step 'done' `
            -Message "Probelauf: $($videos.Count) Video(s) erzeugt, nicht hochgeladen"
        $videos | ForEach-Object { Write-Host "  $_" }
        continue
    }

    Write-Step "$name : hochladen"
    $uploadArgs = @('run', '--no-sync', 'python', 'scripts/youtube_upload.py')
    $uploadArgs += $videos
    $uploadArgs += @('--channel', $name)
    if ($cfg.category) { $uploadArgs += @('--category', "$($cfg.category)") }
    if ($cfg.publish_at) {
        # Geplante Videos bleiben bis zum Termin privat; YouTube schaltet sie
        # dann selbst frei, auch wenn dieser Rechner aus ist.
        $uploadArgs += @('--publish-at', $cfg.publish_at)
    }
    else {
        $privacy = if ($cfg.privacy) { $cfg.privacy } else { 'private' }
        $uploadArgs += @('--privacy', $privacy)
    }
    $upload = Invoke-Native $uv $uploadArgs
    if ($upload.ExitCode -ne 0) {
        Write-Warning "$name : Hochladen fehlgeschlagen (Rueckgabewert $($upload.ExitCode))."
        Write-RunLog -Channel $name -Step 'upload' -Ok $false `
            -Message "Hochladen fehlgeschlagen (Rueckgabewert $($upload.ExitCode))"
    }
    else {
        Write-RunLog -Channel $name -Step 'upload' `
            -Message "$($videos.Count) Video(s) hochgeladen"
    }
    Write-RunLog -Channel $name -Step 'done' -Message 'Lauf abgeschlossen'
}

Write-Step 'fertig'
