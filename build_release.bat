@echo off
chcp 65001 >nul
echo =========================================
echo    WuWa Hekili v1.0 一键打包发布脚本
echo =========================================

echo.
echo [1/4] 正在使用 PyInstaller 编译主程序 (请耐心等待)...
:: -D: 生成一个文件夹 (更稳定)
:: -w: 无控制台黑框 (纯GUI模式)
:: --uac-admin: 强制要求管理员权限 (解决游戏内无法监听键鼠的问题)
:: -n: 指定生成的 exe 名字
pyinstaller -D -w --uac-admin -n "WuWa_Hekili" main.py

echo.
echo [2/4] 正在组装 Release 文件夹...
:: 创建最终发布文件夹
if exist "WuWa_Hekili_Release_v1" rmdir /s /q "WuWa_Hekili_Release_v1"
mkdir "WuWa_Hekili_Release_v1"

:: 把编译好的核心程序移进去
move dist\WuWa_Hekili\* WuWa_Hekili_Release_v1\ >nul

echo.
echo [3/4] 正在拷贝用户资源与配置...
:: 复制素材文件夹 (/E 包含子目录, /I 目标是目录, /Y 覆盖)
xcopy assets WuWa_Hekili_Release_v1\assets\ /E /I /Y >nul
:: 复制剧本文件夹
xcopy configs WuWa_Hekili_Release_v1\configs\ /E /I /Y >nul
:: 复制说明文档
copy README.md WuWa_Hekili_Release_v1\ >nul

echo.
echo [4/4] 清理编译垃圾...
rmdir /s /q build
rmdir /s /q dist
del WuWa_Hekili.spec

echo.
echo =========================================
echo 🎉 打包完成！
echo 请查看当前目录下的【WuWa_Hekili_Release_v1】文件夹！
echo 你只需要把这个文件夹压缩成 .zip 发给别人即可。
echo =========================================
pause