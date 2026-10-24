import logging
import os
from logging.handlers import RotatingFileHandler

# 日志目录：项目根/logs（打包后位于 exe 同级目录）
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(log_dir, "hekili_running.log")

logger = logging.getLogger("WuWa_Hekili")
# 总开关放开到 DEBUG，各 handler 再自行收口
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # 1. 文件日志：只记 INFO 及以上
    #    每次按键都会产生的 debug 明细不再落盘，避免连招时频繁触发磁盘 IO；
    #    2MB 滚动，保留 3 份历史。
    file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

    # 2. 控制台日志：DEBUG 全量输出，方便开发时排查
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# 其它模块 `from utils.logger import log` 即可使用
log = logger
