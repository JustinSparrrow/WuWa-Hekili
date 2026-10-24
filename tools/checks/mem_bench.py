"""
内存压测：连续推进 N 次连招，看内存与对象数会不会往上堆。

为什么要单独压测
--------------
悬浮窗的内存问题不会在"打开看一眼"的时候暴露，只会随着连招次数累积：
v1.0 每推进一次就 new 一组动画对象 + new 一个格子控件，而这些对象
要等 Qt 事件循环空闲才真正销毁，连招一快就会堆积。

本脚本把这条链路跑到高频：Director 推进 -> get_visual_data 查图标
-> overlay 滑动渲染，中间穿插 processEvents，然后对比前后的：

    私有内存       进程真实占用（看是否泄漏）
    Python 堆      tracemalloc 统计（看 Python 层有没有漏）
    Qt 控件数      QApplication.allWidgets()（看格子池有没有失控）
    动画对象数     直接读 overlay._animators（应当恒定）
    单次刷新耗时   看有没有随次数劣化的趋势

用法
----
    python tools/mem_bench.py                  # 默认 2000 次
    python tools/mem_bench.py --rounds 5000
    python tools/mem_bench.py --routine configs/routines/爱琳莫轮椅轴.json

看结论怎么判
-----------
    Qt 控件数、动画对象数必须**完全不变**（它们用池复用，不该增长）。
    私有内存允许小幅波动（几 MB 内，因为 Python 内存池/GC 有滞后），
    但如果随次数线性上升，就是泄漏。
"""

import argparse
import gc
import glob
import json
import os
import sys
import time
import tracemalloc

# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
sys.path.insert(0, _root)

from utils.paths import project_root  # noqa: E402
ROOT = str(project_root())

# 必须在导入 PySide6 之前设置，否则会拉起真实窗口
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.director import Director
from ui.overlay_window import HekiliOverlay
from utils.asset_manager import AssetManager
from mem_probe import sample_memory


def _mb(value):
    return value / 1024 / 1024


def pick_routine(explicit=None):
    """选一个剧本用来压测。"""
    if explicit:
        return explicit

    candidates = sorted(glob.glob(os.path.join(ROOT, "configs", "routines", "*.json")))
    if not candidates:
        raise SystemExit("configs/routines 下没有剧本，先放一份进去。")
    return candidates[0]


def build_objects(routine_path):
    """按真实启动流程组装 Director + Overlay。"""
    with open(routine_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    asset_mgr = AssetManager(os.path.join(ROOT, "assets", "characters"))
    director = Director(
        team_config={int(k): v for k, v in data["team_config"].items()},
        opener_script=data["opener_script"],
        loop_script=data["loop_script"],
        start_char_index=data.get("initial_char_index", 1),
        asset_mgr=asset_mgr,
    )
    overlay = HekiliOverlay()
    overlay.show()
    return director, overlay


def snapshot_state(overlay):
    """当前的对象数快照。"""
    app = QApplication.instance()
    return {
        "qt_widgets": len(app.allWidgets()) if app else 0,
        "anim_objects": len(overlay._animators) if hasattr(overlay, "_animators") else 0,
        "slot_widgets": len(overlay.widgets),
        "pool": len(getattr(overlay, "_pool", [])),
        "gc_objects": len(gc.get_objects()),
    }


def warmup(director, overlay, app, rounds):
    """
    预热：让缓存、对象池、Qt 内部结构先分配到位。

    必须把这一步和"正式测量"分开——否则首次分配（图片缓存、字体、
    渲染缓冲）会被当成泄漏算进增量里，基线会虚高好几 MB。
    """
    for _ in range(rounds):
        director.advance()
        overlay.update_ui(director.get_visual_data(3), is_advance=True)

    for _ in range(3):
        app.processEvents()

    gc.collect()


def run_rounds(director, overlay, app, rounds, segments=8):
    """
    正式压测主循环，并分段采样内存。

    分段的意义：只看首末差值分不清"缓存填满后收敛"和"线性泄漏"。
    如果每段增量越来越小 -> 缓存填充；如果每段等量增长 -> 泄漏。

    :return: (平均每轮耗时ms, [(累计轮次, 私有内存字节, 控件数), ...])
    """
    elapsed_total = 0.0
    samples = []
    seg_size = max(1, rounds // segments)

    def record(done):
        mem = sample_memory(os.getpid())
        widgets = len(QApplication.instance().allWidgets())
        samples.append((done, mem["private"] if mem else 0, widgets))

    record(0)

    for i in range(rounds):
        began = time.perf_counter()

        director.advance()
        overlay.update_ui(director.get_visual_data(3), is_advance=True)

        elapsed_total += time.perf_counter() - began

        # 每 20 轮把事件循环转一次：动画的 finished 回调、格子回收
        # 都在事件循环里触发，不转的话池子不会真正运转
        if i % 20 == 19:
            app.processEvents()

        if (i + 1) % seg_size == 0:
            record(i + 1)

    app.processEvents()

    if samples[-1][0] != rounds:
        record(rounds)

    return elapsed_total / max(1, rounds) * 1000, samples


def main():
    parser = argparse.ArgumentParser(description="连招推进内存压测")
    parser.add_argument("--rounds", type=int, default=2000, help="推进次数，默认 2000")
    parser.add_argument("--routine", help="指定剧本 JSON 路径")
    parser.add_argument("--warmup", type=int, default=120, help="预热次数，默认 120")
    args = parser.parse_args()

    routine_path = pick_routine(args.routine)
    print(f"剧本: {os.path.basename(routine_path)}")

    app = QApplication(sys.argv)
    director, overlay = build_objects(routine_path)

    print(f"预热 {args.warmup} 次（让图片缓存/对象池先分配到位）...")
    tracemalloc.start()
    warmup(director, overlay, app, args.warmup)

    # ---------------- 基线（预热之后再拍） ----------------
    time.sleep(0.2)
    baseline_mem = sample_memory(os.getpid())
    baseline_state = snapshot_state(overlay)
    baseline_snapshot = tracemalloc.take_snapshot()

    avg_ms, samples = run_rounds(director, overlay, app, args.rounds)

    # ---------------- 收尾统计 ----------------
    gc.collect()
    time.sleep(0.2)      # 给 Qt 一点时间真正释放 deferred delete
    app.processEvents()

    final_mem = sample_memory(os.getpid())
    final_state = snapshot_state(overlay)
    final_snapshot = tracemalloc.take_snapshot()

    # tracemalloc 的差分只统计"当前还活着"的分配
    diff = final_snapshot.compare_to(baseline_snapshot, "filename")
    python_growth = sum(stat.size_diff for stat in diff)

    print("\n" + "=" * 62)
    print(f"压测完成：{args.rounds} 次推进")
    print("-" * 62)

    if baseline_mem and final_mem:
        delta_private = final_mem["private"] - baseline_mem["private"]
        delta_ws = final_mem["ws"] - baseline_mem["ws"]
        print(f"私有内存    {_mb(baseline_mem['private']):7.1f}MB -> "
              f"{_mb(final_mem['private']):7.1f}MB   Δ{_mb(delta_private):+7.2f}MB")
        print(f"工作集      {_mb(baseline_mem['ws']):7.1f}MB -> "
              f"{_mb(final_mem['ws']):7.1f}MB   Δ{_mb(delta_ws):+7.2f}MB")
        print(f"句柄        {baseline_mem['handles']:>7} -> {final_mem['handles']:>7}"
              f"   Δ{final_mem['handles'] - baseline_mem['handles']:+d}")
    else:
        delta_private = 0
        print("（未取到进程内存，可能需要管理员权限）")

    print(f"Python 堆   Δ{_mb(python_growth):+7.2f}MB（tracemalloc）")
    print(f"Qt 控件数   {baseline_state['qt_widgets']} -> {final_state['qt_widgets']}"
          f"   Δ{final_state['qt_widgets'] - baseline_state['qt_widgets']:+d}")
    print(f"动画对象数  {baseline_state['anim_objects']} -> {final_state['anim_objects']}"
          f"   Δ{final_state['anim_objects'] - baseline_state['anim_objects']:+d}")
    print(f"槽位/池     {baseline_state['slot_widgets']}格+{baseline_state['pool']}空闲"
          f"  ->  {final_state['slot_widgets']}格+{final_state['pool']}空闲")
    print(f"平均刷新    {avg_ms:.3f} ms/次")
    print("-" * 62)

    # ---------------- 分段曲线 ----------------
    trend_note = None
    if len(samples) >= 3:
        print(f"{'轮次':>8}  {'私有内存':>10}  {'控件数':>6}")
        for done, private, widgets in samples:
            print(f"{done:>8}  {_mb(private):9.1f}MB  {widgets:>6}")

        # 前半段 vs 后半段增量：用来区分"缓存填满后收敛"和"线性泄漏"
        mid = len(samples) // 2
        first_half = samples[mid][1] - samples[0][1]
        second_half = samples[-1][1] - samples[mid][1]

        if second_half < 1.5 * 1024 * 1024:
            trend_note = "后半段基本不再增长 -> 前面的增长是缓存填充，已收敛"
        elif second_half <= first_half * 0.7:
            trend_note = "后半段增量明显变小 -> 增长在收敛，不像泄漏"
        elif second_half > first_half * 1.2 and second_half > 3 * 1024 * 1024:
            trend_note = "后半段增量不减 -> 存在线性增长，需要重点排查"
        else:
            trend_note = "增量平稳但幅度小 -> 可能是内存碎片，可延长压测再观察"

        print(f"趋势        {trend_note}")
        print("-" * 62)

    # ---------------- 结论 ----------------
    problems = []
    if final_state["anim_objects"] != baseline_state["anim_objects"]:
        problems.append("动画对象数发生了变化（应该常驻复用）")
    if final_state["qt_widgets"] - baseline_state["qt_widgets"] > 2:
        problems.append("Qt 控件数持续增长（格子池可能没回收）")
    if delta_private > 8 * 1024 * 1024:
        problems.append(f"私有内存增长偏大（{_mb(delta_private):+.1f}MB）")

    if problems:
        print("⚠️  发现问题：")
        for p in problems:
            print(f"    - {p}")
    else:
        print("✅ 对象数恒定，内存无显著增长，未发现泄漏迹象")
    print("=" * 62)

    overlay.close()


if __name__ == "__main__":
    main()
