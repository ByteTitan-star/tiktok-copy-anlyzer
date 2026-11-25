param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    $bundled = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundled) {
        $runtime = $bundled
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $runtime = (Get-Command python).Source
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '请安装 Python 3.12' }
    } else {
        throw '请先安装 Python 3.12，再运行本脚本'
    }
}
& $runtime -c "import importlib.util,sys; sys.exit(1) if not importlib.util.find_spec('pydantic') else None; import pydantic; sys.exit(int(pydantic.__version__.split('.')[0] != '2'))"
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & $runtime -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
    }
    $runtime = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    & $runtime -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '安装 Pydantic 失败' }
}
& $runtime app.py --port $Port

