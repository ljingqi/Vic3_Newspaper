@echo off
chcp 936 >nul
title V3Journal 报纸杂志监控（新档）
cd /d "%~dp0"
python journal_save.py watch
echo.
echo 程序已退出，按任意键关闭窗口。
pause >nul
