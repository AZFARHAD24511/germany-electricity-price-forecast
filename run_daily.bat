@echo off
cd /d D:\projects\germany-electricity-price-forecast-v2-fixed-realdata

if not exist logs mkdir logs
if not exist outputs\figures mkdir outputs\figures
if not exist outputs\forecasts mkdir outputs\forecasts
if not exist reports\figures mkdir reports\figures
if not exist reports\metrics mkdir reports\metrics

echo ==== %date% %time% START ==== >> logs\daily_windows.log

rem 1) data update + live forecast + live scoring (time-critical: must run before the 12:00 CET gate)
py scripts\run_daily_forecast.py >> logs\daily_windows.log 2>&1

rem 2) add the newest complete delivery day to the retrospective evaluation, rebuild README sections and figures
py scripts\run_rolling_eval.py --incremental >> logs\daily_windows.log 2>&1

rem 3) publish
git add outputs\forecasts\*.csv outputs\figures\*.png README.md >> logs\daily_windows.log 2>&1
git add -f reports\figures\rolling_eval.png reports\figures\ablation_mae.png reports\metrics\rolling_eval.csv >> logs\daily_windows.log 2>&1
git commit -m "chore: daily forecast and evaluation update" >> logs\daily_windows.log 2>&1
git pull --rebase --autostash origin main >> logs\daily_windows.log 2>&1
git push origin main >> logs\daily_windows.log 2>&1

echo ==== %date% %time% END ==== >> logs\daily_windows.log
