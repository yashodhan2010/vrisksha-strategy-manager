@echo off
cd /d %~dp0\..
python -m app.main backtest --years 10
pause

