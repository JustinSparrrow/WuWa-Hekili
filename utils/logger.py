import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from utils.paths import project_root

# 日志目录：项目根/logs。
# 必须走统一根查找：打包后 __file__ 在 _internal 里，用 dirname 反推会
# 把日志写进 _internal\logs，玩家永远找不到，日志也就白记了。
log_dir = os.path.join(str(project_root()), "logs")
os.makedirs(log_dir, exist_ok=True)

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

    # 2. 控制台日志：DEBUG 全量输出，方便开发时排查。
    #    打包成 windowed（-w）之后 sys.stderr 是 None，此时 StreamHandler
    #    每次输出都会走 logging 的错误分支刷屏，所以直接不加它。
    logger.addHandler(file_handler)
    if sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logger.addHandler(console_handler)

# 其它模块 `from utils.logger import log` 即可使用
log = logger
