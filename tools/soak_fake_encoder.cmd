@echo off
setlocal
echo(%*| findstr /C:"-i -" >nul
if not errorlevel 1 exit /b 17
"C:\Users\mark\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe" %*
exit /b %errorlevel%
