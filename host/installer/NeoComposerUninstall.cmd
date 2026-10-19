@echo off
setlocal
title Neo Composer Native Enhancement
node "%~dp0setup.mjs" rollback
set "code=%errorlevel%"
echo.
echo No window reload or backend restart was performed.
if not defined NEO_COMPOSER_NONINTERACTIVE pause
exit /b %code%
