import logging
import os
from logging.handlers import RotatingFileHandler

# 创建 logs 文件夹
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(log_dir, "hekili_running.log")

# 配置 Logger
logger = logging.getLogger("WuWa_Hekili")
logger.setLevel(logging.DEBUG)  # 记录所有级别的日志

# 如果已经有 handler，不重复添加
if not logger.handlers:
    # 1. 输出到文件的 Handler (最大 2MB，保留 3 个备份)
    file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_formatter)

    # 2. 输出到控制台的 Handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# 方便其他文件直接 import log 就能用
log = logger