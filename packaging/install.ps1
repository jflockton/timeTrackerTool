<#
timeTrackerTool installer — no Python required on this machine.

Copies the "timeTrackerTool" folder sitting next to this script into a
proper install location and creates a Start Menu shortcut:

  just me    -> %LOCALAPPDATA%\Programs\timeTrackerTool   (no admin)
  all users  -> %ProgramFiles%\timeTrackerTool            (auto-elevates)

Usage (via install.bat, which bypasses the execution policy):
  install.bat               interactive: asks just me / all users
  install.bat -AllUsers     machine-wide, prompts for admin approval
  install.bat -Uninstall    remove the app and its shortcut
Re-run after getting a newer zip to upgrade in place.
#>
param(
    [switch]$AllUsers,
    [switch]$CurrentUser,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$AppName = "timeTrackerTool"
$Source = Join-Path $PSScriptRoot $AppName

function Get-Paths([bool]$All) {
    if ($All) {
        @{ Install  = Join-Path $env:ProgramFiles $AppName
           Shortcut = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\$AppName.lnk" }
    } else {
        @{ Install  = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
           Shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk" }
    }
}

if (-not $AllUsers -and -not $CurrentUser) {
    if ($Uninstall) {
        $CurrentUser = $true  # bare uninstall targets the per-user install
    } else {
        Write-Host "Install $AppName for:"
        Write-Host "  [1] Just me     (no admin needed)"
        Write-Host "  [2] All users   (needs administrator approval)"
        do { $choice = Read-Host "Choose 1 or 2" } until ($choice -in "1", "2")
        if ($choice -eq "2") { $AllUsers = $true } else { $CurrentUser = $true }
    }
}

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($AllUsers -and -not $isAdmin) {
    Write-Host "Requesting administrator approval..."
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", "`"$PSCommandPath`"", "-AllUsers")
    if ($Uninstall) { $argList += "-Uninstall" }
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    exit 0
}

$paths = Get-Paths $AllUsers

if ($Uninstall) {
    $removed = $false
    if (Test-Path $paths.Shortcut) {
        Remove-Item $paths.Shortcut -Force
        Write-Host "Removed $($paths.Shortcut)"
        $removed = $true
    }
    if (Test-Path $paths.Install) {
        Remove-Item $paths.Install -Recurse -Force
        Write-Host "Removed $($paths.Install)"
        $removed = $true
    }
    if (-not $removed) { Write-Host "Nothing installed - nothing removed." }
    Write-Host "Your tracked time is untouched (it lives in %APPDATA%\$AppName)."
    exit 0
}

if (-not (Test-Path (Join-Path $Source "$AppName.exe"))) {
    Write-Host "Can't find the '$AppName' folder next to this script."
    Write-Host "Unzip the whole download first, then run install.bat again."
    exit 1
}

Write-Host "Installing to $($paths.Install) ..."
if (Test-Path $paths.Install) {
    try {
        Remove-Item $paths.Install -Recurse -Force
    } catch {
        Write-Host "Couldn't replace the installed app - if $AppName is"
        Write-Host "running, quit it (tray icon -> Quit) and run this again."
        exit 1
    }
}
$parent = Split-Path $paths.Install -Parent
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force $parent | Out-Null }
Copy-Item $Source $paths.Install -Recurse

$shortcutDir = Split-Path $paths.Shortcut -Parent
if (-not (Test-Path $shortcutDir)) { New-Item -ItemType Directory -Force $shortcutDir | Out-Null }
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($paths.Shortcut)
$lnk.TargetPath = Join-Path $paths.Install "$AppName.exe"
$lnk.WorkingDirectory = $paths.Install
$lnk.IconLocation = (Join-Path $paths.Install "$AppName.exe") + ",0"
$lnk.Description = "timeTrackerTool - one big button per task"
$lnk.Save()
Write-Host "Start Menu shortcut: $($paths.Shortcut)"
Write-Host "Done - press the Windows key and type 'time' to find it."
