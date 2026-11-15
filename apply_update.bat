@echo off
setlocal
set "TARGET=D:\projects\germany-electricity-price-forecast-v2-fixed-realdata"

if not exist "%TARGET%\data\raw" (
  echo.
  echo ERROR: project folder not found:
  echo   %TARGET%
  echo Open apply_update.bat in Notepad and fix the TARGET path in line 3.
  pause
  exit /b 1
)

echo.
echo [1/3] Making backups (src_backup, scripts_backup, README_backup.md, run_daily_backup.bat) ...
xcopy "%TARGET%\src" "%TARGET%\src_backup\" /E /I /Y >nul
xcopy "%TARGET%\scripts" "%TARGET%\scripts_backup\" /E /I /Y >nul
copy /Y "%TARGET%\README.md" "%TARGET%\README_backup.md" >nul
copy /Y "%TARGET%\run_daily.bat" "%TARGET%\run_daily_backup.bat" >nul

echo [2/3] Copying new code, README and run_daily.bat (your data and outputs are NOT touched) ...
xcopy "%~dp0src" "%TARGET%\src\" /E /I /Y >nul
xcopy "%~dp0scripts" "%TARGET%\scripts\" /E /I /Y >nul
copy /Y "%~dp0README.md" "%TARGET%\README.md" >nul
copy /Y "%~dp0run_daily.bat" "%TARGET%\run_daily.bat" >nul

echo [3/3] Building figures and README results from your own CSV files ...
cd /d "%TARGET%"
py scripts\update_readme_results.py

echo.
echo DONE.
pause
