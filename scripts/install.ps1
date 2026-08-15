param(
  [Alias("Profile")]
  [ValidateSet("global", "project", "server")]
  [string]$SetupProfile = $env:MNEME_SETUP_PROFILE,
  [switch]$GlobalMemory,
  [switch]$ProjectMemory,
  [switch]$ServerOnly,
  [string]$EnvFile = $env:MNEME_ENV_FILE,
  [string]$InstallDir = $env:MNEME_INSTALL_DIR,
  [string]$VenvDir = $env:MNEME_VENV_DIR,
  [switch]$Editable,
  [switch]$NoEmbeddings,
  [switch]$NoClientConfig,
  [switch]$NoContinuity,
  [switch]$MemoryOnly,
  [string]$PythonBin = $env:PYTHON_BIN,
  [switch]$Help
)

$ErrorActionPreference = "Stop"

function Show-Usage {
  @"
Mneme Memory MCP Windows installer

Usage:
  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 [-Profile global|project|server] [options]

Mneme installs into a managed user-data directory. Choose a setup profile to
set the memory scope and client configuration. Client configuration is
best-effort.

Setup profiles:
  global   Shared persistent memory in ~/.hermes, with supported client
           configuration, startup context, and local conversation capture.
  project  Project/env-scoped memory from .env, defaulting to a project folder
           under %LOCALAPPDATA%\mneme-memory-mcp\projects. This configures MCP
           clients without installing global memory instructions.
  server   Install the local Mneme server only; print manual config.

Options:
  -Profile VALUE      Select global, project, or server setup.
  -GlobalMemory       Alias for -Profile global.
  -ProjectMemory      Alias for -Profile project.
  -ServerOnly         Alias for -Profile server.
  -EnvFile PATH       .env file for project/env-scoped memory.
  -InstallDir PATH    Managed install directory. Default: %LOCALAPPDATA%\mneme-memory-mcp.
  -VenvDir PATH       Python virtualenv directory. Default: <InstallDir>\venv.
  -Editable           Install Mneme in editable mode for local development.
  -NoEmbeddings       Skip the local semantic-retrieval dependencies.
  -NoClientConfig     Do not modify Codex or Claude MCP configuration.
  -NoContinuity       Do not install global Claude/Codex memory instructions.
  -MemoryOnly         Same as -NoClientConfig -NoContinuity.

Environment:
  MNEME_HOME          Memory home to use. Defaults to HERMES_HOME or ~/.hermes.
  HERMES_HOME         Hermes-compatible memory home.
  MNEME_SETUP_PROFILE global, project, or server.
  MNEME_INSTALL_DIR   Managed install directory.
  MNEME_VENV_DIR      Python virtualenv directory.
  MNEME_DATA_DIR      Mneme data directory. Defaults to %LOCALAPPDATA%\mneme-memory-mcp.
  MNEME_ENV_FILE      .env file for the project profile.
  MNEME_PROJECT_HOME  Default memory home for the project profile.
  MNEME_EDITABLE      Set to 1 for editable local development installs.
  MNEME_INSTALL_EMBEDDINGS  Set to 0 to skip semantic-retrieval dependencies.
  PYTHON_BIN          Python 3.10+ binary to use. Auto-detected when unset.
"@
}

if ($Help) {
  Show-Usage
  exit 0
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectSlug = (Split-Path $Root -Leaf) -replace '[^A-Za-z0-9._-]', '-'
$LocalData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
$DataDir = if ($env:MNEME_DATA_DIR) { $env:MNEME_DATA_DIR } else { Join-Path $LocalData "mneme-memory-mcp" }
if (-not $InstallDir) { $InstallDir = $DataDir }
if (-not $VenvDir) { $VenvDir = Join-Path $InstallDir "venv" }
if (-not $EnvFile) { $EnvFile = Join-Path $Root ".env" }
$ProjectMemoryHome = if ($env:MNEME_PROJECT_HOME) {
  $env:MNEME_PROJECT_HOME
} else {
  Join-Path (Join-Path $DataDir "projects") $ProjectSlug
}
$GlobalMemoryHome = if ($env:MNEME_HOME) {
  $env:MNEME_HOME
} elseif ($env:HERMES_HOME) {
  $env:HERMES_HOME
} else {
  Join-Path $HOME ".hermes"
}

if ($GlobalMemory) { $SetupProfile = "global" }
if ($ProjectMemory) { $SetupProfile = "project" }
if ($ServerOnly) { $SetupProfile = "server" }
function Select-SetupProfile {
  if (-not $script:SetupProfile -and ($env:MNEME_INSTALL_NONINTERACTIVE -eq "1" -or [Console]::IsInputRedirected)) {
    $message = @"
No Mneme setup profile was selected.

Pass one of these profiles explicitly:
  global   shared memory with supported client continuity
  project  project/env-scoped memory from .env
  server   server install only; manual wiring

Example:
  powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile project
"@
    [Console]::Error.WriteLine($message)
    exit 2
  }

  if (-not $script:SetupProfile) {
    Write-Host ""
    Write-Host "Choose a Mneme setup profile:"
    Write-Host ""
    Write-Host "  1) Global persistent memory"
    Write-Host "     Shared memory and continuity hooks for supported clients."
    Write-Host ""
    Write-Host "  2) Project/env-scoped memory"
    Write-Host "     An isolated memory home for this workspace, configured through .env."
    Write-Host ""
    Write-Host "  3) Server only / manual wiring"
    Write-Host "     Installs Mneme locally and prints config without client configuration"
    Write-Host "     or continuity hooks."
    Write-Host ""

    $choice = Read-Host "Select 1, 2, or 3"
    switch ($choice) {
      { $_ -in @("1", "global", "g") } { $script:SetupProfile = "global" }
      { $_ -in @("2", "project", "p", "env") } { $script:SetupProfile = "project" }
      { $_ -in @("3", "server", "s", "manual") } { $script:SetupProfile = "server" }
      default { throw "Unknown setup profile selection: $choice" }
    }
  }
}

Select-SetupProfile

if ($MemoryOnly) {
  $NoClientConfig = $true
  $NoContinuity = $true
}

if ($env:MNEME_EDITABLE -eq "1") {
  $Editable = $true
}
if ($env:MNEME_INSTALL_EMBEDDINGS -eq "0") {
  $NoEmbeddings = $true
}

function Resolve-MnemePath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PathValue,
    [string]$BaseDir = $Root
  )

  if ($PathValue -eq "~") {
    return (Resolve-Path $HOME).Path
  }
  if ($PathValue.StartsWith("~/") -or $PathValue.StartsWith("~\")) {
    return [IO.Path]::GetFullPath((Join-Path $HOME $PathValue.Substring(2)))
  }

  $expanded = [Environment]::ExpandEnvironmentVariables($PathValue)
  if ([IO.Path]::IsPathRooted($expanded)) {
    return [IO.Path]::GetFullPath($expanded)
  }
  return [IO.Path]::GetFullPath((Join-Path $BaseDir $expanded))
}

function Test-PythonVersion {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command,
    [string[]]$CommandArgs = @()
  )

  try {
    & $Command @CommandArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Find-Python {
  if ($PythonBin) {
    if (Test-PythonVersion -Command $PythonBin) {
      return [pscustomobject]@{ Command = $PythonBin; Args = @(); Display = $PythonBin }
    }
    throw "PYTHON_BIN does not point to Python 3.10 or newer: $PythonBin"
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python -and (Test-PythonVersion -Command $python.Source)) {
    return [pscustomobject]@{ Command = $python.Source; Args = @(); Display = $python.Source }
  }

  $python3 = Get-Command python3 -ErrorAction SilentlyContinue
  if ($python3 -and (Test-PythonVersion -Command $python3.Source)) {
    return [pscustomobject]@{ Command = $python3.Source; Args = @(); Display = $python3.Source }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py -and (Test-PythonVersion -Command $py.Source -CommandArgs @("-3"))) {
    return [pscustomobject]@{ Command = $py.Source; Args = @("-3"); Display = "$($py.Source) -3" }
  }

  throw "Python 3.10 or newer is required. Install Python or set PYTHON_BIN."
}

function Invoke-Python {
  param(
    [Parameter(Mandatory = $true)]
    [pscustomobject]$Python,
    [Parameter(Mandatory = $true)]
    [string[]]$PythonArgs
  )

  & $Python.Command @($Python.Args + $PythonArgs)
}

function Invoke-Optional {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Action
  )

  Write-Host "==> $Label"
  try {
    & $Action
  } catch {
    Write-Warning "$Label failed: $($_.Exception.Message). Continuing."
  }
}

function Write-Utf8File {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Text
  )

  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Add-Utf8File {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Text
  )

  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::AppendAllText($Path, $Text, $encoding)
}

function Read-EnvMemoryHome {
  param([Parameter(Mandatory = $true)][string]$PathValue)

  if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
    return $null
  }

  $values = @{}
  foreach ($raw in Get-Content -LiteralPath $PathValue -Encoding UTF8) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith("#")) {
      continue
    }
    if ($line -match '^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $key = $Matches[1]
      $value = $Matches[2].Trim()
      if ($value.Length -ge 2 -and $value[0] -eq $value[$value.Length - 1] -and ($value[0] -eq "'" -or $value[0] -eq '"')) {
        $value = $value.Substring(1, $value.Length - 2)
      }
      $values[$key] = $value
    }
  }

  $selected = if ($values.ContainsKey("MNEME_HOME")) { $values["MNEME_HOME"] } elseif ($values.ContainsKey("HERMES_HOME")) { $values["HERMES_HOME"] } else { $null }
  if (-not $selected) {
    return $null
  }

  return Resolve-MnemePath -PathValue $selected -BaseDir (Split-Path $PathValue -Parent)
}

function Ensure-ProjectEnv {
  $script:EnvFile = Resolve-MnemePath -PathValue $script:EnvFile
  $script:ProjectMemoryHome = Resolve-MnemePath -PathValue $script:ProjectMemoryHome
  New-Item -ItemType Directory -Force -Path (Split-Path $script:EnvFile -Parent) | Out-Null

  if (-not (Test-Path -LiteralPath $script:EnvFile -PathType Leaf)) {
    Write-Utf8File -Path $script:EnvFile -Text "# Mneme project-scoped memory`nMNEME_HOME=$script:ProjectMemoryHome`n"
    return
  }

  if (-not (Read-EnvMemoryHome -PathValue $script:EnvFile)) {
    Add-Utf8File -Path $script:EnvFile -Text "`n# Mneme project-scoped memory`nMNEME_HOME=$script:ProjectMemoryHome`n"
  }
}

function Test-CommandRunnable {
  param([Parameter(Mandatory = $true)][string]$Command)

  try {
    & $Command --version *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Configure-Clients {
  if ($NoClientConfig) {
    Write-Host "==> Skipping Codex/Claude MCP configuration."
    return
  }

  $codex = Get-Command codex -ErrorAction SilentlyContinue
  if ($codex -and (Test-CommandRunnable "codex")) {
    try {
      & codex mcp remove mneme_memory *> $null
    } catch {
    }
    $args = @("mcp", "add")
    if ($script:McpStaticEnv) {
      $args += @("--env", "MNEME_HOME=$script:HermesHome")
    }
    $args += @("mneme_memory", "--", $script:McpCommand)
    $args += $script:McpArgs
    Invoke-Optional "Configuring Codex MCP server: mneme_memory" { & codex @args }
  } elseif ($codex) {
    Write-Host "==> Codex CLI was found but could not run; skipping Codex MCP configuration."
  } else {
    Write-Host "==> Codex CLI not found; skipping Codex MCP configuration."
  }

  $claude = Get-Command claude -ErrorAction SilentlyContinue
  if ($claude -and (Test-CommandRunnable "claude")) {
    try {
      & claude mcp remove mneme-memory *> $null
    } catch {
    }
    $args = @("mcp", "add", "-s", "user", "mneme-memory")
    if ($script:McpStaticEnv) {
      $args += @("-e", "MNEME_HOME=$script:HermesHome")
    }
    $args += @("--", $script:McpCommand)
    $args += $script:McpArgs
    Invoke-Optional "Configuring Claude Code MCP server: mneme-memory" { & claude @args }
  } elseif ($claude) {
    Write-Host "==> Claude CLI was found but could not run; skipping Claude MCP configuration."
  } else {
    Write-Host "==> Claude CLI not found; skipping Claude MCP configuration."
  }
}

function Install-Continuity {
  if ($NoContinuity) {
    Write-Host "==> Skipping client continuity installation."
    return
  }

  Invoke-Optional "Installing Mneme client continuity for Codex and Claude" {
    & $script:VenvPython -m mneme_memory_mcp.continuity install --memory-home $script:HermesHome --bin-dir $script:ScriptsDir
  }
}

function ConvertTo-JsonString {
  param([string]$Value)
  return ($Value | ConvertTo-Json -Compress)
}

function ConvertTo-JsonArray {
  param([string[]]$Values)
  return (@($Values) | ConvertTo-Json -Compress)
}

function ConvertTo-TomlLiteral {
  param([string]$Value)
  return "'" + ($Value -replace "'", "''") + "'"
}

function ConvertTo-TomlArray {
  param([string[]]$Values)
  if (-not $Values -or $Values.Count -eq 0) {
    return "[]"
  }
  return "[" + (($Values | ForEach-Object { ConvertTo-TomlLiteral $_ }) -join ", ") + "]"
}

function Print-ManualConfig {
  Write-Host ""
  Write-Host "==> Mneme configuration"
  Write-Host ""
  Write-Host "Selected profile: $SetupProfile"
  Write-Host ""

  $commandJson = ConvertTo-JsonString $McpCommand
  $argsJson = ConvertTo-JsonArray $McpArgs
  $commandToml = ConvertTo-TomlLiteral $McpCommand
  $argsToml = ConvertTo-TomlArray $McpArgs

  if ($McpStaticEnv) {
    $homeJson = ConvertTo-JsonString $HermesHome
    $homeToml = ConvertTo-TomlLiteral $HermesHome
    @"
Codex:

[mcp_servers.mneme_memory]
command = $commandToml
args = $argsToml
startup_timeout_sec = 120

[mcp_servers.mneme_memory.env]
MNEME_HOME = $homeToml

Claude Code:

{
  "mcpServers": {
    "mneme-memory": {
      "type": "stdio",
      "command": $commandJson,
      "args": $argsJson,
      "env": {
        "MNEME_HOME": $homeJson
      }
    }
  }
}
"@
  } else {
    @"
Codex:

[mcp_servers.mneme_memory]
command = $commandToml
args = $argsToml
startup_timeout_sec = 120

Claude Code:

{
  "mcpServers": {
    "mneme-memory": {
      "type": "stdio",
      "command": $commandJson,
      "args": $argsJson
    }
  }
}
"@
  }

  Write-Host ""
  Write-Host "Restart Codex and Claude Code after install so MCP configuration reloads."
}

Write-Host "==> Mneme Memory MCP"
Write-Host "repo: $Root"

$Python = Find-Python

$InstallDir = Resolve-MnemePath -PathValue $InstallDir
$VenvDir = Resolve-MnemePath -PathValue $VenvDir

switch ($SetupProfile) {
  "global" {
    $HermesHome = Resolve-MnemePath -PathValue $GlobalMemoryHome
    $McpStaticEnv = $true
  }
  "project" {
    Ensure-ProjectEnv
    $HermesHome = Read-EnvMemoryHome -PathValue $EnvFile
    if (-not $HermesHome) {
      throw "Could not resolve MNEME_HOME or HERMES_HOME from $EnvFile"
    }
    $NoContinuity = $true
    $McpStaticEnv = $false
  }
  "server" {
    $HermesHome = Resolve-MnemePath -PathValue $GlobalMemoryHome
    $NoClientConfig = $true
    $NoContinuity = $true
    $McpStaticEnv = $true
  }
}

$installRoot = [IO.Path]::GetFullPath($InstallDir).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
$venvRoot = [IO.Path]::GetFullPath($VenvDir).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
$containedPrefix = $installRoot + [IO.Path]::DirectorySeparatorChar
if ($venvRoot -eq $installRoot -or -not $venvRoot.StartsWith($containedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing venv outside the managed install directory: $VenvDir"
}
if ((Test-Path -LiteralPath $VenvDir -PathType Container) -and -not (Test-Path -LiteralPath (Join-Path $VenvDir "pyvenv.cfg") -PathType Leaf)) {
  $existingEntry = Get-ChildItem -LiteralPath $VenvDir -Force | Select-Object -First 1
  if ($existingEntry) {
    throw "Refusing to clear a non-venv directory: $VenvDir"
  }
}

$ScriptsDir = Join-Path $VenvDir "Scripts"
$VenvPython = Join-Path $ScriptsDir "python.exe"
if ($McpStaticEnv) {
  $McpCommand = $VenvPython
  $McpArgs = @("-m", "mneme_memory_mcp")
} else {
  $McpCommand = $VenvPython
  $McpArgs = @("-m", "mneme_memory_mcp.env_launcher", "--env-file", $EnvFile, "--default-home", $ProjectMemoryHome)
}

$env:MNEME_HOME = $HermesHome
$env:HERMES_HOME = $HermesHome

Write-Host "profile: $SetupProfile"
Write-Host "install dir: $InstallDir"
Write-Host "venv dir: $VenvDir"
Write-Host "memory home: $HermesHome"
if ($SetupProfile -eq "project") {
  Write-Host "env file: $EnvFile"
}
Write-Host "python: $($Python.Display)"
Write-Host "semantic embeddings: $(if ($NoEmbeddings) { 'disabled' } else { 'enabled' })"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Invoke-Python -Python $Python -PythonArgs @("-m", "venv", "--clear", $VenvDir)
& $VenvPython -m pip install --upgrade pip
$PackageSpec = if ($NoEmbeddings) { $Root } else { "$Root[embeddings]" }
if ($Editable) {
  & $VenvPython -m pip install -e $PackageSpec
} else {
  & $VenvPython -m pip install $PackageSpec
}
if (-not $NoEmbeddings) {
  Invoke-Optional "Preparing pinned local embedding model" {
    & $VenvPython -m mneme_memory_mcp.cli embeddings prepare
  }
}

$MemoryDir = Join-Path $HermesHome "memories"
New-Item -ItemType Directory -Force -Path $MemoryDir | Out-Null
$UserMemory = Join-Path $MemoryDir "USER.md"
$SharedMemory = Join-Path $MemoryDir "MEMORY.md"
if (-not (Test-Path -LiteralPath $UserMemory -PathType Leaf)) {
  Write-Utf8File -Path $UserMemory -Text "# USER.md`n"
}
if (-not (Test-Path -LiteralPath $SharedMemory -PathType Leaf)) {
  Write-Utf8File -Path $SharedMemory -Text "# MEMORY.md`n"
}

Write-Host ""
Install-Continuity
Write-Host ""
Configure-Clients
Write-Host ""
& $VenvPython -m mneme_memory_mcp.doctor

Print-ManualConfig
