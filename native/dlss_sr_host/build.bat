@echo off
setlocal
call "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1

cmake -S "%~dp0." -B "%~dp0build" -G Ninja -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 exit /b 1
cmake --build "%~dp0build"
if errorlevel 1 exit /b 1

copy /Y "%~dp0..\..\runtime\audit\dlss5-v3\extracted\bin\runtime\nvngx_dlss.dll" "%~dp0..\..\runtime\dlss-sr-host\nvngx_dlss.dll"
endlocal
