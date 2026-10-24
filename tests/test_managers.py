import unittest
import os
import sys
import json
import shutil
import tempfile

# 把项目根目录加入路径，这样才能导入 utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from utils.asset_manager import AssetManager


class TestCoreModules(unittest.TestCase):
    """
    Java JUnit 风格的测试类
    测试 ConfigManager 和 AssetManager 的核心逻辑
    """

    def setUp(self):
        """
        @Before: 每次测试运行前执行
        创建一个临时的虚拟环境，模拟真实的 assets 目录结构
        """
        # 1. 创建临时根目录
        self.test_dir = tempfile.mkdtemp()

        # 2. 模拟目录结构
        # root/
        #   config.json
        #   assets/
        #     ui/xbox/
        #     assets/
        #       Character_Occupation.txt
        #       TestChar/
        #       _general/
        self.assets_root = os.path.join(self.test_dir, "assets", "characters")
        self.ui_root = os.path.join(self.test_dir, "assets", "input")

        os.makedirs(os.path.join(self.assets_root, "TestChar", "normal_attack"))
        os.makedirs(os.path.join(self.assets_root, "TestChar", "resonance_skill"))
        os.makedirs(os.path.join(self.assets_root, "_general", "normal_attack", "sword"))
        os.makedirs(os.path.join(self.ui_root, "xbox"))

        # 3. 创建假的配置文件 (config.json)
        self.config_path = os.path.join(self.test_dir, "config.json")
        self.mock_config_data = {
            "settings": {"current_device": "xbox"},
            "assets": {
                "folder_mapping": {
                    "basic": "normal_attack",
                    "skill": "resonance_skill",
                    "intro": "character"
                },
                "default_filename": {
                    "basic": "normal",
                    "skill": "normal",
                    "intro": "character"
                }
            },
            "keymaps": {
                "xbox": {
                    "basic": "xbox_x",
                    "intro_1": "dpad_up",
                    "intro_2": "dpad_right"
                }
            }
        }
        with open(self.config_path, 'w') as f:
            json.dump(self.mock_config_data, f)

        # 4. 创建假的资源文件 (Dummy files)
        # 角色职业映射
        with open(os.path.join(self.assets_root, "Character_Occupation.txt"), 'w') as f:
            f.write("TestChar=sword\n")

        # 创建一些假图片
        self._create_dummy_file(self.assets_root, "TestChar/normal_attack/normal.png")
        self._create_dummy_file(self.assets_root, "TestChar/resonance_skill/enhanced_skill.png")  # 强化技能
        self._create_dummy_file(self.assets_root, "TestChar/resonance_skill/normal_skill_1.png")  # 多段技能1
        self._create_dummy_file(self.assets_root, "TestChar/resonance_skill/normal_skill_2.png")  # 多段技能2

        # 通用图片 (用于测试 fallback)
        self._create_dummy_file(self.assets_root, "_general/normal_attack/sword/normal.png")

        # UI 按键图片
        self._create_dummy_file(self.ui_root, "xbox/xbox_x.png")
        self._create_dummy_file(self.ui_root, "xbox/dpad_up.png")

        # 5. 初始化 Managers
        # 强制 ConfigManager 读取我们的临时文件
        self.config_mgr = ConfigManager()
        self.config_mgr.config_path = self.config_path
        self.config_mgr.load()  # Reload

        self.asset_mgr = AssetManager(self.assets_root)
        # 修正 AssetManager 的 ui_root 指向临时目录
        self.asset_mgr.ui_root = self.ui_root

    def tearDown(self):
        """
        @After: 每次测试结束后执行
        清理垃圾，删除临时目录
        """
        shutil.rmtree(self.test_dir)

    def _create_dummy_file(self, base, rel_path):
        """辅助方法：创建一个空的 png 文件"""
        path = os.path.join(base, rel_path)
        with open(path, 'w') as f:
            f.write("fake image content")

    # ==========================================
    # 📝 测试用例 (Test Cases)
    # ==========================================

    def test_config_load(self):
        """测试配置读取是否正确"""
        print("\nRunning: test_config_load")
        device = self.config_mgr.get("settings.current_device")
        self.assertEqual(device, "xbox", "应该读取到 xbox")

    def test_icon_find_basic(self):
        """测试查找基础技能图标"""
        print("Running: test_icon_find_basic")
        path = self.asset_mgr.get_icon_path("TestChar", "basic")
        self.assertIsNotNone(path)
        self.assertTrue("TestChar" in path, "应该优先找到角色专属文件夹")
        self.assertTrue("normal.png" in path)

    def test_icon_find_variant(self):
        """测试查找变体图标 (enhanced)"""
        print("Running: test_icon_find_variant")
        # 查找 variant="enhanced"
        path = self.asset_mgr.get_icon_path("TestChar", "skill", variant="enhanced")
        self.assertIsNotNone(path)
        self.assertTrue("enhanced_skill.png" in path, "应该找到 enhanced_skill.png")

    def test_icon_find_sequence(self):
        """测试查找多段技能 (技能 2)"""
        print("Running: test_icon_find_sequence")
        # 查找 variant="2"
        path = self.asset_mgr.get_icon_path("TestChar", "skill", variant="2")
        self.assertIsNotNone(path)
        self.assertTrue("normal_skill_2.png" in path, "应该找到 normal_skill_2.png")

    def test_icon_fallback_to_general(self):
        """测试降级查找 (删除角色专属，看是否去找通用)"""
        print("Running: test_icon_fallback_to_general")
        # 1. 删掉角色的 normal_attack 文件夹
        shutil.rmtree(os.path.join(self.assets_root, "TestChar", "normal_attack"))

        # 2. 再次查找
        path = self.asset_mgr.get_icon_path("TestChar", "basic")

        self.assertIsNotNone(path)
        self.assertTrue("_general" in path, "应该降级查找到通用文件夹")
        self.assertTrue("sword" in path, "应该根据 txt 映射找到 sword 子文件夹")

    def test_button_mapping_dynamic(self):
        """测试按键映射 (含 Intro 动态参数)"""
        print("Running: test_button_mapping_dynamic")

        # 1. 普通按键
        path = self.asset_mgr.get_button_path("basic")
        self.assertIsNotNone(path)
        self.assertTrue("xbox_x.png" in path)

        # 2. 切人 (动态参数)
        path_intro_1 = self.asset_mgr.get_button_path("intro", target_index=1)
        self.assertIsNotNone(path_intro_1)
        self.assertTrue("dpad_up.png" in path_intro_1, "Intro 1 应该对应 dpad_up")

    def test_missing_resource(self):
        """测试缺失资源是否返回 None 而不是报错"""
        print("Running: test_missing_resource")
        path = self.asset_mgr.get_icon_path("TestChar", "ult")  # 我们没创建 ult 文件夹
        self.assertIsNone(path, "不存在的资源应该返回 None")


if __name__ == '__main__':
    unittest.main()