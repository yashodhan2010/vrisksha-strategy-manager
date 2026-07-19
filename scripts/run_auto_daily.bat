@echo off
cd /d %~dp0\..
if not exist logs mkdir logs
echo. >> logs\auto_daily.log
echo ===== %date% %time% auto-daily-run ===== >> logs\auto_daily.log
if "%CONDA_ENV_NAME%"=="" set CONDA_ENV_NAME=vrisksha-strategy-manager
if exist "%USERPROFILE%\miniconda3\Scripts\activate.bat" call "%USERPROFILE%\miniconda3\Scripts\activate.bat" %CONDA_ENV_NAME%
if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" call "%USERPROFILE%\anaconda3\Scripts\activate.bat" %CONDA_ENV_NAME%
python -m app.main auto-daily-run --selenium-token >> logs\auto_daily.log 2>&1
