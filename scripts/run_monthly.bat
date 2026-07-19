@echo off
cd /d %~dp0\..
python -m app.main monthly-run --strategy-profile strategies/dual-momentum/strategy_profile.json
