param(
    [string]$Phase = "user",
    [string]$DeviceGuid = "",
    [string]$Account = "",
    [string]$ResultPath = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Pre = "{EACD2258-FCAC-4FF4-B36D-419E924A6D79}"
$Post = "{EC1CC9CE-FAED-4822-828A-82A81A6F018F}"
$Fx = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d}"
$Lfx = "$Fx,1"
$Gfx = "$Fx,2"
$Sfx = "$Fx,5"
$Mfx = "$Fx,6"
$Efx = "$Fx,7"
$ChainSfx = "$Fx,13"
$ChainMfx = "$Fx,14"
$ChainEfx = "$Fx,15"
$InstallerName = "EqualizerAPO-x64-1.4.2.exe"
$InstallerUrl = "https://downloads.sourceforge.net/project/equalizerapo/1.4.2/EqualizerAPO-x64-1.4.2.exe"
$InstallerSha = "7403BE7427BBE1936A40DDED082829B6E217FC4F5990FEE5CBA501F0AE055AFA"
$ApoDll = Join-Path $env:ProgramFiles "EqualizerAPO\EqualizerAPO.dll"
$ConfigDir = Join-Path $env:ProgramFiles "EqualizerAPO\config"
$Modes = @(
    @{ Name = "SFX/EFX"; PreSlot = $Sfx; PostSlot = $Efx; PreChain = $ChainSfx; PostChain = $ChainEfx },
    @{ Name = "SFX/MFX"; PreSlot = $Sfx; PostSlot = $Mfx; PreChain = $ChainSfx; PostChain = $ChainMfx },
    @{ Name = "LFX/GFX"; PreSlot = $Lfx; PostSlot = $Gfx; PreChain = $null; PostChain = $null }
)

function Publish([string]$Text) {
    Write-Output $Text
    if ($ResultPath) {
        Add-Content -LiteralPath $ResultPath -Value $Text -Encoding utf8
    }
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-ApoLoaded {
    $out = & "$env:SystemRoot\System32\tasklist.exe" /m EqualizerAPO.dll 2>&1 | Out-String
    if ($out -match "No tasks are running") { return $false }
    return $out -match "EqualizerAPO\.dll"
}

function Write-ProbeWav([string]$Path) {
    $rate = 48000
    $count = [int]($rate * 0.08)
    $data = New-Object System.Collections.Generic.List[byte]
    for ($i = 0; $i -lt $count; $i++) {
        $sample = [int]([math]::Round([math]::Sin(2 * [math]::PI * 440.0 * $i / $rate) * 0.08 * 32767))
        $unsigned = $sample -band 65535
        $data.Add([byte]($unsigned -band 255))
        $data.Add([byte](($unsigned -shr 8) -band 255))
    }
    $dataSize = $data.Count
    $stream = [System.IO.File]::Create($Path)
    $writer = New-Object System.IO.BinaryWriter $stream
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("RIFF"))
    $writer.Write([int](36 + $dataSize))
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("WAVEfmt "))
    $writer.Write([int]16)
    $writer.Write([int16]1)
    $writer.Write([int16]1)
    $writer.Write([int]$rate)
    $writer.Write([int]($rate * 2))
    $writer.Write([int16]2)
    $writer.Write([int16]16)
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("data"))
    $writer.Write([int]$dataSize)
    $writer.Write($data.ToArray())
    $writer.Close()
    $stream.Close()
}

function Invoke-AudiodgProbe {
    $wav = Join-Path $env:TEMP "clarity-apo-probe.wav"
    if (-not (Test-Path -LiteralPath $wav)) { Write-ProbeWav $wav }
    for ($try = 0; $try -lt 4; $try++) {
        try {
            $player = New-Object System.Media.SoundPlayer $wav
            $player.PlaySync()
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
}

function Wait-ApoLoaded {
    for ($i = 0; $i -lt 6; $i++) {
        Invoke-AudiodgProbe
        Start-Sleep -Seconds 1
        if (Test-ApoLoaded) { return $true }
    }
    return $false
}

function Restart-WindowsAudio {
    try {
        Restart-Service -Name Audiosrv -Force -ErrorAction Stop
    } catch {
        Stop-Service -Name Audiosrv -Force -ErrorAction SilentlyContinue
        Start-Service -Name AudioEndpointBuilder
        Start-Service -Name Audiosrv
    }
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Service -Name Audiosrv).Status -ne "Running" -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
    }
    Start-Sleep -Seconds 1
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
        Publish "Equalizer APO is already installed."
        return
    }
    $dest = Join-Path $env:TEMP $InstallerName
    Publish "Downloading Equalizer APO 1.4.2"
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

function Remove-CaptureRegistration {
    $captureRoot = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
    if (-not (Test-Path -LiteralPath $captureRoot)) { return }
    $names = @($Lfx, $Gfx, $Sfx, $Mfx, $Efx, $ChainSfx, $ChainMfx, $ChainEfx)
    Get-ChildItem -LiteralPath $captureRoot | ForEach-Object {
        $rel = "SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\$($_.PSChildName)\FxProperties"
        $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($rel, $false)
        if ($null -eq $key) { return }
        $hit = @()
        foreach ($name in $names) {
            $value = $key.GetValue($name)
            if ($value -eq $Pre -or $value -eq $Post) { $hit += $name }
            if ($value -is [string[]] -and (($value -contains $Pre) -or ($value -contains $Post))) { $hit += $name }
        }
        $key.Close()
        if ($hit.Count -eq 0) { return }
        Grant-Registry $rel
        $writable = Open-Registry $rel "FullControl"
        foreach ($name in $hit) {
            $value = $writable.GetValue($name)
            if ($value -is [string[]]) {
                $kept = @($value | Where-Object { $_ -ne $Pre -and $_ -ne $Post })
                if ($kept.Count -eq 0) { $writable.DeleteValue($name) }
                else { $writable.SetValue($name, [string[]]$kept, [Microsoft.Win32.RegistryValueKind]::MultiString) }
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

function Get-FxSnapshot($key) {
    $snap = @()
    foreach ($name in @($key.GetValueNames())) {
        $value = $key.GetValue($name)
        if ($value -is [System.Array]) { $value = @($value.Clone()) }
        $snap += @{ Name = $name; Kind = $key.GetValueKind($name); Value = $value }
    }
    return $snap
}

function Restore-FxSnapshot($key, $snap) {
    $names = @($snap | ForEach-Object { $_.Name })
    foreach ($name in @($key.GetValueNames())) {
        if ($names -notcontains $name) { $key.DeleteValue($name, $false) }
    }
    foreach ($item in $snap) {
        $key.SetValue($item.Name, $item.Value, $item.Kind)
    }
}

function Remove-OurGuids($key) {
    foreach ($name in @($Lfx, $Gfx, $Sfx, $Mfx, $Efx)) {
        $value = $key.GetValue($name)
        if ($value -eq $Pre -or $value -eq $Post) { $key.DeleteValue($name, $false) }
    }
    foreach ($name in @($ChainSfx, $ChainMfx, $ChainEfx)) {
        if ($null -eq $key.GetValue($name)) { continue }
        $kept = @($key.GetValue($name) | Where-Object { $_ -and $_ -ne $Pre -and $_ -ne $Post })
        if ($kept.Count -eq 0) { $key.DeleteValue($name, $false) }
        else { $key.SetValue($name, [string[]]$kept, [Microsoft.Win32.RegistryValueKind]::MultiString) }
    }
}

function Add-ChainGuid($key, $name, $guid) {
    $current = @()
    if ($null -ne $key.GetValue($name)) { $current = @($key.GetValue($name)) }
    $kept = @($current | Where-Object { $_ -and $_ -ne $guid })
    $key.SetValue($name, [string[]](@($guid) + $kept), [Microsoft.Win32.RegistryValueKind]::MultiString)
}

function Set-ApoMode($fx, $child, $mode) {
    Remove-OurGuids $fx
    foreach ($pair in @(
        @{ Slot = $mode.PreSlot; Guid = $Pre; Child = "PreMixChild" },
        @{ Slot = $mode.PostSlot; Guid = $Post; Child = "PostMixChild" }
    )) {
        $existing = $fx.GetValue($pair.Slot)
        if ($existing -and "$existing" -ne $Pre -and "$existing" -ne $Post) {
            $child.SetValue($pair.Slot, "$existing")
            $child.SetValue($pair.Child, "$existing")
        }
        $fx.SetValue($pair.Slot, $pair.Guid)
    }
    if ($mode.PreChain) { Add-ChainGuid $fx $mode.PreChain $Pre }
    if ($mode.PostChain) { Add-ChainGuid $fx $mode.PostChain $Post }
    $disabled = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"
    if ($null -ne $fx.GetValue($disabled)) { $fx.DeleteValue($disabled, $false) }
    $child.SetValue("AllowSilentBufferModification", "false")
    $child.SetValue("Version", "2")
    New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Audio" -Name "DisableProtectedAudioDG" -Value 1 -PropertyType DWord -Force | Out-Null
}

function Register-Phase([string]$Guid, [string]$AccountName) {
    if (-not (Test-Admin)) { throw "administrator rights are required" }
    Install-ApoFiles
    try { Remove-CaptureRegistration } catch { Publish "Capture registration was left unchanged." }
    Write-ApoConfig $AccountName
    Invoke-AudiodgProbe
    if (Test-ApoLoaded) {
        Publish "Equalizer APO is already loaded."
        return
    }
    $fxRel = "SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$Guid\FxProperties"
    Grant-Registry $fxRel
    $fx = Open-Registry $fxRel "FullControl"
    if ($null -eq $fx) { throw "cannot open headphone FxProperties" }
    $snap = Get-FxSnapshot $fx
    $child = [Microsoft.Win32.Registry]::LocalMachine.CreateSubKey("SOFTWARE\EqualizerAPO\Child APOs\$Guid")
    $script:Loaded = $false
    $script:Touched = $false
    try {
        foreach ($mode in $Modes) {
            Publish "Trying $($mode.Name)"
            Restore-FxSnapshot $fx $snap
            Set-ApoMode $fx $child $mode
            $script:Touched = $true
            Restart-WindowsAudio
            if (Wait-ApoLoaded) {
                $script:Loaded = $true
                Publish "Equalizer APO loaded using $($mode.Name)."
                break
            }
        }
    } finally {
        try {
            if (-not $script:Loaded -and $script:Touched) {
                Restore-FxSnapshot $fx $snap
                Restart-WindowsAudio
                Publish "Equalizer APO did not load. Restored the previous headphone registration."
            }
        } finally {
            if ($fx) { $fx.Close() }
            if ($child) { $child.Close() }
        }
    }
    if (-not $script:Loaded) { exit 1 }
}

if ($Phase -eq "register") {
    Register-Phase $DeviceGuid $Account
    exit 0
}

Set-Location -LiteralPath $Root
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Python 3.12 or newer is required on PATH." }
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python.Source -m venv (Join-Path $Root ".venv")
}
& $venvPython -m pip install -r (Join-Path $Root "requirements.txt")
$detected = & $venvPython -m clarity.devices
if ($LASTEXITCODE -ne 0 -or -not $detected) { throw "no playback device found" }
$guid = [string]$detected[0]
$friendly = ([string[]]$detected | Select-Object -Skip 1) -join " "
Write-Output "Headphone endpoint: $friendly"
Write-Output "Endpoint id: $guid"
Invoke-AudiodgProbe
if (Test-ApoLoaded) {
    Write-Output "Equalizer APO is already loaded."
    exit 0
}
$account = whoami
$result = Join-Path $env:TEMP "clarity-setup-result.txt"
if (Test-Path -LiteralPath $result) { Remove-Item -LiteralPath $result -Force }
$argumentList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Phase register -DeviceGuid `"$guid`" -Account `"$account`" -ResultPath `"$result`""
$elevated = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList $argumentList
if (Test-Path -LiteralPath $result) { Get-Content -LiteralPath $result | Write-Output }
if ($elevated.ExitCode -ne 0) { throw "Equalizer APO setup did not finish (exit $($elevated.ExitCode))." }
Write-Output "Setup finished."
