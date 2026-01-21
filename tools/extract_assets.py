import os
import sys
import cv2
import time

# ================= ⚙️ 配置 =================
# 视频路径
VIDEO_PATH = r"../assets/video/Client-Win64-Shipping 2026.01.21 - 16.07.05.01.mp4"
# 输出目录
OUTPUT_BASE = r"../assets/assets_temp"
# ===============================================


# 全局状态
drawing = False      # 正在拖拽
ix, iy = -1, -1      # 起始坐标
current_frame = None # 当前显示的画面
clean_frame = None   # 没有画线的干净画面
is_paused = False    # 暂停状态
save_mode = "char"   # 当前模式: "char" (头像) 或 "skill" (图标)


def ensure_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)


def save_crop(x_min, y_min, x_max, y_max):
    global clean_frame, save_mode

    # 确认没有超出边界
    if clean_frame is None:
        return
    w, h = x_max - x_min, y_max - y_min
    if w < 10 or h < 10:
        print("⚠️ 选区太小，忽略")
        return

    # 裁剪
    crop = clean_frame[y_min:y_max, x_min:x_max]
    timestamp = int(time.time() * 1000)

    if save_mode == "char":
        folder = os.path.join(OUTPUT_BASE, "characters")
        ensure_folder(folder)
        filename = f"char_{timestamp}.png"
        path = os.path.join(folder, filename)
        cv2.imwrite(path, crop)
        print(f"✅ [头像] 已保存: {filename}")

    elif save_mode == "skill":
        # 技能需要指定名字，所以要弹出来问一下
        print("-" * 30)
        name = input(f"⌨️ [技能模式] 请输入图标名称 (回车跳过): ").strip()
        if name:
            folder = os.path.join(OUTPUT_BASE, "icons")
            ensure_folder(folder)
            filename = f"{name}.png"
            path = os.path.join(folder, filename)
            cv2.imwrite(path, crop)
            print(f"✅ [图标] 已保存: {name}.png")
        else:
            print("🚫 已取消")

        print("▶️ 继续播放...")

def mouse_callback(event, x, y, flags, param):
    global ix, iy, drawing, current_frame, is_paused

    if current_frame is None:
        return

    if not is_paused:
        return

    # 1. 按下左键
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        ix, iy = x, y

    # 2. 拖拽预览（画绿框）
    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            # 每次移动都刷新画面防止框框重叠
            img_temp = current_frame.copy()
            cv2.rectangle(img_temp, (ix, iy), (x, y), (0, 255, 0), 2)
            cv2.imshow('Wuwa Cutter', img_temp)

    # 3. 松开左键
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False

        # 计算坐标
        x_min, x_max = sorted([ix, x])
        y_min, y_max = sorted([iy, y])

        cv2.rectangle(current_frame, (x_min, y_min), (x_max, y_max), (0, 0, 255), 2)
        cv2.imshow('Wuwa Cutter', current_frame)
        cv2.waitKey(1)

        save_crop(x_min, y_min, x_max, y_max)


def main():
    global current_frame, clean_frame, is_paused, save_mode

    if not os.path.exists(VIDEO_PATH):
        print("❌ 找不到视频，请检查路径！")
        return

    cap = cv2.VideoCapture(VIDEO_PATH)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    window_name = 'Wuwa Cutter'
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1080, 720)

    # 进度条回调
    def nothing(x): pass
    cv2.createTrackbar('Seek', window_name, 0, total_frames, nothing)

    # 绑定鼠标
    cv2.setMouseCallback(window_name, mouse_callback)

    print("=" * 50)
    print("✂️ 鸣潮素材纯手动切割工具")
    print("------------------------------------------")
    print(" [空格]    暂停/播放")
    print(" [按键 1]  切换到【角色头像模式】(框选即自动保存)")
    print(" [按键 2]  切换到【技能图标模式】(框选后手动命名)")
    print(" [鼠标]    在画面上框选区域即可")
    print(" [Esc]     退出")
    print("=" * 50)

    while True:
        # 处理进度条
        real_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        target_pos = cv2.getTrackbarPos('Seek', window_name)
        track_pos = cv2.getTrackbarPos('Seek', window_name)

        if abs(target_pos - real_pos) > 2:
            # 听你的：视频跳转到进度条的位置
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_pos)
            ret, frame = cap.read()
            if ret:
                current_frame = frame.copy()
                clean_frame = frame.copy()

        if not is_paused:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            # 更新画面缓存
            current_frame = frame.copy()
            clean_frame = frame.copy()

            # 同步进度条
            curr_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            cv2.setTrackbarPos('Seek', window_name, curr_pos)
        else:
            # 暂停时允许拖动进度条
            curr_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            if abs(track_pos - curr_pos) > 5:
                cap.set(cv2.CAP_PROP_POS_FRAMES, track_pos)
                ret, frame = cap.read()
                if ret:
                    current_frame = frame.copy()
                    clean_frame = frame.copy()

        # === 绘制 UI 状态文字 ===
        # 模式提示
        mode_text = "MODE: CHARACTER (Auto Save)" if save_mode == "char" else "MODE: SKILL (Manual Name)"
        mode_color = (0, 255, 255) if save_mode == "char" else (255, 0, 255)

        # 状态提示
        status_text = "PAUSED" if is_paused else "PLAYING"

        # 在画面左上角写字
        display_img = current_frame.copy() if not drawing else display_img  # 如果正在画，已经在回调里显示了，这里不动
        if not drawing:
            cv2.putText(display_img, f"{status_text} | {mode_text}", (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, mode_color, 2)
            cv2.imshow(window_name, display_img)

        # 按键处理
        key = cv2.waitKey(15) & 0xFF

        if key == 27:
            break
        elif key == 32:
            is_paused = not is_paused
        elif key == ord('1'):
            save_mode = "char"
            print("🔄 已切换模式: 角色头像 (框选自动保存)")
        elif key == ord('2'):
            save_mode = "skill"
            print("🔄 已切换模式: 技能图标 (框选输入名称)")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()


