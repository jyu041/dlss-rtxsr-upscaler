$ApprovedProviderPath = 'C:\Windows\System32\DriverStore\FileRepository\nvmdi.inf_amd64_72f1798f54a8a57a\nvngx_dlssg.dll'

function Test-AbsoluteWindowsPath([string]$Path) {
  return $Path -match '^(?:[A-Za-z]:[\\/]|\\\\)'
}

function Normalize-WindowsFullPath([string]$Path) {
  return [System.IO.Path]::GetFullPath($Path)
}

function Test-ApprovedProviderPath([string]$Path, [string]$ApprovedPath) {
  $normalizedPath = Normalize-WindowsFullPath $Path
  $normalizedApprovedPath = Normalize-WindowsFullPath $ApprovedPath
  return [System.StringComparer]::OrdinalIgnoreCase.Equals($normalizedPath, $normalizedApprovedPath)
}
