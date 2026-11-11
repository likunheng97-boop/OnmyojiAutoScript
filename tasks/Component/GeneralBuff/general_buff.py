# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

import cv2
import numpy as np

from tasks.Component.GeneralBuff.assets import GeneralBuffAssets
from module.atom.ocr import RuleOcr
from module.atom.image import RuleImage
from tasks.base_task import BaseTask
from module.logger import logger
from module.base.timer import Timer


class GeneralBuff(BaseTask, GeneralBuffAssets):

    # ================= 加成开关的定位与状态判据 =================
    # 2026-11-11 用同一台机器「关→开」两张截图实测标定的，1280x720。
    #
    # 为什么不再用模板判开关：老代码拿 I_OPEN_YELLOW（13x18 的黄色小图标）
    # 去认「是否已开启」，实测在**关闭态**的开关上也能匹配到 0.726（阈值 0.6），
    # 于是 soul_on() 第一句就返回 True，从来不去点 —— 日志写 confirmed ON，
    # 实际上加成一直是关的。颜色判据在同一张图上区分度是 20 vs 181，可靠得多。
    #
    # 位置：行图标（I_SOUL / I_AWAKE …）匹配上之后 roi_front 就是该行图标的外框。
    # 圆的中心基本等于「图标框的垂直中心」（实测误差 ≤2px：I_AWAKE 框中心 152.5
    # 对真实开关 153，I_SOUL 框中心 223 对 221），横向中心 + 476 就是开关中心
    # （御魂行 396.5 + 476 = 872.5，真实开关 859~887）。老代码写死 +364，算出来
    # x 760~840，永远点空。
    BUFF_SWITCH_OFFSET_X = 476
    # 「剩余天数」药丸的取样框，相对开关中心 (x0, y0, x1, y1)。
    # 整段都取、不取单点：文字是白描边、长度不一（"140天" 比 "7天" 宽得多），
    # 单点很容易正好落在笔画上，把均值拉成面板底色。
    BUFF_TAG_BOX = (-85, -13, -10, 13)
    # 状态判据 = 取样框内「中间通道 - 最小通道」的 75 分位：
    #   关闭态红标签 (206,33,13)  -> 20  （整行 p75 = 25）
    #   开启态金黄   (237,181,0)  -> 181 （整行 p75 = 174）
    #   面板底色（这行没有标签）(225,213,202) -> 11，落在关闭侧，
    #   符合「没标签 = 没生效 = 需要点开」的直觉。
    # 用 mid-min 而不是「绿通道 - 蓝通道」，是因为它对 RGB / BGR 两种通道顺序都
    # 成立（红标签和金黄标签的最小通道都是蓝），不依赖截图方法的实现细节。
    # 取 75 分位而不是中位数：开启态的黄色若是被长文字挤成小面积，中位数会掉下来，
    # 而 75 分位只要求四分之三的像素是黄的，抗「文字占位」更强。
    BUFF_ON_THRESHOLD = 80
    BUFF_OFF_THRESHOLD = 45

    def buff_row_anchor(self, target: RuleImage) -> tuple | None:
        """定位某一行加成，返回 (行中心 y, 开关中心 x)；认不出这一行返回 None。

        调用前需要已经 screenshot 过。target 是大图标（I_SOUL / I_AWAKE /
        I_GOLD_50 …），match 成功后 roi_front 会被更新成实际匹配位置。
        """
        if not target.match(self.device.image):
            return None
        center_y = target.roi_front[1] + target.roi_front[3] / 2
        switch_x = int(target.front_center()[0] + self.BUFF_SWITCH_OFFSET_X)
        return center_y, switch_x

    def buff_switch_state(self, center_y: float, switch_x: int) -> str:
        """判断该行开关是 'on' / 'off' / 'unknown'（只看颜色，约 0.2ms）。"""
        img = self.device.image
        b = self.BUFF_TAG_BOX
        x0, x1 = switch_x + b[0], switch_x + b[2]
        y0, y1 = int(center_y) + b[1], int(center_y) + b[3]
        if x0 < 0 or y0 < 0 or y1 > img.shape[0] or x1 > img.shape[1]:
            return 'unknown'
        box = img[y0:y1, x0:x1]
        if box.size == 0:
            return 'unknown'
        box = box.astype(np.int16)
        # 逐像素算「中间通道 - 最小通道」，再取 75 分位压掉文字描边和噪点
        mid = np.median(box, axis=2)          # (h, w)
        score = float(np.percentile(mid - box.min(axis=2), 75))
        if score >= self.BUFF_ON_THRESHOLD:
            return 'on'
        if score <= self.BUFF_OFF_THRESHOLD:
            return 'off'
        logger.info(f'Buff switch color score {score:.0f} is ambiguous')
        return 'unknown'

    def click_buff_switch(self, center_y: float, switch_x: int) -> None:
        """点该行的圆形开关。用坐标点，不再依赖模板匹配到的位置。"""
        self.device.click(switch_x, int(center_y))
        self.device.sleep(0.5)

    def open_buff(self):
        """
        打开buff的总界面
        :return: 打开成功 True，超时放弃 False（调用方已有 soul_on() 兜底）
        """
        logger.info('Open buff')
        # 原来这是个没有出口的 while：只要 I_BUFF_1 认不出来就既不点击也不退出，
        # 一分钟零点击后 device 判 GameStuckError（detect_record 是空集），
        # 强杀游戏重启，任务连续失败三次直接退出。2026-11-11 09:29 换新版 UI 的
        # oas1 就是这么挂的。加超时 + 两套 UI 的入口都试一遍。
        timeout = Timer(25).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_CLOUD):
                break
            # 经典樱花庭院是左上角那个小图标；2026-11 水墨新版是偏左的竖排「加成」木牌
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue
            if self.appear_then_click(self.I_BUFF_1_NEW, interval=2):
                continue
            if timeout.reached():
                logger.warning('加成面板 25 秒没打开（两套入口都没认出来），跳过加成继续刷本')
                return False

        # 这段原来是无限循环：认不出觉醒那一行就一直滑，滑到任务被判定卡死为止。
        # 「御魂加成」排在第 2 行，本来就该立刻出现；给 20 秒上限，到点就带着
        # 当前（可能已滚动的）位置继续往下走，交给 soul_on 自己再定位一次。
        check_image = self.I_AWAKE
        timeout = Timer(20).start()
        while 1:
            self.screenshot()
            if self.appear(check_image):
                break
            if timeout.reached():
                logger.warning('加成面板里 20 秒没找到觉醒那一行，继续尝试开御魂加成')
                break

            self.swipe(self.S_BUFF_UP, interval=2)
        return True

    def close_buff(self):
        """
        关闭buff的总界面, 但是要确保buff界面已经打开了
        :return:
        """
        logger.info('Close buff')
        # 同样两套 UI 都试：面板开着却关不掉的话，run() 里会一直卡在这里空转
        timeout = Timer(20).start()
        while 1:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue
            if self.appear_then_click(self.I_BUFF_1_NEW, interval=2):
                continue
            if timeout.reached():
                logger.warning('加成面板 20 秒关不掉，先继续（下一次进庭院会重新判断）')
                return

    def get_area(self, buff: RuleOcr) -> tuple:
        """
        获取要点击的开关buff的区域
        :param cls:
        :param image:
        :param buff:
        :return:  如果没有就返回None
        """
        # 防止邀请框挡住BUFF框架
        self.reject_invite()
        self.screenshot()
        area = buff.ocr(self.device.image)
        if area == tuple([432.0, 143.0, 325.0, 21.0]):
            logger.info(f'No {buff.name} buff')
            return None

        # 开始的x坐标就是文字的右边
        start_x = area[0] + area[2] + 10  # 10是文字和开关之间的间隔
        start_y = area[1] - 10
        width = 80  # 开关的宽度 80够了
        height = area[3] + 20
        return int(start_x), int(start_y), int(width), int(height)

    def set_switch_area(self, area):
        """
        设置开关的区域
        :param area:
        :return:
        """
        self.I_OPEN_YELLOW.roi_back = list(area)  # 动态设置roi
        self.I_CLOSE_RED.roi_back = list(area)

    def gold_50(self, is_open: bool = True):
        """
        金币50buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} gold 50 buff')
        self.screenshot()
        area = self.get_area(self.O_GOLD_50)
        if not area:
            logger.warning('No gold 50 buff')
            return None
        self.set_switch_area(area)
        if is_open:
            if not self.ui_click(click=self.I_CLOSE_RED, stop=self.I_OPEN_YELLOW, interval=1, timeout=10):
                logger.warning('Open gold 50 buff failed')
        else:
            if not self.ui_click(click=self.I_OPEN_YELLOW, stop=self.I_CLOSE_RED, interval=1, timeout=10):
                logger.warning('Close gold 50 buff failed')

    def gold_100(self, is_open: bool = True):
        """
        金币100buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} gold 100 buff')
        self.screenshot()
        area = self.get_area(self.O_GOLD_100)
        if not area:
            logger.warning('No gold 100 buff')
            return None
        self.set_switch_area(area)
        if is_open:
            if not self.ui_click(click=self.I_CLOSE_RED, stop=self.I_OPEN_YELLOW, interval=1, timeout=10):
                logger.warning('Open gold 100 buff failed')
        else:
            if not self.ui_click(click=self.I_OPEN_YELLOW, stop=self.I_CLOSE_RED, interval=1, timeout=10):
                logger.warning('Close gold 100 buff failed')

    def exp_50(self, is_open: bool = True):
        """
        经验50buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} exp 50 buff')
        while 1:
            self.screenshot()
            area = self.get_area(self.O_EXP_50)
            if not area:
                logger.warning('No exp 50 buff')
                continue
            self.set_switch_area(area)

            if not self.appear(self.I_OPEN_YELLOW) and not self.appear(self.I_CLOSE_RED):
                self.device.swipe(p2=(530, 240), p1=(580, 320))
                time.sleep(1)
            else:
                break

        if is_open:
            if not self.ui_click(click=self.I_CLOSE_RED, stop=self.I_OPEN_YELLOW, interval=1, timeout=10):
                logger.warning('Open exp 50 buff failed')
        else:
            if not self.ui_click(click=self.I_OPEN_YELLOW, stop=self.I_CLOSE_RED, interval=1, timeout=10):
                logger.warning('Close exp 50 buff failed')

    def exp_100(self, is_open: bool = True):
        """
        经验100buff
        :param is_open: 是否打开
        :return:
        """
        logger.info(f'{"Open" if is_open else "Close"} exp 100 buff')
        while 1:
            self.screenshot()
            area = self.get_area(self.O_EXP_100)
            if not area:
                logger.warning('No exp 100 buff')
                continue
            self.set_switch_area(area)

            if not self.appear(self.I_OPEN_YELLOW) and not self.appear(self.I_CLOSE_RED):
                self.device.swipe(p2=(530, 240), p1=(580, 320))
                time.sleep(1)
            else:
                break

        if is_open:
            if not self.ui_click(click=self.I_CLOSE_RED, stop=self.I_OPEN_YELLOW, interval=1, timeout=10):
                logger.warning('Open exp 100 buff failed')
        else:
            if not self.ui_click(click=self.I_OPEN_YELLOW, stop=self.I_CLOSE_RED, interval=1, timeout=10):
                logger.warning('Close exp 100 buff failed')

    def get_area_image(self, target: RuleImage) -> list:
        """
        获取觉醒加成或者是御魂加成所要点击的区域
        因为实在的图片比ocr快
        :param image:
        :param target:
        :return:
        """
        self.reject_invite()
        self.screenshot()

        anchor = self.buff_row_anchor(target)
        if not anchor:
            logger.warning(f'No {target.name} buff')
            return None
        center_y, switch_x = anchor
        # 老代码这里写的是 front_center()[0] + 364，只对旧版 UI 成立：在这张
        # 1280x720 的加成面板上算出来是 x 760~840，而真正的圆形开关在 859~887，
        # 永远点空。现在按实测偏移定位，并以开关中心为基准左右各留 25px。
        height = int(target.roi_front[3]) + 8
        return [switch_x - 25, int(center_y - height / 2), 50, height]

    def set_buff_by_row(self, target: RuleImage, is_open: bool, max_attempts: int = 6) -> bool:
        """把某一行加成切到指定状态，并确认真的切到位了。

        统一走「颜色判据 + 实测坐标点击」，不再用 I_OPEN_YELLOW / I_CLOSE_RED 模板：
        那两个模板在**关闭态**的开关上也会命中（实测 0.726，阈值 0.6），
        ui_click(click=I_CLOSE_RED, stop=I_OPEN_YELLOW) 会立刻以为已经停了，
        一个点击都不发。
        """
        want = 'on' if is_open else 'off'
        for attempt in range(1, max_attempts + 1):
            self.reject_invite()
            self.screenshot()

            anchor = self.buff_row_anchor(target)
            if not anchor:
                logger.warning(f'{target.name} row not found, scroll and retry ({attempt}/{max_attempts})')
                self.swipe(self.S_BUFF_UP, interval=1)
                continue

            center_y, switch_x = anchor
            state = self.buff_switch_state(center_y, switch_x)

            if state == want:
                logger.info(f'{target.name} confirmed {want.upper()} (attempt {attempt})')
                return True

            if state == 'unknown':
                # 颜色读不出明确的开/关：可能是换皮或特效干扰，先滑一下重新定位
                logger.warning(f'{target.name} switch state unclear, scroll and retry ({attempt}/{max_attempts})')
                self.swipe(self.S_BUFF_UP, interval=1)
                continue

            logger.info(f'{target.name} is {state.upper()}, click switch -> {want.upper()} ({attempt}/{max_attempts})')
            self.click_buff_switch(center_y, switch_x)

        logger.error(f'{target.name} still not {want.upper()} after {max_attempts} attempts')
        return False

    def soul_on(self, max_attempts: int = 6) -> bool:
        """
        打开御魂加成，并且要「确认真的开启了」才算成功。

        2026-11-11 重写：原来用 I_OPEN_YELLOW 模板判「已开启」，而它在**关闭态**
        的开关上也能匹配到 0.726（阈值 0.6）→ 第一次判断就返回 True，从来没真正
        点过开关。现在改成颜色判据（关闭态 21 / 开启态 177，见类头注释），并且
        用实测坐标点击，不再依赖模板匹配到的位置。

        :param max_attempts: 最大尝试次数（有界循环，避免无限重试卡死任务）
        :return: True 表示已确认御魂加成处于开启状态
        """
        return self.set_buff_by_row(self.I_SOUL, True, max_attempts)

    def awake(self, is_open: bool = True):
        """
        觉醒buff
        :param is_open: 是否打开
        :return: True 表示已确认切到目标状态
        """
        logger.info(f'{"Open" if is_open else "Close"} awake buff')
        return self.set_buff_by_row(self.I_AWAKE, is_open)

    def soul(self, is_open: bool = True):
        """
        御魂buff
        :param is_open: 是否打开
        :return: True 表示已确认切到目标状态
        """
        logger.info(f'{"Open" if is_open else "Close"} soul buff')
        return self.set_buff_by_row(self.I_SOUL, is_open)

    def reject_invite(self):
        from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
        while 1:
            self.screenshot()
            if not (self.appear(gia.I_I_REJECT_1) or self.appear(gia.I_I_REJECT_2) or self.appear(gia.I_I_REJECT_3)):
                break
            if self.appear(gia.I_I_REJECT_3):
                self.click(gia.I_I_REJECT_3, 6)
                continue
            if self.appear(gia.I_I_REJECT_2):
                self.click(gia.I_I_REJECT_2, 6)
                continue
            if self.appear(gia.I_I_REJECT_1):
                self.click(gia.I_I_REJECT_1, 6)
                continue


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = GeneralBuff(c, d)

    t.open_buff()
    # t.screenshot()
    #
    t.awake(is_open=True)
    t.soul(is_open=True)
    t.gold_50(is_open=False)
    t.gold_100(is_open=False)
    t.exp_50(is_open=True)
    t.exp_100(is_open=True)
