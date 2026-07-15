# sage.ps1 -- SAGE = Spec . Acceptance . Gate . Evidence -- the ai-dev-sop command (ASCII-only, no BOM needed).
# Setup: dot-sourced from your PowerShell profile.ps1:
#   . "C:\path\to\sage\sage.ps1"
# Rename the command: change 'sage' in the Set-Alias line at the bottom.
$script:SopRoot    = $PSScriptRoot
$script:SopScripts = Join-Path $PSScriptRoot 'scripts'

function Invoke-Sage {
  [CmdletBinding()]
  param(
    [Parameter(Position = 0)][string]$Cmd = 'help',
    [Parameter(ValueFromRemainingArguments = $true)]$Rest
  )
  $s = $script:SopScripts
  if ($null -eq $Rest) { $Rest = @() }   # empty splat, not a $null positional arg (breaks default-file subcommands)
  switch ($Cmd) {
    'new'        { & (Join-Path $s 'new-task.ps1') @Rest }
    'lock'       { & (Join-Path $s 'acceptance-lock.ps1') lock @Rest }
    'relock'     { & (Join-Path $s 'acceptance-lock.ps1') relock @Rest }
    'check'      { & (Join-Path $s 'acceptance-lock.ps1') check @Rest }
    'verify'     {
      # forward -AllowUnlocked explicitly: a switch inside a plain array splat is
      # silently dropped (bound to $args), leaving Windows users no legal
      # allow-unlocked path through the dispatcher (audit W-04, second half)
      $files = @(); $allow = $false
      foreach ($a in $Rest) {
        if ("$a" -match '^(-AllowUnlocked|--allow-unlocked)$') { $allow = $true } else { $files += $a }
      }
      if ($allow) { & (Join-Path $s 'verify.ps1') @files -AllowUnlocked }
      else        { & (Join-Path $s 'verify.ps1') @files }
    }
    'crosscheck' { & (Join-Path $s 'crosscheck.ps1') @Rest }
    'retro'      { & (Join-Path $s 'retro.ps1') @Rest }
    'preflight'  { & (Join-Path $s 'preflight.ps1') @Rest }
    'test'       { & (Join-Path $s 'selftest.ps1') @Rest }
    'version'    { Get-Content (Join-Path $script:SopRoot 'VERSION') }
    'rules'      { Get-Content (Join-Path $script:SopRoot 'SAGE_RULES.md') -Encoding UTF8 }   # explicit UTF8: PS5.1 on zh systems reads BOM-less files as ANSI otherwise
    default      {
      Write-Host 'sage <command>  --  SAGE = Spec . Acceptance . Gate . Evidence'
      Write-Host '  new <name>              new task: dir + git init + templates + acceptance.txt'
      Write-Host '  lock  [acceptance.txt]  lock the acceptance set (R9; refuses if already locked)'
      Write-Host '  relock [acceptance.txt] deliberately replace an existing lock'
      Write-Host '  check [acceptance.txt]  is the acceptance set unchanged?'
      Write-Host '  verify [acceptance.txt] run acceptance, see the REAL green (you run it)'
      Write-Host '  crosscheck <file> <out> multi-CLI back-to-back review'
      Write-Host '  retro <name> [dir]      30-sec retro note -> retro/ (reminder, not a gate)'
      Write-Host '  preflight               environment precheck'
      Write-Host '  test                    selftest'
      Write-Host '  version                 print the installed SAGE CLI version'
      Write-Host '  rules                   print SAGE_RULES.md (R1-R9 / dosage / gates)'
    }
  }
}
Set-Alias sage Invoke-Sage
