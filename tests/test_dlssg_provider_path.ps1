$ErrorActionPreference='Stop'
$helper=Join-Path $PSScriptRoot '..\native\dlssg_ampere_experiment\provider_path.ps1';. $helper
$approved=$ApprovedProviderPath
function Assert-PathDecision([string]$Name,[string]$Path,[bool]$Expected){
  $actual = (Test-AbsoluteWindowsPath $Path) -and (Test-ApprovedProviderPath $Path $approved)
  if($actual -ne $Expected){throw "$Name expected $Expected but got $actual"}
  Write-Output "$Name=$($(if($actual){'ACCEPT'}else{'REJECT'}))"
}
Assert-PathDecision 'exact approved path' $approved $true
Assert-PathDecision 'case-different exact path' ($approved.ToUpperInvariant()) $true
Assert-PathDecision 'normalized-dot exact path' ($approved.Replace('\nvngx\','\.\nvngx\')) $true
Assert-PathDecision 'different absolute same filename' 'C:\Temp\nvngx_dlssg.dll' $false
Assert-PathDecision 'different DriverStore directory' 'C:\Windows\System32\DriverStore\FileRepository\some_other_directory\nvngx_dlssg.dll' $false
Assert-PathDecision 'relative path' '.\nvngx_dlssg.dll' $false
Write-Output 'provider path comparison tests: PASS'
