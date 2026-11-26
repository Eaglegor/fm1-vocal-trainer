param([string]$Toolchain = $env:FM1_PI32_TOOLCHAIN)
$ErrorActionPreference = 'Stop'
if (!$Toolchain) { $Toolchain = 'C:\JL\pi32' }
$base = Join-Path $PSScriptRoot '.build/fm1_open'
$revision = '4c7496daac04a95ff10d1afdcc8f9ead2dbabc41'
if (!(Test-Path $base)) {
    git clone --no-checkout https://github.com/m-vave/fm1_open.git $base
    if ($LASTEXITCODE) { throw 'SDK clone failed' }
    git -C $base checkout --detach $revision
    if ($LASTEXITCODE) { throw 'SDK checkout failed' }
}
if ((git -C $base rev-parse HEAD) -ne $revision) { throw "Expected SDK at $revision in $base" }
$patch = Join-Path $PSScriptRoot 'firmware/trainer.patch'
$work = Join-Path $PSScriptRoot ('.build/trainer-' + (Get-FileHash $patch).Hash.Substring(0,12))
if (!(Test-Path $work)) {
    git -C $base worktree add --detach $work $revision
    if ($LASTEXITCODE) { throw 'Could not prepare clean SDK worktree' }
}
$base = $work
git -C $base apply --reverse --check --quiet $patch 2>$null
if ($LASTEXITCODE) {
    git -C $base apply $patch
    if ($LASTEXITCODE) { throw 'Firmware patch failed' }
}
Copy-Item (Join-Path $PSScriptRoot 'firmware/trainer.inc') (Join-Path $base 'app/trainer.inc')
Copy-Item (Join-Path $PSScriptRoot 'firmware/practice_bank.inc') (Join-Path $base 'app/practice_bank.inc')
& (Join-Path $base 'sdk/Build.ps1') -FirmwareOnly -Toolchain $Toolchain
$out = Join-Path $PSScriptRoot 'firmware/vocal-trainer.fwsc'
$package = Join-Path $base 'build/dx7/generated/FM1_OFFICIAL_OPEN.fwsc'
# This pinned SDK starts flash.bin at UFW byte 1024. Its .fwsc wrapper
# inserts 20 identity bytes before that point (see sdk/Package.cs::Wrap).
$bytes = [IO.File]::ReadAllBytes($package)
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $boot = [BitConverter]::ToString($sha.ComputeHash($bytes, 1044, 0x4000)).Replace('-', '')
} finally { $sha.Dispose() }
if ($boot -ne '2981ccf8d12a132c82d8b5e959c2d27d62f13bc51419225cacc87a6e82d58171') {
    throw 'Packaged boot area differs from the unmodified official FM1 Open reference.'
}
Copy-Item $package $out
Get-FileHash $out
