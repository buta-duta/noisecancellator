param(
    [string]$Phase = "user",
    [string]$DeviceGuid = "",
    [string]$Account = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$PreMix = "{EACD2258-FCAC-4FF4-B36D-419E924A6D79}"
$PostMix = "{EC1CC9CE-FAED-4822-828A-82A81A6F018F}"
$ApoNames = @(
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},1",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},2",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6",
    "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7"
)
$SfxName = $ApoNames[2]
$EfxName = $ApoNames[4]
$ChainSfx = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},13"
$ChainEfx = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},15"
$InstallerName = "EqualizerAPO-x64-1.4.2.exe"
$InstallerUrl = "https://downloads.sourceforge.net/project/equalizerapo/1.4.2/EqualizerAPO-x64-1.4.2.exe"
$InstallerSha = "7403BE7427BBE1936A40DDED082829B6E217FC4F5990FEE5CBA501F0AE055AFA"
$ApoDll = Join-Path $env:ProgramFiles "EqualizerAPO\EqualizerAPO.dll"
$ConfigDir = Join-Path $env:ProgramFiles "EqualizerAPO\config"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-HeadphoneWired([string]$Guid) {
    $dllReady = Test-Path -LiteralPath $ApoDll
    $configFile = Join-Path $ConfigDir "config.txt"
    $clarityFile = Join-Path $ConfigDir "clarity.txt"
    if (-not $dllReady -or -not (Test-Path -LiteralPath $configFile) -or -not (Test-Path -LiteralPath $clarityFile)) {
        return $false
    }
    $configText = Get-Content -LiteralPath $configFile -Raw
    if ($configText -notmatch "(?m)^Include:\s*clarity\.txt\s*$") {
        return $false
    }
    $fxPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$Guid\FxProperties"
    if (-not (Test-Path -LiteralPath $fxPath)) {
        return $false
    }
    $key = Get-Item -LiteralPath $fxPath
    $sfx = [string]$key.GetValue($SfxName)
    $efx = [string]$key.GetValue($EfxName)
    $chain13 = @($key.GetValue($ChainSfx))
    $chain15 = @($key.GetValue($ChainEfx))
    return ($sfx -eq $PreMix -and $efx -eq $PostMix -and ($chain13 -contains $PreMix) -and ($chain15 -contains $PostMix))
}

function Enable-Privilege([string]$Name) {
    if (-not ("TokPriv" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TokPriv {
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool OpenProcessToken(IntPtr h, uint acc, out IntPtr tok);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern bool LookupPrivilegeValue(string sys, string name, out LUID luid);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool AdjustTokenPrivileges(IntPtr tok, bool dis, ref TOKEN_PRIVILEGES news, int len, IntPtr prev, IntPtr ret);
    [StructLayout(LayoutKind.Sequential)]
    public struct LUID { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)]
    public struct LUID_AND_ATTRIBUTES { public LUID Luid; public uint Attr; }
    [StructLayout(LayoutKind.Sequential)]
    public struct TOKEN_PRIVILEGES { public uint Count; public LUID_AND_ATTRIBUTES Priv; }
    public static void Enable(string privilege) {
        IntPtr tok;
        if (!OpenProcessToken(System.Diagnostics.Process.GetCurrentProcess().Handle, 0x28, out tok))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        LUID luid;
        if (!LookupPrivilegeValue(null, privilege, out luid))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        TOKEN_PRIVILEGES tp = new TOKEN_PRIVILEGES();
        tp.Count = 1;
        tp.Priv.Luid = luid;
        tp.Priv.Attr = 2;
        if (!AdjustTokenPrivileges(tok, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    }
}
"@
    }
    [TokPriv]::Enable($Name)
}

function Open-Registry([string]$Relative, [string]$RightsName) {
    $rights = [System.Security.AccessControl.RegistryRights]$RightsName
    return [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey(
        $Relative,
        [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree,
        $rights
    )
}

function Grant-Registry([string]$Relative) {
    Enable-Privilege "SeTakeOwnershipPrivilege"
    Enable-Privilege "SeRestorePrivilege"
    $admin = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")
    $take = Open-Registry $Relative "TakeOwnership"
    if ($null -eq $take) { throw "cannot take ownership of $Relative" }
    $acl = $take.GetAccessControl()
    $acl.SetOwner($admin)
    $take.SetAccessControl($acl)
    $take.Close()
    $change = Open-Registry $Relative "ChangePermissions"
    $acl = $change.GetAccessControl()
    $rule = New-Object System.Security.AccessControl.RegistryAccessRule($admin, "FullControl", "Allow")
    $acl.SetAccessRule($rule)
    $change.SetAccessControl($acl)
    $change.Close()
}

function Install-ApoFiles {
    if (Test-Path -LiteralPath $ApoDll) {
        Write-Output "Equalizer APO is already installed."
        return
    }
    $dest = Join-Path $env:TEMP $InstallerName
    Write-Output "Downloading Equalizer APO 1.4.2"
    & curl.exe -L --fail --retry 2 -o $dest $InstallerUrl
    $hash = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
    if ($hash -ne $InstallerSha) { throw "installer hash mismatch" }
    $installer = Start-Process -FilePath $dest -ArgumentList "/S" -PassThru
    $deadline = (Get-Date).AddMinutes(4)
    while (-not $installer.HasExited -and (Get-Date) -lt $deadline) {
        Get-Process -Name DeviceSelector, Configurator -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Milliseconds 400
    }
    if (-not $installer.HasExited) {
        Stop-Process -Id $installer.Id -Force
        throw "Equalizer APO installer timed out"
    }
    if (-not (Test-Path -LiteralPath $ApoDll)) { throw "Equalizer APO DLL missing after install" }
    $reg = Start-Process -FilePath "$env:SystemRoot\System32\regsvr32.exe" -ArgumentList "/s `"$ApoDll`"" -Wait -PassThru
    if ($reg.ExitCode -ne 0) { throw "regsvr32 failed ($($reg.ExitCode))" }
}

function Register-Headphone([string]$Guid) {
    $fxRel = "SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$Guid\FxProperties"
    Grant-Registry $fxRel
    $fx = Open-Registry $fxRel "FullControl"
    if ($null -eq $fx) { throw "cannot open headphone FxProperties" }
    $child = [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey("SOFTWARE\EqualizerAPO\Child APOs\$Guid")
    $origSfx = $null
    $origEfx = $null
    foreach ($name in $ApoNames) {
        $existing = $fx.GetValue($name)
        if ($null -eq $existing) {
            $child.SetValue($name, "!VALUE")
        } else {
            $child.SetValue($name, [string]$existing)
            if ($name -eq $SfxName) { $origSfx = [string]$existing }
            if ($name -eq $EfxName) { $origEfx = [string]$existing }
        }
    }
    $preChild = ""
    $postChild = ""
    if ($origSfx -and $origSfx -ne $PreMix -and $origSfx -ne $PostMix) { $preChild = $origSfx }
    if ($origEfx -and $origEfx -ne $PreMix -and $origEfx -ne $PostMix) { $postChild = $origEfx }
    $child.SetValue("PreMixChild", $preChild)
    $child.SetValue("PostMixChild", $postChild)
    $child.SetValue("AllowSilentBufferModification", "false")
    $child.SetValue("Version", "2")
    foreach ($drop in @($ApoNames[0], $ApoNames[1])) {
        if ($null -ne $fx.GetValue($drop)) { $fx.DeleteValue($drop) }
    }
    $fx.SetValue($SfxName, $PreMix)
    $fx.SetValue($EfxName, $PostMix)
    $chain13 = @($fx.GetValue($ChainSfx))
    if ($chain13 -notcontains $PreMix) { $chain13 = @($PreMix) + $chain13 }
    $fx.SetValue($ChainSfx, [string[]]$chain13, [Microsoft.Win32.RegistryValueKind]::MultiString)
    $chain15 = @($fx.GetValue($ChainEfx))
    if ($chain15 -notcontains $PostMix) { $chain15 += $PostMix }
    $fx.SetValue($ChainEfx, [string[]]$chain15, [Microsoft.Win32.RegistryValueKind]::MultiString)
    $disabled = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"
    if ($null -ne $fx.GetValue($disabled)) { $fx.DeleteValue($disabled) }
    $fx.Close()
    $child.Close()
    New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Audio" -Name "DisableProtectedAudioDG" -Value 1 -PropertyType DWord -Force | Out-Null
}

function Remove-CaptureRegistration {
    $captureRoot = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
    if (-not (Test-Path -LiteralPath $captureRoot)) { return }
    Get-ChildItem -LiteralPath $captureRoot | ForEach-Object {
        $rel = "SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\$($_.PSChildName)\FxProperties"
        $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($rel, $false)
        if ($null -eq $key) { return }
        $hit = @()
        foreach ($name in ($ApoNames + @($ChainSfx, $ChainEfx))) {
            $value = $key.GetValue($name)
            if ($value -eq $PreMix -or $value -eq $PostMix) { $hit += $name }
            if ($value -is [string[]] -and (($value -contains $PreMix) -or ($value -contains $PostMix))) { $hit += $name }
        }
        $key.Close()
        if ($hit.Count -eq 0) { return }
        Grant-Registry $rel
        $writable = Open-Registry $rel "FullControl"
        foreach ($name in $hit) {
            $value = $writable.GetValue($name)
            if ($value -is [string[]]) {
                $kept = @($value | Where-Object { $_ -ne $PreMix -and $_ -ne $PostMix })
                $writable.SetValue($name, [string[]]$kept, [Microsoft.Win32.RegistryValueKind]::MultiString)
            } else {
                $writable.DeleteValue($name)
            }
        }
        $writable.Close()
    }
}

function Write-ApoConfig([string]$AccountName) {
    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
    $main = Join-Path $ConfigDir "config.txt"
    $needsInclude = $true
    if (Test-Path -LiteralPath $main) {
        $current = Get-Content -LiteralPath $main -Raw
        if ($current -match "(?m)^Include:\s*clarity\.txt\s*$" -and $current -notmatch "GraphicEQ|example\.txt") {
            $needsInclude = $false
        } elseif (-not (Test-Path -LiteralPath ($main + ".before-clarity"))) {
            Copy-Item -LiteralPath $main -Destination ($main + ".before-clarity") -Force
        }
    }
    if ($needsInclude) {
        Set-Content -LiteralPath $main -Value "Include: clarity.txt`r`n" -Encoding ascii
    }
    $clarity = Join-Path $ConfigDir "clarity.txt"
    if (-not (Test-Path -LiteralPath $clarity)) {
        Set-Content -LiteralPath $clarity -Value "# Clarity off`r`n" -Encoding ascii
    }
    & icacls.exe $ConfigDir /grant "${AccountName}:(OI)(CI)M" /T | Out-Null
}

function Register-Phase([string]$Guid, [string]$AccountName) {
    if (-not (Test-Admin)) { throw "administrator rights are required" }
    $changed = -not (Test-HeadphoneWired $Guid)
    Install-ApoFiles
    if (-not (Test-HeadphoneWired $Guid)) {
        Register-Headphone $Guid
        $changed = $true
    }
    Remove-CaptureRegistration
    Write-ApoConfig $AccountName
    if ($changed) {
        Restart-Service -Name Audiosrv -Force
        Write-Output "Audio service restarted so the headphone endpoint loads Equalizer APO."
    } else {
        Write-Output "Headphone endpoint is already wired. Audio service was left running."
    }
}

if ($Phase -eq "register") {
    Register-Phase $DeviceGuid $Account
    exit 0
}

Set-Location -LiteralPath $Root
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Python 3.12 or newer is required on PATH." }
& $python.Source -m venv (Join-Path $Root ".venv")
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPython -m pip install -r (Join-Path $Root "requirements.txt")
$detected = & $venvPython -m clarity.devices
if ($LASTEXITCODE -ne 0 -or -not $detected) { throw "no playback device found" }
$guid = [string]$detected[0]
$friendly = ([string[]]$detected | Select-Object -Skip 1) -join " "
Write-Output "Headphone endpoint: $friendly"
Write-Output "Endpoint id: $guid"
if (Test-HeadphoneWired $guid) {
    Write-Output "Equalizer APO is already configured for this endpoint."
    exit 0
}
$account = whoami
$argumentList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Phase register -DeviceGuid `"$guid`" -Account `"$account`""
$elevated = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList $argumentList
if ($elevated.ExitCode -ne 0) { throw "Equalizer APO setup did not finish (exit $($elevated.ExitCode))." }
Write-Output "Setup finished."
