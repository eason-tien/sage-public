# acceptance-lock.ps1 -- lock / relock / check the acceptance set so a weakened acceptance.txt
# cannot SILENTLY pass verify (R9). Tamper-EVIDENT (git-tracked lock), not tamper-proof.
# Usage:
#   .\acceptance-lock.ps1 lock   [acceptance.txt]   # create lock; REFUSES if a lock already exists
#   .\acceptance-lock.ps1 relock [acceptance.txt]   # explicitly replace an existing lock (deliberate)
#   .\acceptance-lock.ps1 check  [acceptance.txt]   # exit 0 if unchanged; exit 1 if changed / no lock
# ASCII-only on purpose (no BOM dependency).
param([string]$Action = "", [string]$AcceptFile = "acceptance.txt")
$ErrorActionPreference = 'Stop'

# Anchor relative paths to the PowerShell location: [System.IO.File] APIs resolve against the
# PROCESS cwd, which Set-Location/Push-Location do NOT change (bites in-process dispatcher use).
# Keep the user-supplied path for display and for the .lock third field (verbatim, like the .sh
# version) so committed locks never leak machine-local absolute paths.
$AcceptDisplay = $AcceptFile
if (-not [System.IO.Path]::IsPathRooted($AcceptFile)) { $AcceptFile = Join-Path (Get-Location).Path $AcceptFile }
if (-not (Test-Path $AcceptFile)) { Write-Host "acceptance file not found: $AcceptDisplay"; exit 1 }
function Get-NormHash([string]$p) {
  # Byte-level CRLF -> LF only. A lone CR remains significant because PowerShell can
  # interpret it as a command boundary; deleting every CR would create an R9 bypass.
  $raw = [System.IO.File]::ReadAllBytes($p)
  $keep = New-Object System.Collections.Generic.List[byte]
  for ($i = 0; $i -lt $raw.Length; $i++) {
    if ($raw[$i] -eq 13 -and $i + 1 -lt $raw.Length -and $raw[$i + 1] -eq 10) { continue }
    $keep.Add($raw[$i])
  }
  return ([System.BitConverter]::ToString(([System.Security.Cryptography.SHA256]::Create()).ComputeHash($keep.ToArray()))).Replace('-','').ToLowerInvariant()
}
$lock = "$AcceptFile.lock"
$lockDisplay = "$AcceptDisplay.lock"
$hash = Get-NormHash $AcceptFile
function Write-Lock() {
  # UTC Z timestamp, identical format to acceptance-lock.sh (date -u +%Y-%m-%dT%H:%M:%SZ).
  # InvariantCulture: custom format strings follow the current culture's calendar and
  # separators otherwise (e.g. ar-SA writes a non-Gregorian year).
  $ts = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ', [System.Globalization.CultureInfo]::InvariantCulture)
  $line = "$hash  $ts  $AcceptDisplay"
  [System.IO.File]::WriteAllText($lock, $line + "`n", (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "locked: $AcceptDisplay"
  Write-Host "  sha256: $hash"
  Write-Host "  -> commit $lockDisplay so the lock is tracked in git (tamper-evident)."
}

switch ($Action) {
  'lock' {
    if (Test-Path $lock) {
      Write-Host "lock already exists: $lockDisplay"
      Write-Host "  changing the acceptance set needs explicit human intent ->"
      Write-Host "  use: acceptance-lock.ps1 relock $AcceptDisplay"
      exit 1
    }
    Write-Lock; exit 0
  }
  'relock' { Write-Lock; Write-Host "  (relock: existing lock deliberately replaced)"; exit 0 }
  'check' {
    if (-not (Test-Path $lock)) { Write-Host "no lock file: $lockDisplay  (run: acceptance-lock.ps1 lock $AcceptDisplay)"; exit 1 }
    $locked = (((Get-Content -Path $lock -TotalCount 1) -split '\s+')[0]).Trim().ToLowerInvariant()
    if ($hash -eq $locked) { Write-Host ("OK: acceptance unchanged (" + $hash.Substring(0,12) + "...)"); exit 0 }
    Write-Host "TAMPERED: acceptance changed since lock."
    Write-Host "  locked : $locked"
    Write-Host "  current: $hash"
    exit 1
  }
  default { Write-Host "usage: acceptance-lock.ps1 {lock|relock|check} [acceptance.txt]"; exit 1 }
}
