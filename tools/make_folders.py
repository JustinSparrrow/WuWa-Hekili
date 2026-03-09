import os

# ================= 配置区域 =================
# 这里根据你截图的路径，指向那个放着角色名字的 assets 文件夹
# 注意：前面加 r 是为了防止转义字符报错
bash_path = r"../assets/assets"
folders = ["Aalto", "Aemeath", "Augusta",
           "Baizhi", "Brant", "Buling",
           "Calcharo", "Camellya", "Cantarella", "Carlotta", "Cartethyia", "Changli", "Chisa", "Chixia", "Ciaccona",
           "Danjin",
           "Encore",
           "Galbrena",
           "luno",
           "Jianxin", "Jinhsi", "Jiyan",
           "Lingyang", "Lumi", "Lupa", "Luuk Herssen", "Lynae",
           "Mornye", "Mortefi",
           "Phoebe", "Phrolova",
           "Qiuyuan",
           "Roccia", "Rover",
           "Sanhua", "Shorekeeper",
           "Taoqi",
           "Verina",
           "Xiangli Yao",
           "Yangyang", "Yinlin", "Youhu", "Yuanwu",
           "Zani", "ZheZhi"]
sub_folders = ["normal_attack", "jump", "resonance_skill", "resonance_liberation", "echo", "character", "forte_circuit", "concerto_energy"]


# ===========================================

def create_structure():
    if not os.path.exists(bash_path):
        print(f"❌ 错误：找不到路径 {bash_path}")
        return

    count = 0

    for name in folders:
        print(f"📂 Processing: {name}...")
        target_folder = os.path.join(bash_path, name)
        for sub in sub_folders:
            target_dir = os.path.join(target_folder, sub)
            os.makedirs(target_dir, exist_ok=True)
    count += 1

    print(f"\n✅ Done! Created folders for {count} characters.")


create_structure()
