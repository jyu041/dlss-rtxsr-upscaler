param(
    [Parameter(Mandatory = $true)] [string] $Output,
    [string] $SourceRoot = (Get-Location).Path
)
$ErrorActionPreference = "Stop"
python "$SourceRoot\tools\build_portable_candidate.py" --output $Output --source-root $SourceRoot
