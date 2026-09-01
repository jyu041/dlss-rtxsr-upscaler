@echo off
setlocal
cd /d "%~dp0"
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False
where conda >nul 2>nul || (echo Conda was not found. Run setup.bat first.& exit /b 1)
conda run --no-capture-output -n dlss-rtxsr-upscaler python app.py
