"""
进程内存采样器 —— 用来判断"这一版到底占多少内存、用久了会不会一直涨"。

为什么不用任务管理器看
--------------------
任务管理器只给一个瞬时数字，而内存问题有两个完全不同的形态：

    1. 占用高但稳定   -> 只是基线高（Qt 预分配、图片缓存），不影响长时间悬挂；
    2. 占用不高但持续涨 -> 这才是泄漏，玩一小时就会被系统拖慢。

本工具对同一个进程连续采样，输出起始值 / 峰值 / 结束值 / 增长斜率，
让你一眼看出是"基线高"还是"在漏"。

三个指标怎么看
------------
    Private（私有内存）  最重要。程序真实占用、不共享、不会被系统随手回收。
                          任务管理器里对应"提交大小"。判断泄漏主要看它。
    WS（工作集）         当前驻留在物理内存里的部分，系统压力大时会被回收，
                          波动大，只能参考。任务管理器里对应"内存(专用工作集)"。
    句柄 / 线程          泄漏的早期信号。句柄数应长期平稳，持续上涨说明
                          有资源没关（文件、GDI 对象、内核句柄）。

用法
----
    # 1. 先列出候选进程，找到 pid
    python tools/mem_probe.py --list
    python tools/mem_probe.py --list --name python

    # 2. 采样（默认每秒一次，60 秒）
    python tools/mem_probe.py --pid 12345 --seconds 60
    python tools/mem_probe.py --name WuWa_Hekili --seconds 120 --csv mem.csv

    # 3. 跟着进程生命周期采样（直到它退出）
    python tools/mem_probe.py --pid 12345 --until-exit

判断标准（工具会自动给结论）
--------------------------
    稳定    : 私有内存增长 < 3MB 且斜率 < 1.5 MB/min
    需留意  : 增长 3~10MB，或斜率 1.5~4 MB/min
    疑似泄漏: 增长 > 10MB 或斜率 > 4 MB/min（且采样时长 >= 60s 才有意义）

注意：采样期间请保持程序处于**真实使用状态**（打连招、来回切剧本），
否则测到的是空转内存，参考价值有限。
"""

import argparse
import csv
import ctypes
import os
import sys
import time
from ctypes import wintypes

if os.name != "nt":
    print("本工具只支持 Windows（依赖 Win32 进程 API）。")
    sys.exit(1)

# ================================================================ Win32 绑定

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    """
    比 PROCESS_MEMORY_COUNTERS 多一个 PrivateUsage。

    注意字段必须按原样排列（DWORD + SIZE_T 混排），64 位下对齐才对得上，
    否则读出来的数字会是垃圾。
    """
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
_kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD]


# ================================================================ 进程枚举

def list_processes():
    """
    枚举所有进程，返回 [{pid, name, threads}]。

    用 Toolhelp 快照而不是 WMI：不需要额外依赖，也不会卡住（WMI 首次查询很慢）。
    """
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []

    result = []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

    try:
        ok = _kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            result.append({
                "pid": entry.th32ProcessID,
                "name": entry.szExeFile.decode("mbcs", errors="ignore"),
                "threads": entry.cntThreads,
            })
            ok = _kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)

    return result


def _open_process(pid):
    """打开进程句柄，权限不够时降级重试。"""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    return handle


def sample_memory(pid):
    """
    采一次内存。

    :return: {"ws": bytes, "private": bytes, "peak_ws": bytes, "handles": int} 或 None
    """
    handle = _open_process(pid)
    if not handle:
        return None

    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        if not _psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None

        handle_count = wintypes.DWORD(0)
        _kernel32.GetProcessHandleCount(handle, ctypes.byref(handle_count))

        return {
            "ws": counters.WorkingSetSize,
            "private": counters.PrivateUsage,
            "peak_ws": counters.PeakWorkingSetSize,
            "handles": handle_count.value,
        }
    finally:
        _kernel32.CloseHandle(handle)


# ================================================================ 展示辅助

def _mb(value):
    return value / 1024 / 1024


def _fmt_mb(value):
    return f"{_mb(value):7.1f}MB"


def _slope_per_minute(samples):
    """
    最小二乘拟合出线性斜率（单位/分钟），用来判断"是否在持续增长"。

    只看首末差值会被抖动骗：程序先涨后跌也会显示正增长。
    拟合斜率能反映整体趋势。
    """
    if len(samples) < 3:
        return 0.0

    # samples: [(秒, 字节)]
    n = len(samples)
    mean_x = sum(s[0] for s in samples) / n
    mean_y = sum(s[1] for s in samples) / n

    num = sum((x - mean_x) * (y - mean_y) for x, y in samples)
    den = sum((x - mean_x) ** 2 for x, _ in samples)
    if den == 0:
        return 0.0

    return (num / den) * 60  # 每秒 -> 每分钟


def _verdict(private_samples):
    """根据私有内存增长情况给出结论。"""
    if len(private_samples) < 5:
        return "样本太少，无法判断（建议至少采样 30 秒）"

    duration = private_samples[-1][0] - private_samples[0][0]
    if duration < 30:
        return "采样时间太短，无法判断（建议至少 60 秒）"

    growth = private_samples[-1][1] - private_samples[0][1]
    slope = _slope_per_minute(private_samples)

    if growth > 10 * 1024 * 1024 or slope > 4 * 1024 * 1024:
        return f"⚠️  私有内存在持续增长（+{_mb(growth):.1f}MB, {_mb(slope):+.2f}MB/min），疑似泄漏"
    if growth > 3 * 1024 * 1024 or slope > 1.5 * 1024 * 1024:
        return f"🔸 有轻微增长（+{_mb(growth):.1f}MB, {_mb(slope):+.2f}MB/min），可再观察"

    return f"✅ 内存稳定（{_mb(growth):+.1f}MB, {_mb(slope):+.2f}MB/min）"


# ================================================================ 主流程

def cmd_list(keyword=None):
    """列出进程，按私有内存从大到小排序。"""
    rows = []
    for proc in list_processes():
        if keyword and keyword.lower() not in proc["name"].lower():
            continue
        memory = sample_memory(proc["pid"])
        if memory is None:
            continue
        rows.append((proc, memory))

    if not rows:
        print("没有匹配的进程。" if keyword else "没有可读的进程。")
        return

    rows.sort(key=lambda r: r[1]["private"], reverse=True)

    print(f"{'PID':>8}  {'进程名':<28} {'私有内存':>10} {'工作集':>10} {'句柄':>7} {'线程':>5}")
    print("-" * 76)
    for proc, memory in rows:
        name = proc["name"][:28]
        print(f"{proc['pid']:>8}  {name:<28} {_fmt_mb(memory['private'])} "
              f"{_fmt_mb(memory['ws'])} {memory['handles']:>7} {proc['threads']:>5}")

    print("\n提示：用 --pid <PID> 开始采样。")


def cmd_watch(pid, seconds, interval, until_exit, csv_path):
    """持续采样并输出统计。"""
    start_time = time.time()
    next_tick = start_time

    ws_samples, private_samples, handle_samples, thread_samples = [], [], [], []
    rows = []

    print(f"开始采样 pid={pid}，间隔 {interval}s"
          f"{'，直到进程退出' if until_exit else f'，共 {seconds}s'} ...")
    print("（采样期间请正常使用程序，让内存进入真实负载状态）\n")

    try:
        while True:
            now = time.time()
            elapsed = now - start_time

            if not until_exit and elapsed > seconds:
                break

            memory = sample_memory(pid)
            if memory is None:
                print(f"\n进程 {pid} 已退出或无法访问（{elapsed:.1f}s）。")
                break

            threads = 0
            for proc in list_processes():
                if proc["pid"] == pid:
                    threads = proc["threads"]
                    break

            ws_samples.append((elapsed, memory["ws"]))
            private_samples.append((elapsed, memory["private"]))
            handle_samples.append((elapsed, memory["handles"]))
            thread_samples.append((elapsed, threads))
            rows.append([round(elapsed, 2), round(_mb(memory["ws"]), 2),
                         round(_mb(memory["private"]), 2), memory["handles"], threads])

            print(f"[{elapsed:6.1f}s] 私有 {_fmt_mb(memory['private'])}  "
                  f"工作集 {_fmt_mb(memory['ws'])}  句柄 {memory['handles']:>5}  线程 {threads:>3}")

            next_tick += interval
            sleep_time = max(0.0, next_tick - time.time())
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n已中断采样。")

    if not ws_samples:
        print("没有采到数据。")
        return

    # ---------------- 汇总 ----------------
    duration = private_samples[-1][0] - private_samples[0][0]
    print("\n" + "=" * 66)
    print(f"采样 {duration:.1f}s（{len(private_samples)} 次）")
    print("-" * 66)
    print(f"私有内存   起始 {_fmt_mb(private_samples[0][1])} -> 结束 {_fmt_mb(private_samples[-1][1])}"
          f"   峰值 {_fmt_mb(max(v for _, v in private_samples))}")
    print(f"工作集     起始 {_fmt_mb(ws_samples[0][1])} -> 结束 {_fmt_mb(ws_samples[-1][1])}"
          f"   峰值 {_fmt_mb(max(v for _, v in ws_samples))}")
    print(f"句柄       起始 {handle_samples[0][1]} -> 结束 {handle_samples[-1][1]}"
          f"   Δ{handle_samples[-1][1] - handle_samples[0][1]:+d}")
    if any(t for _, t in thread_samples):
        print(f"线程       起始 {thread_samples[0][1]} -> 结束 {thread_samples[-1][1]}")
    print("-" * 66)
    print("结论：" + _verdict(private_samples))
    print("=" * 66)

    if csv_path:
        try:
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["time_s", "working_set_mb", "private_mb", "handles", "threads"])
                writer.writerows(rows)
            print(f"\n明细已写入 {csv_path}（可直接拖进 Excel 画曲线）")
        except OSError as e:
            print(f"\n写 CSV 失败: {e}")


def _resolve_pid(args):
    """把 --pid / --name 解析成唯一 pid。"""
    if args.pid:
        return args.pid

    if not args.name:
        print("请用 --pid 或 --name 指定目标进程（--list 可以先看看有哪些）。")
        return None

    matches = [p for p in list_processes() if args.name.lower() in p["name"].lower()]
    if not matches:
        print(f"没有找到名字包含 '{args.name}' 的进程。")
        return None
    if len(matches) > 1:
        print(f"匹配到多个进程，请改用 --pid 指定：")
        for proc in matches:
            print(f"    {proc['pid']:>8}  {proc['name']}")
        return None
    return matches[0]["pid"]


def main():
    parser = argparse.ArgumentParser(
        description="进程内存采样器：判断程序占用多少、会不会持续增长。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python tools/mem_probe.py --list\n"
               "  python tools/mem_probe.py --name python --seconds 60\n"
               "  python tools/mem_probe.py --pid 1234 --until-exit --csv mem.csv")
    parser.add_argument("--list", action="store_true", help="列出进程及当前内存")
    parser.add_argument("--name", help="按进程名模糊匹配（如 WuWa_Hekili / python）")
    parser.add_argument("--pid", type=int, help="直接指定进程 PID")
    parser.add_argument("--seconds", type=float, default=60, help="采样时长，默认 60 秒")
    parser.add_argument("--interval", type=float, default=1.0, help="采样间隔，默认 1 秒")
    parser.add_argument("--until-exit", action="store_true", help="一直采样到进程退出")
    parser.add_argument("--csv", help="把明细写入 CSV 文件")

    args = parser.parse_args()

    if args.list:
        cmd_list(args.name)
        return

    pid = _resolve_pid(args)
    if pid is None:
        return

    cmd_watch(pid, args.seconds, max(0.2, args.interval), args.until_exit, args.csv)


if __name__ == "__main__":
    main()
