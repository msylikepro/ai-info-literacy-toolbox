@echo off
setlocal
chcp 65001 >nul
title 网站检测工具
set "CHECKER_NODE="
for /f "delims=" %%N in ('where node.exe 2^>nul') do if not defined CHECKER_NODE set "CHECKER_NODE=%%N"
if not defined CHECKER_NODE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" set "CHECKER_NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not defined CHECKER_NODE (
    echo 未找到 Node.js，请安装 Node.js 22 或更新版本后再启动。
    pause
    exit /b 1
)
"%CHECKER_NODE%" -e "if(Number(process.versions.node.split('.')[0])<22)process.exit(1)"
if errorlevel 1 (
    echo 当前 Node.js 版本过低，需要 Node.js 22 或更新版本。
    pause
    exit /b 1
)
echo 正在前台启动网址检测工具，请保持此窗口打开。
"%CHECKER_NODE%" "%~dp0server.cjs"
if errorlevel 1 (
    echo 启动失败，请查看上方的错误信息。
    pause
    exit /b 1
)
endlocal
