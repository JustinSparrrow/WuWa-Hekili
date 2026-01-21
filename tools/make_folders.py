import os

# ================= 配置区域 =================
# 这里根据你截图的路径，指向那个放着角色名字的 assets 文件夹
# 注意：前面加 r 是为了防止转义字符报错
bash_path = r"../assets/assets"
sub_folders = ["normal_attack", "jump", "resonance_skill", "resonance_liberation", "echo", "character"]


# ===========================================

def create_structure():
    if not os.path.exists(bash_path):
        print(f"❌ 错误：找不到路径 {bash_path}")
        return

    items = os.listdir(bash_path)
    count = 0
    for item in items:
        full_path = os.path.join(bash_path, item)

        if os.path.isdir(full_path):
            print(f"📂 Processing: {item}...")
            for sub in sub_folders:
                target_dir = os.path.join(full_path, sub)
                os.makedirs(target_dir, exist_ok=True)
            count += 1

    print(f"\n✅ Done! Created folders for {count} characters.")


create_structure()
