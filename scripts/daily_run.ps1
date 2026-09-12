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

    if ($cfg.source -eq 'news') {
        # Recherchekanal: Themen kommen aus der Websuche, nicht aus einer Liste.
        & $uv run --no-sync python news_to_shorts.py `
            --count $count `
            --topic $cfg.topic `
            --out $manifest `
            --sources-out (Join-Path $dir 'sources.json') `
            --model (Get-ConfigValue $cfg 'research_model' 'claude-sonnet-5')
        if ($LASTEXITCODE -ne 0) { Write-Warning "$name : Recherche fehlgeschlagen."; continue }
    }
    else {
        # Warteschlangenkanal: die naechsten Zeilen aus tasks.jsonl.
        $queue = Join-Path $dir 'tasks.jsonl'
        if (-not (Test-Path $queue)) { Write-Warning "$name : $queue fehlt."; continue }
        $lines = Get-Content $queue -Encoding UTF8 | Where-Object { $_.Trim() }
        if (-not $lines) { Write-Host "$name : Warteschlange leer."; continue }

        $take = @($lines | Select-Object -First $count)
        $tasks = @($take | ForEach-Object { $_ | ConvertFrom-Json })
        # Der Komma-Operator erzwingt ein Array; sonst serialisiert
        # ConvertTo-Json ein einzelnes Thema als Objekt und cli.py lehnt das
        # Manifest ab.
        Write-Utf8NoBom $manifest (,$tasks | ConvertTo-Json -Depth 10)
        # Erst nach dem Rendern aus der Warteschlange nehmen, damit ein
        # Abbruch keine Themen verschluckt.
        $rest = @($lines | Select-Object -Skip $take.Count)
    }

    Write-Step "$name : rendern"
    $output = @(& $uv run --no-sync python cli.py --batch-file $manifest 2>&1)
    $output | ForEach-Object { Write-Host $_ }
    $summary = Get-BatchSummary $output

    if (-not $summary) {
        Write-Warning "$name : keine JSON-Zusammenfassung erhalten, Upload uebersprungen."
        continue
    }
    Write-Host "$name : $($summary.succeeded) von $($summary.total) erfolgreich."

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
    & $uv @uploadArgs
}

Write-Step 'fertig'
