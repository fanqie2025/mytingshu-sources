@echo off
chcp 65001 >nul
setlocal
set "JAR=%~dp0sources_by_xmd.jar"
set "DIR=/sdcard/Android/data/com.github.eprendre.tingshu/files/jars"

set "ADB="
where adb >nul 2>nul && set "ADB=adb"
if not defined ADB if exist "D:\LDPlayer9\adb.exe" set "ADB=D:\LDPlayer9\adb.exe"
if not defined ADB if exist "C:\platform-tools\adb.exe" set "ADB=C:\platform-tools\adb.exe"
if not defined ADB goto NOADB

echo 使用 adb: %ADB%
"%ADB%" devices
echo.
echo 正在推送 sources_by_xmd.jar 到手机 ...
"%ADB%" push "%JAR%" %DIR%
if errorlevel 1 goto PUSHFAIL
"%ADB%" shell chmod 444 %DIR%/sources_by_xmd.jar
"%ADB%" shell ls -l %DIR%
echo.
echo ============================================================
echo 安装完成，接下来在手机上：
echo   1. 强行停止或重启「我的听书」App
echo   2. 左侧菜单 - 源管理，会出现「离线源: 自建修复源」
echo   3. 点进去，打开「22听书」开关
echo   4. 回首页搜索关键词，底部出现「点击验证 N 个搜索源」时点它
echo      按提示填一次图片验证码；之后 22听书 即可正常搜索
echo ============================================================
pause
exit /b 0

:NOADB
echo [错误] 没找到 adb.exe。
echo 请安装 Android SDK platform-tools 并把 adb.exe 加入 PATH；
echo 雷电模拟器用户脚本会自动尝试 D:\LDPlayer9\adb.exe。
pause
exit /b 1

:PUSHFAIL
echo.
echo [失败] 推送失败，常见原因：
echo   1. 手机没连上，或没打开「USB 调试」
echo   2. 多台设备时需指定：adb -s 设备号 push ...
echo   3. 目标目录不存在：请先在手机上安装并打开一次「我的听书」
pause
exit /b 1
