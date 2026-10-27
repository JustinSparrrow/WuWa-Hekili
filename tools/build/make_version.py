"""
生成 PyInstaller 的 Windows 版本信息文件。

用途：让 exe 在「属性 → 详细信息」里显示版本号、产品名、版权，
而不是一片空白。build.bat 打包前调用它。

    python tools/build/make_version.py 2.3 build/version_info.txt

为什么单独拆一个脚本而不是在 bat 里 echo：
版本信息文件是 VSVersionInfo 结构的 Python 字面量，里面有大量括号和
引号，用 bat 拼字符串会遇到转义地狱，且中文在 chcp 切换时容易变乱码。
"""

from __future__ import annotations

import os
import sys

TEMPLATE = '''# UTF-8
# 由 tools/build/make_version.py 生成，不要手改
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple4},
    prodvers={tuple4},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [StringStruct('CompanyName', '{company}'),
         StringStruct('FileDescription', '{description}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{internal}'),
         StringStruct('LegalCopyright', '{copyright}'),
         StringStruct('OriginalFilename', '{internal}.exe'),
         StringStruct('ProductName', '{product}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
'''


def build(version: str, out_path: str) -> str:
    parts = (version.split(".") + ["0", "0", "0", "0"])[:4]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        nums = [0, 0, 0, 0]
    tuple4 = "({}, {}, {}, {})".format(*nums)

    text = TEMPLATE.format(
        tuple4=tuple4,
        version=version,
        company="WuWa_Hekili",
        description="鸣潮连招提示器 · 悬浮层辅助（只监听输入，不读写游戏内存）",
        internal="WuWa_Hekili",
        copyright="MIT License",
        product="WuWa_Hekili",
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    version = argv[1].lstrip("vV")
    path = build(version, argv[2])
    print(f"[version] {path} <- v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
