@echo off
rem Handbuilt's own Python, for Windows without Git Bash.
rem
rem Runs Python with the arguments given. The first time, it downloads the build
rem named in tools\python-dist.lock, checks it against the SHA-256 recorded there,
rem and unpacks it into Handbuilt's private folder. It needs no installer, no
rem administrator password, and changes nothing else on the computer.
rem
rem   handbuilt-python --where     print the path to this Python and stop
rem   handbuilt-python script.py   run a script
setlocal EnableExtensions DisableDelayedExpansion

set "LOCK=%~dp0..\tools\python-dist.lock"
if not exist "%LOCK%" (
    echo handbuilt-python: tools\python-dist.lock is missing from the plugin. 1>&2
    exit /b 2
)

rem A short folder: the Claude desktop app redirects AppData to a deep one,
rem and Windows then refuses the long file paths inside.
set "ROOT=%USERPROFILE%\.handbuilt\runtime"
if defined HANDBUILT_RUNTIME_HOME set "ROOT=%HANDBUILT_RUNTIME_HOME%"

set "TAG="
set "SHA="
set "URL="
for /f "usebackq eol=# tokens=1,2,3" %%a in ("%LOCK%") do (
    if "%%a"=="release" set "TAG=%%b"
    if "%%a"=="windows-x86_64" set "SHA=%%b"
    if "%%a"=="windows-x86_64" set "URL=%%c"
)
if not defined TAG goto nolock
if not defined SHA goto nolock
if not defined URL goto nolock

set "DIST=%ROOT%\python-dist\%TAG%"
set "PY=%DIST%\python\python.exe"
if exist "%PY%" goto run

set "WORK=%ROOT%\python-dist\.tmp.%RANDOM%%RANDOM%"
mkdir "%WORK%\x" || goto failed
echo Handbuilt is getting its own copy of Python. This happens once and takes about a minute. 1>&2
"%SystemRoot%\System32\curl.exe" --proto =https --tlsv1.2 -fsSL --connect-timeout 20 --speed-limit 20000 --speed-time 20 --retry 4 -C - -o "%WORK%\python.tar.gz" "%URL%"
if errorlevel 1 goto nodownload

set "GOT="
for /f "skip=1 tokens=* delims=" %%h in ('""%SystemRoot%\System32\certutil.exe" -hashfile "%WORK%\python.tar.gz" SHA256"') do if not defined GOT set "GOT=%%h"
if not defined GOT goto badsum
set "GOT=%GOT: =%"
if /i not "%GOT%"=="%SHA%" goto badsum

"%SystemRoot%\System32\tar.exe" -xzf "%WORK%\python.tar.gz" -C "%WORK%\x"
if errorlevel 1 goto failed
if not exist "%WORK%\x\python\python.exe" goto failed
rem Another run may have finished first. Keep whichever copy is already there.
if not exist "%DIST%" move "%WORK%\x" "%DIST%" >nul
rmdir /s /q "%WORK%" 2>nul
if not exist "%PY%" goto failed

:run
if "%~1"=="--where" (
    echo %PY%
    exit /b 0
)
rem UTF-8 mode: Windows would otherwise read and write text in an older encoding.
"%PY%" -X utf8 %*
exit /b %errorlevel%

:nolock
echo handbuilt-python: tools\python-dist.lock has no build for Windows. 1>&2
exit /b 2

:nodownload
rmdir /s /q "%WORK%" 2>nul
echo handbuilt-python: the download failed. Check the internet connection and try again. 1>&2
exit /b 1

:badsum
rmdir /s /q "%WORK%" 2>nul
echo handbuilt-python: the download did not match its recorded checksum, so it was not used. 1>&2
exit /b 1

:failed
if defined WORK rmdir /s /q "%WORK%" 2>nul
echo handbuilt-python: Python could not be unpacked into Handbuilt's folder. 1>&2
exit /b 1
