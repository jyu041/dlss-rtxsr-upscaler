param([Parameter(Mandatory=$true)][string]$ProviderPath,[switch]$ValidateOnly)
$ErrorActionPreference='Stop'
$pathHelper=Join-Path $PSScriptRoot 'provider_path.ps1';. $pathHelper
$expectedHash='15D85827A2D4437713CD66F1090297633384F5A1867C319406D2B1F37BE83FB5';$expectedVersion=@{Major=310;Minor=2;Build=1;Private=0}
$WorkerPath=Join-Path $PSScriptRoot 'bin\dlssg_ampere_experiment.exe'
function Quote-WindowsArgument([string]$value){return '"'+$value+'"'}
Write-Host "POWERSHELL_VERSION=$($PSVersionTable.PSVersion)"
if($PSVersionTable.PSVersion.Major -ne 5){throw 'Windows PowerShell 5.x is required for this compatibility path'}
if(-not (Test-AbsoluteWindowsPath $ProviderPath)){throw 'ProviderPath must be absolute'}
$normalizedProviderPath=Normalize-WindowsFullPath $ProviderPath
$normalizedApprovedProviderPath=Normalize-WindowsFullPath $ApprovedProviderPath
Write-Host "PROVIDER_PATH_NORMALIZED=$normalizedProviderPath"
Write-Host "PROVIDER_PATH_APPROVED_NORMALIZED=$normalizedApprovedProviderPath"
if(-not (Test-ApprovedProviderPath $ProviderPath $ApprovedProviderPath)){
  Write-Host 'PROVIDER_EXACT_PATH_GATE=REJECT'
  throw "provider path is not approved; supplied normalized path: $normalizedProviderPath; required approved path: $normalizedApprovedProviderPath"
}
Write-Host 'PROVIDER_EXACT_PATH_GATE=PASS'
if(-not (Test-Path -LiteralPath $ProviderPath -PathType Leaf)){throw "provider file does not exist: $ProviderPath"}
$out=Join-Path (Join-Path $PSScriptRoot '..\..\runtime\audit') 'dlssg-ampere-experiment';New-Item -ItemType Directory -Force $out|Out-Null
$start=Get-Date;$startUtc=$start.ToUniversalTime().ToString('o')
if((Get-FileHash -LiteralPath $ProviderPath -Algorithm SHA256).Hash -ne $expectedHash){throw 'provider hash mismatch'}
$signature=Get-AuthenticodeSignature -LiteralPath $ProviderPath;if($signature.Status -ne 'Valid'){throw "Authenticode status is $($signature.Status)"}
$versionInfo=[System.Diagnostics.FileVersionInfo]::GetVersionInfo($ProviderPath)
$rawVersion=$versionInfo.FileVersion
$numericVersion="{0}.{1}.{2}.{3}" -f $versionInfo.FileMajorPart,$versionInfo.FileMinorPart,$versionInfo.FileBuildPart,$versionInfo.FilePrivatePart
Write-Host "PROVIDER_FILEVERSION_RAW=$rawVersion"
Write-Host "PROVIDER_VERSION_NUMERIC=$numericVersion"
if($versionInfo.FileMajorPart -ne $expectedVersion.Major -or $versionInfo.FileMinorPart -ne $expectedVersion.Minor -or $versionInfo.FileBuildPart -ne $expectedVersion.Build -or $versionInfo.FilePrivatePart -ne $expectedVersion.Private){throw "provider numeric version is $numericVersion"}
Write-Host 'PROVIDER_HASH_GATE=PASS'
Write-Host 'PROVIDER_SIGNATURE_GATE=PASS'
Write-Host 'PROVIDER_VERSION_GATE=PASS'
if(-not (Test-Path -LiteralPath $WorkerPath -PathType Leaf)){throw "expected experiment worker missing: $WorkerPath"}
if($ValidateOnly){
  $psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName=$WorkerPath;$psi.WorkingDirectory=Split-Path $WorkerPath;$psi.UseShellExecute=$false;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true;$psi.Arguments='--serve --provider '+(Quote-WindowsArgument $ProviderPath)
  Write-Host 'VALIDATE_ONLY=true';Write-Host "WORKER_PATH=$($psi.FileName)";Write-Host "WORKER_ARGUMENTS=$($psi.Arguments)";Write-Host 'ARGUMENTLIST_USED=false';Write-Host 'BINARY_STDIN=StandardInput.BaseStream';Write-Host 'WORKER_STARTED=false';exit 0
}
$inputFile=Join-Path $out 'synthetic-256x256.bin';$producer=Join-Path $PSScriptRoot '..\..\tools\dlssg_synthetic_input.py';& python $producer --output $inputFile --validate;if($LASTEXITCODE -ne 0){throw 'synthetic input producer validation failed'}
$before=Join-Path $out 'nvidia-smi-before.txt';$after=Join-Path $out 'nvidia-smi-after.txt';nvidia-smi 2>&1|Set-Content -LiteralPath $before
$providers=@('nvlddmkm','Display','WHEA-Logger','Kernel-Power');Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$start.AddMinutes(-10)} -ErrorAction SilentlyContinue|Where-Object {$providers -contains $_.ProviderName}|Export-Clixml (Join-Path $out 'events-baseline.xml')
$psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName=$WorkerPath;$psi.WorkingDirectory=Split-Path $WorkerPath;$psi.UseShellExecute=$false;$psi.RedirectStandardInput=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true;$psi.Arguments='--serve --provider '+(Quote-WindowsArgument $ProviderPath);Write-Host "WORKER_PATH=$($psi.FileName)";Write-Host "WORKER_ARGUMENTS=$($psi.Arguments)"
$p=New-Object Diagnostics.Process;$p.StartInfo=$psi;if(-not $p.Start()){throw 'failed to launch intended experiment worker'};Write-Host "WORKER_PID=$($p.Id)"
$outTask=$p.StandardOutput.BaseStream.CopyToAsync([IO.File]::Open((Join-Path $out 'worker-output.bin'),[IO.FileMode]::Create));$errTask=$p.StandardError.ReadToEndAsync()
try{$bytes=[IO.File]::ReadAllBytes($inputFile);$p.StandardInput.BaseStream.Write($bytes,0,$bytes.Length);$p.StandardInput.BaseStream.Flush();$p.StandardInput.Close();if(-not $p.WaitForExit(60000)){throw 'outer watchdog timeout'}}catch{if(-not $p.HasExited){$p.Kill()};throw}
$outTask.GetAwaiter().GetResult();$stderr=$errTask.GetAwaiter().GetResult();$stderr|Set-Content (Join-Path $out 'worker-stderr.txt');nvidia-smi 2>&1|Set-Content -LiteralPath $after
Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$start}|Where-Object {$providers -contains $_.ProviderName}|Export-Clixml (Join-Path $out 'events-since-start.xml')
[pscustomobject]@{startUtc=$startUtc;endUtc=(Get-Date).ToUniversalTime().ToString('o');workerExit=$p.ExitCode;workerPid=$p.Id;provider=$ProviderPath;sha256=$expectedHash;version=$numericVersion}|ConvertTo-Json|Set-Content (Join-Path $out 'run.json')
