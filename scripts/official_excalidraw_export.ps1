<#
.SYNOPSIS
  Cartograph Official Excalidraw Exporter + Persistent Offline CDN Cache + Real PNG Visual Verifier (Windows).
  Zero Node.js/npm required; runs @excalidraw/mermaid-to-excalidraw@3.6.0 (elbow:true) +
  @excalidraw/excalidraw@0.18.1 (convertToExcalidrawElements + exportToBlob) in local headless Chrome/Edge.
  Caches all /npm/* assets locally under resources/cdn_cache/ so subsequent runs work 100% offline.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -Command "& 'official_excalidraw_export.ps1' -InputMmd @('a.mmd') -OutDir '.' -RenderDir './previews'"
  powershell -ExecutionPolicy Bypass -Command "& 'official_excalidraw_export.ps1' -RenderOnly -InputExcalidraw @('a.excalidraw') -RenderDir './previews' -FocusText '核心结论'"
#>
param(
  [string[]]$InputMmd = @(),
  [string[]]$InputExcalidraw = @(),
  [string]$OutputExcalidraw = "",
  [string]$OutDir = "",
  [string]$RenderDir = "",
  [switch]$RenderOnly,
  [string[]]$FocusText = @(),
  [int]$TimeoutSec = 120
)

$ErrorActionPreference = 'Stop'

$browserCandidates = @(
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
)
$browser = $browserCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { throw 'No local Chrome or Edge binary found.' }

$skillRoot = Split-Path -Parent $PSScriptRoot
$htmlPath = Join-Path $skillRoot 'resources\official_converter.html'
$cacheDir = Join-Path $skillRoot 'resources\cdn_cache'
if (-not (Test-Path $htmlPath)) { throw "Missing converter HTML: $htmlPath" }
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
if ($RenderDir) { New-Item -ItemType Directory -Force -Path $RenderDir | Out-Null }

$jobs = @()
if ($RenderOnly) {
  for ($i = 0; $i -lt $InputExcalidraw.Count; $i++) {
    $src = (Resolve-Path -LiteralPath $InputExcalidraw[$i]).Path
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($src)
    $focus = if ($i -lt $FocusText.Count) { $FocusText[$i] } else { "" }
    $jobs += @{ idx = $i; name = $stem; mmd = ""; out = $src; focus = $focus }
  }
  $mode = 'render'
} else {
  for ($i = 0; $i -lt $InputMmd.Count; $i++) {
    $src = (Resolve-Path -LiteralPath $InputMmd[$i]).Path
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($src)
    if ($OutputExcalidraw -and $InputMmd.Count -eq 1) {
      $dst = $OutputExcalidraw
    } elseif ($OutDir) {
      New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
      $dst = Join-Path $OutDir "$stem.excalidraw"
    } else {
      $dst = Join-Path (Split-Path -Parent $src) "$stem.excalidraw"
    }
    $focus = if ($i -lt $FocusText.Count) { $FocusText[$i] } else { "" }
    $jobs += @{ idx = $i; name = $stem; mmd = $src; out = $dst; focus = $focus }
  }
  $mode = if ($RenderDir) { 'export_and_render' } else { 'export' }
}

$sha = [System.Security.Cryptography.SHA256]::Create()
$wc = New-Object System.Net.WebClient
$wc.Headers.Add('User-Agent', 'Cartograph/2.0')

function Get-CachedNpmAsset([string]$urlPath) {
  $hashBytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($urlPath))
  $key = ([BitConverter]::ToString($hashBytes) -replace '-','').ToLower().Substring(0, 32)
  $binP = Join-Path $cacheDir "$key.bin"
  $metaP = Join-Path $cacheDir "$key.meta.json"
  if ((Test-Path $binP) -and (Test-Path $metaP)) {
    $meta = Get-Content -LiteralPath $metaP -Raw -Encoding UTF8 | ConvertFrom-Json
    return @{ bytes = [System.IO.File]::ReadAllBytes($binP); ctype = $meta.content_type; cached = $true }
  }
  $remote = "https://cdn.jsdelivr.net$urlPath"
  $req = [System.Net.HttpWebRequest]::Create($remote)
  $req.UserAgent = 'Cartograph/2.0'
  $req.Timeout = 30000
  $resp = $req.GetResponse()
  $ms = New-Object System.IO.MemoryStream
  $resp.GetResponseStream().CopyTo($ms)
  $data = $ms.ToArray()
  $ctype = if ($resp.ContentType) { $resp.ContentType } else { 'application/javascript; charset=utf-8' }
  $resp.Close()
  [System.IO.File]::WriteAllBytes($binP, $data)
  $metaJson = (@{ path = $urlPath; content_type = $ctype } | ConvertTo-Json -Compress)
  [System.IO.File]::WriteAllText($metaP, $metaJson, (New-Object System.Text.UTF8Encoding($false)))
  return @{ bytes = $data; ctype = $ctype; cached = $false }
}

$port = Get-Random -Minimum 18500 -Maximum 19900
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://127.0.0.1:$port/")
$listener.Start()

$profileDir = Join-Path ([System.IO.Path]::GetTempPath()) ("cartograph_chrome_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

$chrome = Start-Process -FilePath $browser -ArgumentList @(
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  "--user-data-dir=$profileDir", "http://127.0.0.1:$port/"
) -PassThru

$utf8 = New-Object System.Text.UTF8Encoding($false)
$htmlBytes = [System.IO.File]::ReadAllBytes($htmlPath)
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$done = $false
$hadError = $false
$cacheHits = 0
$cacheMisses = 0

try {
  $async = $listener.BeginGetContext($null, $null)
  while (-not $done -and (Get-Date) -lt $deadline) {
    if (-not $async.AsyncWaitHandle.WaitOne(500)) { continue }
    $ctx = $listener.EndGetContext($async)
    $req = $ctx.Request
    $res = $ctx.Response
    $path = $req.Url.AbsolutePath
    $res.Headers.Add('Access-Control-Allow-Origin', '*')

    if ($path -eq '/') {
      $res.ContentType = 'text/html; charset=utf-8'
      $res.OutputStream.Write($htmlBytes, 0, $htmlBytes.Length)
    } elseif ($path -eq '/config') {
      $bytes = $utf8.GetBytes((@{ mode = $mode } | ConvertTo-Json -Compress))
      $res.ContentType = 'application/json; charset=utf-8'
      $res.OutputStream.Write($bytes, 0, $bytes.Length)
    } elseif ($path -eq '/jobs') {
      $jList = @($jobs | ForEach-Object { @{ idx = $_.idx; name = $_.name; focus = $_.focus } })
      $jsonStr = ConvertTo-Json -InputObject $jList -Compress
      if (-not $jsonStr.StartsWith('[')) { $jsonStr = "[$jsonStr]" }
      $bytes = $utf8.GetBytes($jsonStr)
      $res.ContentType = 'application/json; charset=utf-8'
      $res.OutputStream.Write($bytes, 0, $bytes.Length)
    } elseif ($path -eq '/mmd') {
      $idx = [int]$req.QueryString['idx']
      $bytes = [System.IO.File]::ReadAllBytes($jobs[$idx].mmd)
      $res.ContentType = 'text/plain; charset=utf-8'
      $res.OutputStream.Write($bytes, 0, $bytes.Length)
    } elseif ($path -eq '/final_excalidraw') {
      $idx = [int]$req.QueryString['idx']
      $bytes = [System.IO.File]::ReadAllBytes($jobs[$idx].out)
      $res.ContentType = 'application/json; charset=utf-8'
      $res.OutputStream.Write($bytes, 0, $bytes.Length)
    } elseif ($path.StartsWith('/npm/')) {
      try {
        $asset = Get-CachedNpmAsset $req.Url.PathAndQuery
        if ($asset.cached) { $cacheHits++ } else { $cacheMisses++ }
        $res.ContentType = $asset.ctype
        $res.OutputStream.Write($asset.bytes, 0, $asset.bytes.Length)
      } catch {
        $res.StatusCode = 502
        $errB = $utf8.GetBytes("Cache proxy error: $($_.Exception.Message)")
        $res.OutputStream.Write($errB, 0, $errB.Length)
      }
    } elseif ($path -eq '/result') {
      $idx = [int]$req.QueryString['idx']
      $reader = New-Object System.IO.StreamReader($req.InputStream, [System.Text.Encoding]::UTF8)
      $body = $reader.ReadToEnd()
      $reader.Close()
      [System.IO.File]::WriteAllText($jobs[$idx].out, $body, $utf8)
      Write-Output "EXPORTED: $($jobs[$idx].out) ($($body.Length) chars)"
      $ok = $utf8.GetBytes('OK')
      $res.OutputStream.Write($ok, 0, $ok.Length)
    } elseif ($path -eq '/png') {
      $idx = [int]$req.QueryString['idx']
      $tile = if ($req.QueryString['tile']) { $req.QueryString['tile'] } else { 'closeup' }
      $ms = New-Object System.IO.MemoryStream
      $req.InputStream.CopyTo($ms)
      $pngBytes = $ms.ToArray()
      $pDir = if ($RenderDir) { $RenderDir } else { Split-Path -Parent $jobs[$idx].out }
      $pngOut = Join-Path $pDir "$($jobs[$idx].name)_$tile.png"
      [System.IO.File]::WriteAllBytes($pngOut, $pngBytes)
      Write-Output "PNG_SAVED: $pngOut ($($pngBytes.Length) bytes)"
      $ok = $utf8.GetBytes('OK')
      $res.OutputStream.Write($ok, 0, $ok.Length)
    } elseif ($path -eq '/log') {
      $reader = New-Object System.IO.StreamReader($req.InputStream, [System.Text.Encoding]::UTF8)
      Write-Output ("LOG: " + $reader.ReadToEnd())
      $reader.Close()
      $ok = $utf8.GetBytes('OK')
      $res.OutputStream.Write($ok, 0, $ok.Length)
    } elseif ($path -eq '/error') {
      $reader = New-Object System.IO.StreamReader($req.InputStream, [System.Text.Encoding]::UTF8)
      Write-Output ("ERR: " + $reader.ReadToEnd())
      $reader.Close()
      $hadError = $true
      $done = $true
      $ok = $utf8.GetBytes('OK')
      $res.OutputStream.Write($ok, 0, $ok.Length)
    } elseif ($path -eq '/done') {
      $done = $true
      $ok = $utf8.GetBytes('OK')
      $res.OutputStream.Write($ok, 0, $ok.Length)
    } else {
      $res.StatusCode = 404
    }
    $res.Close()
    if (-not $done) {
      $async = $listener.BeginGetContext($null, $null)
    }
  }
} finally {
  try { $listener.Stop() } catch {}
  try { if (-not $chrome.HasExited) { $chrome.Kill() } } catch {}
  try { Remove-Item -Recurse -Force -Path $profileDir -ErrorAction SilentlyContinue } catch {}
}

Write-Output "CDN_CACHE_STATS: hits=$cacheHits misses=$cacheMisses dir=$cacheDir"
if (-not $done) { throw "Timed out after ${TimeoutSec}s waiting for official Excalidraw pipeline." }
if ($hadError) { throw 'Official Excalidraw pipeline reported an error.' }
