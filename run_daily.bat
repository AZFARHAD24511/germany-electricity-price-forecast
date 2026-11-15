@echo off
cd /d D:\projects\germany-electricity-price-forecast

if not exist logs mkdir logs
if not exist outputs\figures mkdir outputs\figures
if not exist outputs\forecasts mkdir outputs\forecasts

echo ==== %date% %time% START ==== >> logs\daily_windows.log

py scripts\run_daily_forecast.py >> logs\daily_windows.log 2>&1

git add outputs\forecasts\*.csv outputs\figures\*.png README.md
git commit -m "chore: daily forecast update" >> logs\daily_windows.log 2>&1
git push origin main >> logs\daily_windows.log 2>&1

echo ==== %date% %time% END ==== >> logs\daily_windows.log
