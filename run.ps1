Param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]] $Args
)

$VenvDir = ".venv"
$ReqFile = "requirements.txt"

# Find Python
$py = (Get-Command python -ErrorAction SilentlyContinue).Path
if (-not $py) {
  Write-Error "No python found in PATH. Install Python 3."
  exit 1
}

# Create venv if missing
if (-not (Test-Path $VenvDir)) {
  Write-Output "Creating virtualenv in $VenvDir..."
  & $py -m venv $VenvDir
}

$venvPy = Join-Path $VenvDir "Scripts\python.exe"
$venvPip = Join-Path $VenvDir "Scripts\pip.exe"

# upgrade pip
& $venvPy -m pip install --upgrade pip setuptools wheel | Out-Null

# If requirements exist, compare file hash and install only when changed
if (Test-Path $ReqFile) {
  $reqHash = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
  $hashFile = Join-Path $VenvDir ".req_hash"
  $prevHash = if (Test-Path $hashFile) { Get-Content $hashFile -Raw } else { "" }

  if ($reqHash -ne $prevHash) {
    Write-Output "Installing requirements from $ReqFile..."
    & $venvPip install -r $ReqFile
    $reqHash | Out-File -Encoding ascii $hashFile
  } else {
    Write-Output "requirements.txt unchanged - skipping pip install."
  }
}

# Run
& $venvPy -m drift @Args
