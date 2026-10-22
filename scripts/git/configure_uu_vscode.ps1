# Configure this Windows user's UU SSH aliases and VS Code Linux platform.
# Reads existing SSH/VS Code config, an existing private-key PATH (not contents),
# and a previously accepted public known-hosts seed. Writes backed-up user config.
# No remote command, model call, key copying, global proxy or GUI launch.
[CmdletBinding()]
param(
    [string]$IdentityFile = "$env:USERPROFILE/.ssh/KeyPair-nl.pem",
    [Parameter(Mandatory=$true)][string]$KnownHostsSeed,
    [string]$SshConfig = "$env:USERPROFILE/.ssh/config",
    [string]$VSCodeSettings = "$env:APPDATA/Code/User/settings.json",
    [ValidateRange(1024,65535)][int]$UuPort = 12222,
    [ValidateRange(1024,65535)][int]$ProxyPort = 17897,
    [ValidateRange(1024,65535)][int]$ClashPort = 7897
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$stamp = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'China Standard Time').ToString('yyyyMMdd_HHmmss_ffff')

function Publish-BackedUpText([string]$Path, [string]$Original, [string]$Updated) {
    if ($Original -ceq $Updated) { return }
    if ([IO.File]::ReadAllText($Path) -cne $Original) { throw 'Configuration changed concurrently; refusing overwrite.' }
    $tempPath = $Path + '.video-sft-' + $stamp + '.tmp'
    $backupPath = $Path + '.backup-video-sft-' + $stamp
    if ((Test-Path -LiteralPath $tempPath) -or (Test-Path -LiteralPath $backupPath)) { throw 'Backup/staging path already exists.' }
    [IO.File]::WriteAllText($tempPath, $Updated, $utf8)
    try { [IO.File]::Replace($tempPath, $Path, $backupPath) }
    finally { if (Test-Path -LiteralPath $tempPath) { Remove-Item -LiteralPath $tempPath } }
    Write-Output ('BACKUP: ' + $backupPath)
}

try {
    foreach ($path in @($IdentityFile, $KnownHostsSeed, $SshConfig, $VSCodeSettings)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Required config/key/known-host seed file is missing.' }
    }
    $IdentityFile = [IO.Path]::GetFullPath($IdentityFile).Replace('\','/')
    $SshConfig = [IO.Path]::GetFullPath($SshConfig)
    $VSCodeSettings = [IO.Path]::GetFullPath($VSCodeSettings)
    $knownDestination = Join-Path ([IO.Path]::GetDirectoryName($SshConfig)) 'known_hosts_video_sft'
    $knownPath = $knownDestination.Replace('\','/')
    $knownText = [IO.File]::ReadAllText($KnownHostsSeed)
    if ($knownText -notmatch '(?m)^audio-1-modelarts-server\s') { throw 'Seed does not contain the previously accepted server host alias.' }
    if (Test-Path -LiteralPath $knownDestination) {
        if ([IO.File]::ReadAllText($knownDestination) -cne $knownText) { throw 'Dedicated known-hosts file differs; inspect before replacing it.' }
    }
    $begin = '# BEGIN video-sft UU SSH'
    $end = '# END video-sft UU SSH'
    $block = @"
$begin
Host audio_1_uu audio_1_proxy
    HostName 127.0.0.1
    Port $UuPort
    User root
    IdentityFile "$IdentityFile"
    IdentitiesOnly yes
    ConnectTimeout 10
    ServerAliveInterval 30
    ServerAliveCountMax 3
    HostKeyAlias audio-1-modelarts-server
    UserKnownHostsFile "$knownPath"
    StrictHostKeyChecking yes

Host audio_1_proxy
    RemoteForward 127.0.0.1:$ProxyPort 127.0.0.1:$ClashPort
    ExitOnForwardFailure yes
$end
"@
    $sshOriginal = [IO.File]::ReadAllText($SshConfig)
    $managedPattern = '(?ms)^' + [regex]::Escape($begin) + '\r?\n.*?^' + [regex]::Escape($end) + '\r?\n?'
    $managed = [regex]::Matches($sshOriginal, $managedPattern)
    if ($managed.Count -gt 1) { throw 'Multiple managed SSH blocks; refusing ambiguous update.' }
    if ($managed.Count -eq 1) {
        if ($managed[0].Value.TrimEnd() -cne $block.TrimEnd()) { throw 'Managed SSH block changed; inspect before replacing it.' }
        $sshUpdated = $sshOriginal
    } else {
        if ($sshOriginal -match '(?m)^\s*Host\s+[^\r\n]*\baudio_1_(uu|proxy)\b') { throw 'Requested SSH alias already exists outside managed block.' }
        $sshUpdated = $block + "`r`n`r`n" + $sshOriginal
    }
    $settingsOriginal = [IO.File]::ReadAllText($VSCodeSettings)
    $custom = [regex]::Match($settingsOriginal, '"remote\.SSH\.configFile"\s*:\s*"([^"\r\n]*)"')
    if ($custom.Success) { throw 'VS Code uses an explicit SSH config; inspect that setting before applying defaults.' }
    $platform = [regex]::Matches($settingsOriginal, '"remote\.SSH\.remotePlatform"\s*:\s*\{[^{}]*\}')
    if ($platform.Count -ne 1) { throw 'Expected one existing remotePlatform map; refusing to rewrite unrelated VS Code settings.' }
    $entry = [regex]::Match($platform[0].Value, '"audio_1_uu"\s*:\s*"([^"]+)"')
    if ($entry.Success -and $entry.Groups[1].Value -ne 'linux') { throw 'Existing platform for audio_1_uu is not linux.' }
    $settingsUpdated = $settingsOriginal
    if (-not $entry.Success) {
        $offset = $platform[0].Index + $platform[0].Value.IndexOf('{') + 1
        $hasEntries = $platform[0].Value.Substring($platform[0].Value.IndexOf('{') + 1).Trim() -ne '}'
        $addition = "`r`n    `"audio_1_uu`": `"linux`"" + $(if ($hasEntries) { ',' } else { '' })
        $settingsUpdated = $settingsOriginal.Insert($offset, $addition)
    }
    # Validate every intended edit before publishing any of them.
    if (-not (Test-Path -LiteralPath $knownDestination)) {
        $stream = [IO.File]::Open($knownDestination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try { $bytes = $utf8.GetBytes($knownText); $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
    }
    Publish-BackedUpText $SshConfig $sshOriginal $sshUpdated
    Publish-BackedUpText $VSCodeSettings $settingsOriginal $settingsUpdated
    Write-Output 'PASS: audio_1_uu is ready for VS Code; audio_1_proxy is a separate Git-proxy tunnel alias.'
} catch {
    Write-Error ('FAIL: UU/VS Code configuration: ' + $_.Exception.Message)
    exit 1
}
