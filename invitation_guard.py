# -*- coding: utf-8 -*-
# 协作邀请看门狗 —— 把 BaseTask._burst() 里的「协作邀请处理」抽成可独立运行的小程序
#
# 背景：OAS 的协作邀请处理逻辑挂在 BaseTask.screenshot() 里，只有「有任务在跑」时
# 才会被触发。这个脚本脱离调度器，单独接管一个实例的截图循环，只做一件事：
# 看到协作邀请，就按配置点「×」忽略 / 拒绝 / 接受。
#
# 用法：
#   toolkit\python.exe invitation_guard.py oas1
#   toolkit\python.exe invitation_guard.py oas2 --mode ignore --interval 1.0
#   toolkit\python.exe invitation_guard.py oas1 --once --dry-run   # 只识别不点击
#
# 参数说明：
#   config        实例配置名（config/<name>.json），默认 oas1
#   --mode        处理方式，默认取配置里「当出现协作邀请时」的值
#                 ignore / reject / accept / only_jade / jade_and_food
#   --interval    没检测到邀请时的轮询间隔（秒），默认 1.5
#   --once        只检测一次就退出（诊断用）
#   --dry-run     只识别不点击
#   --force       即使检测到 OAS 后端在跑也强行启动（默认会拒绝，避免两边抢着点）
#
# 注意：本脚本与 OAS 后端**不要同时**操作同一个实例，否则两边都截图都点击会互相打断。
#       停掉后端、或者只对没跑任务的实例用。

import argparse
import datetime
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from module.config.config import Config
from module.device.device import Device
from tasks.GlobalGame.assets import GlobalGameAssets as A

# 模板 → 中文名，日志用
BUTTON_NAME = {
    'I_G_ACCEPT': '接受',
    'I_G_REJECT': '拒绝（对方会看到已拒绝）',
    'I_G_IGNORE': '忽略（点 × ，对方无拒绝提示）',
}


def log(msg: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def button_center(rule) -> tuple:
    """RuleImage.match() 会把 roi_front[0:2] 改成命中的绝对左上角，宽高保持模板尺寸。"""
    x, y, w, h = rule.roi_front
    return int(x + w / 2), int(y + h / 2)


def backend_active(config_name: str, within: float = 20.0) -> bool:
    """用当天日志文件的写入时间来粗略判断该实例的后端是否在跑。"""
    p = os.path.join(ROOT, 'log', f'{datetime.date.today()}_{config_name}.txt')
    if not os.path.exists(p):
        return False
    return (time.time() - os.path.getmtime(p)) < within


class InvitationGuard:
    def __init__(self, config_name: str, mode: str = None, dry_run: bool = False):
        log(f'加载配置 {config_name} ...')
        self.config = Config(config_name)
        self.device = Device(config=self.config)
        self.dry_run = dry_run

        default_mode = self.config.global_game.emergency.friend_invitation
        # pydantic 枚举取字符串值，兼容已经被转成 str 的情况
        default_mode = getattr(default_mode, 'value', default_mode)
        self.mode = mode or default_mode
        log(f'处理方式 = {self.mode}（{"来自命令行" if mode else "来自全局配置"}）')

        self.handled = 0

    # ------------------------------------------------------------------ 决策
    def pick_button(self, image):
        """返回本次要点的按钮；没有邀请返回 None。"""
        if not A.I_G_ACCEPT.match(image):
            return None
        if self.mode == 'accept':
            return A.I_G_ACCEPT
        if self.mode == 'reject':
            return A.I_G_REJECT
        if self.mode == 'only_jade':
            return A.I_G_ACCEPT if A.I_G_JADE.match(image) else A.I_G_IGNORE
        if self.mode == 'jade_and_food':
            if (A.I_G_JADE.match(image)
                    or A.I_G_CAT_FOOD.match(image)
                    or A.I_G_DOG_FOOD.match(image)):
                return A.I_G_ACCEPT
            return A.I_G_IGNORE
        # 默认按 ignore 处理，未知取值也不至于把邀请点成拒绝
        return A.I_G_IGNORE

    # ------------------------------------------------------------------ 单次
    def handle_once(self) -> bool:
        """检测一次；有邀请就处理掉。返回是否检测到邀请。"""
        self.device.screenshot()
        rule = self.pick_button(self.device.image)
        if rule is None:
            return False

        self.handled += 1
        log(f'检测到协作邀请（第 {self.handled} 次）')
        if self.dry_run:
            log(f'[dry-run] 本该点击「{BUTTON_NAME.get(rule.name, rule.name)}」')
            return True

        # 最多点 6 次；每次重新截图取坐标，避免动画期间坐标过期
        for attempt in range(1, 7):
            self.device.screenshot()
            image = self.device.image
            rule = self.pick_button(image)
            if rule is None:
                log('邀请已关闭')
                return True
            # 决策出来的按钮自身也必须真的命中模板，否则 roi_front 还是默认值，
            # 照那个坐标点就是瞎点（可能点到别处）。宁可这轮不动。
            if not rule.match(image):
                log(f'「{BUTTON_NAME.get(rule.name, rule.name)}」模板未命中，本轮不点击'
                    f'（可能需要重新截取该按钮的模板）')
                return True
            x, y = button_center(rule)
            # 小随机偏移，落点别每次都像素级一致
            x += random.randint(-3, 3)
            y += random.randint(-3, 3)
            log(f'点击「{BUTTON_NAME.get(rule.name, rule.name)}」@ ({x},{y})  [{attempt}/6]')
            self.device.click(x, y)
            time.sleep(0.8)

        log('连点 6 次仍未关闭，可能不是协作邀请界面，跳过本次')
        return True

    # ------------------------------------------------------------------ 主循环
    def run(self, interval: float = 1.5, once: bool = False) -> None:
        log(f'开始值守：{self.config.config_name}  serial={self.device.serial}')
        log('Ctrl+C 退出')
        try:
            while True:
                try:
                    self.handle_once()
                except Exception as e:            # 单次失败不要让整个值守挂掉
                    log(f'本次检测异常：{type(e).__name__}: {e}')
                if once:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            log('收到 Ctrl+C，退出')
        finally:
            log(f'结束，本次共处理 {self.handled} 次邀请')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='OAS 协作邀请看门狗：单独运行，按配置忽略/拒绝/接受协作邀请',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('config', nargs='?', default='oas1',
                        help='实例配置名，对应 config/<name>.json，默认 oas1')
    parser.add_argument('--mode', default=None,
                        choices=['ignore', 'reject', 'accept', 'only_jade', 'jade_and_food'],
                        help='处理方式，默认取全局配置「当出现协作邀请时」')
    parser.add_argument('--interval', type=float, default=1.5,
                        help='未检测到邀请时的轮询间隔（秒），默认 1.5')
    parser.add_argument('--once', action='store_true', help='只检测一次就退出')
    parser.add_argument('--dry-run', action='store_true', help='只识别不点击')
    parser.add_argument('--force', action='store_true', help='后端在跑也强行启动')
    args = parser.parse_args()

    if backend_active(args.config) and not args.force:
        log(f'检测到 {args.config} 的后端日志刚刚还在写，OAS 可能正在跑这个实例。')
        log('两边同时截图+点击会互相打断，请先停掉后端，或加 --force 强行启动。')
        return 2

    guard = InvitationGuard(args.config, mode=args.mode, dry_run=args.dry_run)
    guard.run(interval=args.interval, once=args.once)
    return 0


if __name__ == '__main__':
    sys.exit(main())
