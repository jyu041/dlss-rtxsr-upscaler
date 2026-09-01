@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
where conda >nul 2>nul || (echo Miniconda or Anaconda is required.& exit /b 1)
conda env update -n dlss-rtxsr-upscaler -f environment.yml --prune || exit /b 1
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pip check
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m src.core.diagnostics
echo Environment ready: dlss-rtxsr-upscaler
