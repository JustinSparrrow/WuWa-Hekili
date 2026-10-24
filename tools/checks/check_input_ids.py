import pygame
import sys


def main():
    pygame.init()
    pygame.joystick.init()

    count = pygame.joystick.get_count()
    if count == 0:
        print("❌ 未检测到手柄！")
        return

    joystick = pygame.joystick.Joystick(0)
    joystick.init()

    print("=" * 40)
    print(f"🎮 手柄名称: {joystick.get_name()}")
    print(f"🔢 按键总数 (Buttons): {joystick.get_numbuttons()}")
    print(f"🕹️ 轴体总数 (Axes):    {joystick.get_numaxes()}")
    print(f"🎩 苦力帽数 (Hats):    {joystick.get_numhats()}")
    print("=" * 40)
    print("请尝试以下操作：")
    print("1. 垂直按下左摇杆 (LS/L3)")
    print("2. 垂直按下右摇杆 (RS/R3)")
    print("3. 按下 LT / RT (有时候它们是轴而不是按键)")
    print("-" * 40)

    try:
        while True:
            for event in pygame.event.get():
                # 1. 纯按键 (Buttons)
                if event.type == pygame.JOYBUTTONDOWN:
                    print(f"✅ [BUTTON] ID: {event.button}")

                # 2. 轴体移动 (Axes - 摇杆移动 和 LT/RT 线性扳机)
                elif event.type == pygame.JOYAXISMOTION:
                    # 过滤掉轻微的漂移，只有变动幅度大才显示
                    if abs(event.value) > 0.5:
                        print(f"🌊 [AXIS]   轴: {event.axis}, 值: {event.value:.2f}")

                # 3. 苦力帽 (Hats - 十字键)
                elif event.type == pygame.JOYHATMOTION:
                    print(f"🎩 [HAT]    值: {event.value}")

            pygame.time.wait(10)

    except KeyboardInterrupt:
        print("\n退出检测。")


if __name__ == "__main__":
    main()