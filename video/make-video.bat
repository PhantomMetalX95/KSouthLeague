@echo off
REM Double-click to make a gameweek video. Put your site's data address in api-address.txt first.
cd /d "%~dp0"
set /p API=<api-address.txt
set /p WEEK=Gameweek number (press Enter for the latest): 
if "%WEEK%"=="" (
  python make_video.py --api %API% --out gameweek-latest.mp4
) else (
  python make_video.py --api %API% --week %WEEK% --out gameweek-%WEEK%.mp4
)
echo.
pause
