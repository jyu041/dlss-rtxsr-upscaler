$ErrorActionPreference='Stop'
function Test-ProviderVersionComponents([int]$major,[int]$minor,[int]$build,[int]$private){
  return $major -eq 310 -and $minor -eq 2 -and $build -eq 1 -and $private -eq 0
}
if(-not (Test-ProviderVersionComponents 310 2 1 0)){throw 'expected provider version tuple to accept'}
foreach($case in @(@(309,2,1,0),@(310,3,1,0),@(310,2,2,0),@(310,2,1,1))){
  if(Test-ProviderVersionComponents $case[0] $case[1] $case[2] $case[3]){throw "unexpected provider version tuple acceptance: $($case -join '.')"}
}
Write-Output 'provider version component tests: PASS'
