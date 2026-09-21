@echo off
setlocal
echo(%*| findstr /C:"-i -" >nul
if not errorlevel 1 exit /b 17
if defined NVE_FFMPEG_PATH (
  set "NVE_SOAK_FFMPEG=%NVE_FFMPEG_PATH%"
) else (
  for /f "delims=" %%F in ('where ffmpeg 2^>nul') do if not defined NVE_SOAK_FFMPEG set "NVE_SOAK_FFMPEG=%%F"
)
if not defined NVE_SOAK_FFMPEG (
  echo FFmpeg was not found. Set NVE_FFMPEG_PATH or add ffmpeg to PATH. 1>&2
  exit /b 1
)
"%NVE_SOAK_FFMPEG%" %*
exit /b %errorlevel%
