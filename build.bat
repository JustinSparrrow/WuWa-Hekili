@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem  WuWa Hekili 打包脚本
rem
rem  用法:
rem      build.bat              正常打包
rem      build.bat --no-zip     只出文件夹, 不打 zip
rem      build.bat --keep-temp  保留 build/ 与 .spec 方便排查
rem
rem  前置条件:
rem      - 在 conda 环境 wuwahekili 里运行 (需要 PyInstaller)
rem      - 已执行 pip install -r requirements.txt
rem
rem  产物布局:
rem      WuWa_Hekili_v2.3\
rem      |- WuWa_Hekili.exe          主程序 (素材工坊已是主菜单第四个入口)
rem      |- config.json             首次运行时自动生成, 包里不预置
rem      |- configs\routines\       剧本, 用户自己写的轴放这里
rem      \- _internal\
rem         |- assets\characters\   角色素材
rem         |- assets\input\        按键提示图
rem         \- tools\factory\       素材工坊的 ROI 配置
rem
rem  资源落点 (容易搞错):
rem      utils/paths.project_root() 打包后返回 exe 所在目录, 所以 configs
rem      必须放 exe 同级; 而 --add-data 默认落在 _internal 下, assets 正好
rem      是 asset_manager 期望的位置. 两者刚好对上, 不要擅自挪动.
rem
rem  编码说明:
rem      本文件存为 GBK. 中文 Windows 的 cmd 用 936 代码页解析批处理,
rem      存成 UTF-8 会把中文注释解析成乱码, 甚至被当作命令执行.
rem      修改时请保持 GBK, 不要再加 chcp 65001.
rem ============================================================

rem ---------------------------------------------------- 版本号
rem 改版本只改这一行: 目录名 / zip 名 / exe 属性里的版本号都用它
set VERSION=2.3

set APPNAME=WuWa_Hekili
set OUTDIR=%APPNAME%_v%VERSION%
set ZIPNAME=%APPNAME%_v%VERSION%_win64

rem 指定解释器: 系统里有多个 python 时, 先 set PYTHON_EXE=<完整路径>
rem 再运行本脚本, 否则默认用 PATH 里的 python.
set PYEXE=python
if defined PYTHON_EXE set PYEXE=%PYTHON_EXE%

set DO_ZIP=1
set KEEP_TEMP=0
for %%A in (%*) do (
    if /I "%%A"=="--no-zip" set DO_ZIP=0
    if /I "%%A"=="--keep-temp" set KEEP_TEMP=1
)

cd /d "%~dp0"

echo ==================================================
echo   %APPNAME% v%VERSION% 打包
echo ==================================================
echo.

rem ---------------------------------------------------- 0. 环境检查
echo [0/6] 检查打包环境...
%PYEXE% -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo   [错误] 无法运行 %PYEXE%, 请先激活 conda 环境 wuwahekili
    echo          或 set PYTHON_EXE=^<python.exe 的完整路径^>
    goto :fail
)
%PYEXE% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo   [错误] 当前环境没有 PyInstaller, 先执行:
    echo          pip install pyinstaller
    goto :fail
)
%PYEXE% -c "import PySide6, cv2" >nul 2>nul
if errorlevel 1 (
    echo   [错误] 缺少运行依赖, 先执行:
    echo          pip install -r requirements.txt
    goto :fail
)

rem 打包前跑一遍回归测试, 避免把坏掉的版本发出去
echo   回归测试...
%PYEXE% tests\test_script_parser.py >nul 2>&1 || goto :test_fail
%PYEXE% tests\test_director_press.py >nul 2>&1 || goto :test_fail
%PYEXE% tests\test_managers.py >nul 2>&1 || goto :test_fail
echo   三套测试全部通过
echo.

rem ---------------------------------------------------- 1. 清理
echo [1/6] 清理上一轮残留...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
if exist "%ZIPNAME%.zip" del /q "%ZIPNAME%.zip"

rem ---------------------------------------------------- 2. 版本信息
echo [2/6] 生成 exe 版本信息...
%PYEXE% tools\build\make_version.py %VERSION% "build\version_info.txt"
if errorlevel 1 goto :fail

rem ---------------------------------------------------- 3. 打包
rem -D 目录模式 (启动快, 资源可见); -w 不弹控制台; --uac-admin 请求管理员
rem 权限 -- 否则游戏在前台时底层按键钩子收不到消息.
echo [3/6] 正在打包 (首次约 1-3 分钟)...
%PYEXE% -m PyInstaller -D -w --uac-admin --clean --noconfirm ^
    -n "%APPNAME%" ^
    --version-file "build\version_info.txt" ^
    --add-data "assets\characters;assets\characters" ^
    --add-data "assets\input;assets\input" ^
    --add-data "tools\factory\factory_config.json;tools\factory" ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.QtMultimedia ^
    main.py
if errorlevel 1 (
    echo   [错误] PyInstaller 打包失败, 看上面最后几行日志
    goto :fail
)

rem ---------------------------------------------------- 4. 组装
echo [4/6] 组装发布目录 [%OUTDIR%]...
mkdir "%OUTDIR%"
xcopy "dist\%APPNAME%" "%OUTDIR%\" /E /I /Y >nul
if errorlevel 1 goto :fail

rem 剧本放 exe 同级 (project_root() 打包后就是 exe 目录)
xcopy "configs" "%OUTDIR%\configs\" /E /I /Y >nul
if not exist "%OUTDIR%\configs\routines" mkdir "%OUTDIR%\configs\routines"

if exist "README.md" copy "README.md" "%OUTDIR%\" /Y >nul

rem ---------------------------------------------------- 5. 自检
rem 打包最常见的翻车是"资源没进包, 运行时才炸". 这里提前验一遍.
echo [5/6] 校验发布包完整性...
set MISSING=0
call :need_file "%OUTDIR%\%APPNAME%.exe"
call :need_file "%OUTDIR%\_internal\assets\characters\Character_Occupation.txt"
call :need_dir "%OUTDIR%\_internal\assets\input\keyboard"
call :need_file "%OUTDIR%\_internal\tools\factory\factory_config.json"
call :need_dir "%OUTDIR%\configs\routines"
if "!MISSING!"=="1" (
    echo   [错误] 发布包缺少上面列出的文件
    goto :fail
)

rem ---------------------------------------------------- 6. 压缩
if "!DO_ZIP!"=="1" (
    echo [6/6] 压缩成 %ZIPNAME%.zip...
    if exist "%ZIPNAME%.zip" del /q "%ZIPNAME%.zip"
    rem 用 python 的 zipfile 压缩: 刚生成的 dll 会被杀毒软件短暂占用,
    rem 系统压缩命令遇到就整体失败而且不返回错误码
    %PYEXE% tools\build\make_zip.py "%OUTDIR%" "%ZIPNAME%.zip"
    if errorlevel 1 goto :fail
) else (
    echo [6/6] 跳过压缩
)

rem ---------------------------------------------------- 清理过程文件
if "%KEEP_TEMP%"=="0" (
    if exist "build" rmdir /s /q "build"
    if exist "dist" rmdir /s /q "dist"
    if exist "%APPNAME%.spec" del /q "%APPNAME%.spec"
)

echo.
echo ==================================================
echo   打包成功  v%VERSION%
echo ==================================================
echo   文件夹: %OUTDIR%\
if "!DO_ZIP!"=="1" echo   压缩包: %ZIPNAME%.zip
%PYEXE% tools\build\size_report.py "%OUTDIR%"
echo.
echo   发给别人: 解压后运行 %APPNAME%.exe (会请求管理员权限)
echo   首次运行会在 exe 旁边生成 config.json
echo ==================================================
if /I not "%NO_PAUSE%"=="1" pause
exit /b 0

rem ==================================================== 子过程

:need_file
if not exist "%~1" (
    echo   [缺失] %~1
    set MISSING=1
)
exit /b 0

:need_dir
if not exist "%~1\" (
    echo   [缺失] %~1\
    set MISSING=1
)
exit /b 0

:test_fail
echo.
echo   [错误] 回归测试没通过, 先修好再打包:
echo          %PYEXE% tests\test_script_parser.py
echo          %PYEXE% tests\test_director_press.py
echo          %PYEXE% tests\test_managers.py
goto :fail

:fail
echo.
echo   打包已中止.
if exist "build" rmdir /s /q "build" 2>nul
if exist "dist" rmdir /s /q "dist" 2>nul
if /I not "%NO_PAUSE%"=="1" pause
exit /b 1
