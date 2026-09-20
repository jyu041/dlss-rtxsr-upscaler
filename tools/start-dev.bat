@echo off
setlocal
cd /d "%~dp0.."
set PYTHONNOUSERSITE=1
set GRADIO_ANALYTICS_ENABLED=False

if exist "%~dp0..\config\source_env.bat" call "%~dp0..\config\source_env.bat"
if not defined NVE_CONDA_ENV if not defined NVE_CONDA_PREFIX set "NVE_CONDA_ENV=dlss-rtxsr-upscaler"
if defined NVE_CONDA_PREFIX (set NVE_CONDA_TARGET=--prefix "%NVE_CONDA_PREFIX%") else (set NVE_CONDA_TARGET=--name "%NVE_CONDA_ENV%")

if defined NVE_CONDA_EXE if not exist "%NVE_CONDA_EXE%" set "NVE_CONDA_EXE="
if not defined NVE_CONDA_EXE for /f "delims=" %%C in ('where conda 2^>nul') do if not defined NVE_CONDA_EXE set "NVE_CONDA_EXE=%%C"
if not defined NVE_CONDA_EXE for %%C in ("%USERPROFILE%\miniconda3\condabin\conda.bat" "%USERPROFILE%\miniconda3\Scripts\conda.exe" "%USERPROFILE%\anaconda3\condabin\conda.bat" "%USERPROFILE%\anaconda3\Scripts\conda.exe" "%LOCALAPPDATA%\miniconda3\condabin\conda.bat" "%LOCALAPPDATA%\anaconda3\condabin\conda.bat" "%ProgramData%\miniconda3\condabin\conda.bat" "%ProgramData%\anaconda3\condabin\conda.bat") do if not defined NVE_CONDA_EXE if exist "%%~C" set "NVE_CONDA_EXE=%%~C"
if not defined NVE_CONDA_EXE (echo Conda was not found. Run setup.bat first.& exit /b 1)

echo Starting developer source environment...
call "%NVE_CONDA_EXE%" run --no-capture-output %NVE_CONDA_TARGET% python app.py
exit /b %errorlevel%
