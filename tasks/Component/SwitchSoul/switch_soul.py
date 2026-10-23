# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from typing import Union

from module.atom.click import RuleClick
from module.atom.long_click import RuleLongClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.logger import logger

from tasks.base_task import BaseTask
from tasks.GameUi.assets import GameUiAssets
from tasks.Component.GeneralInvite.assets import GeneralInviteAssets
from tasks.Component.GeneralInvite.config_invite import InviteConfig, InviteNumber, FindMode
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets



def switch_parser(switch_str: str) -> tuple:
    switch_list = switch_str.split(',')
    if len(switch_list) != 2:
        raise ValueError('Switch_str must be 2 length')
    return int(switch_list[0]), int(switch_list[1])


class SwitchSoul(BaseTask, SwitchSoulAssets):

    def goto_shikigami_records(self, button):
        """
        进入式神录
        """
        while 1:
            self.screenshot()
            if self.appear(GameUiAssets.I_CHECK_RECORDS):
                break
            if self.appear_then_click(button, interval=1.5):
                continue
        logger.info('Entry shikigami records')

    def exit_shikigami_records(self) -> None:
        """
        退出式神录的界面

        原逻辑只在 I_SOU_CHECK_IN 命中时才去点返回键；更换幕间(式神录)皮肤后该模板失效，
        会直接跳出循环、停在式神录里。这里补一层 OCR 兜底：
        只要还能读到左上角「预设」按钮，就认为仍停在式神录，按返回键坐标再点，最多 4 次。
        :return:
        """
        fallback = 0
        while 1:
            self.screenshot()
            if self.appear(self.I_SOU_CHECK_IN):
                if self.appear_then_click(self.I_RECORD_SOUL_BACK, interval=3.5):
                    continue
                continue
            # ---- 以下为 OCR 兜底（模板失效时才走到） ----
            if not self.ocr_appear(self.O_SS_PRESET_BTN):
                break
            if fallback >= 4:
                logger.warning('Shikigami records still detected after 4 fallback clicks, give up')
                break
            fallback += 1
            x, y = self.I_RECORD_SOUL_BACK.coord()
            logger.info(f'Exit shikigami records by coordinate, fallback {fallback}/4')
            self.device.click(x=x, y=y, control_name=self.I_RECORD_SOUL_BACK.name)
            sleep(2)
        logger.info('Exit shikigami records')


    def run_switch_soul(self, target: tuple | list[tuple] | str):
        """
        保证在式神录的界面
        :return:
        """
        if isinstance(target, str):
            try:
                target = switch_parser(target)
            except ValueError:
                logger.error('Switch soul config error')
                return
        if not self.click_preset():
            return
        self.switch_souls(target)

    def preset_panel_opened(self) -> bool:
        """
        判断「队伍预设」面板是否已经打开。
        模板优先（默认皮肤走老路，行为不变），模板全都没命中时用 OCR 兜底，
        这样更换幕间(式神录)皮肤后依然能判断。
        """
        if self.appear(self.I_SOU_TEAM_PRESENT):
            return True
        for switch in (self.I_SOU_SWITCH_1, self.I_SOU_SWITCH_2,
                       self.I_SOU_SWITCH_3, self.I_SOU_SWITCH_4):
            if self.appear(switch):
                return True
        # ---- 以下为 OCR 兜底 ----
        if not self.ocr_appear(self.O_SS_PANEL_TITLE):
            return False
        # 标题命中还不够，再确认右侧分组栏确实读到了分组名，避免在式神录主页误判
        results = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
        return len([r for r in results if r.score >= 0.6]) > 0

    def click_preset(self) -> bool:
        """
        点击预设
        优先 OCR 识别「预设」两个字，识别不到再退回旧的模板匹配。
        :return: 是否成功进入「队伍预设」面板
        """
        attempts = 0
        while 1:
            self.screenshot()
            if self.preset_panel_opened():
                logger.info('Click preset in switch soul')
                return True
            if attempts >= 4:
                logger.error('Preset panel not opened after 4 clicks, give up switching soul')
                return False
            if self.ocr_appear_click(self.O_SS_PRESET_BTN, interval=3):
                attempts += 1
                continue
            if self.appear(self.I_SOUL_PRESET) and self.click(self.I_SOUL_PRESET, interval=3):
                attempts += 1
                continue

    def sure_visible(self) -> bool:
        """
        切换御魂的「确定」弹窗是否出现
        """
        if self.appear(self.I_SOU_SWITCH_SURE):
            return True
        return bool(self.ocr_appear(self.O_SS_SURE))

    def click_sure(self, interval: float = None) -> bool:
        """
        点击「确定」弹窗。模板优先，模板没命中就用 OCR 定位「确定」两个字。
        :return: 是否出现了确定弹窗（不代表一定点到了）
        """
        if self.appear(self.I_SOU_SWITCH_SURE):
            self.click(self.I_SOU_SWITCH_SURE, interval=interval)
            return True
        if not self.ocr_appear(self.O_SS_SURE, interval=interval):
            return False
        x, y = self.O_SS_SURE.coord()
        self.device.click(x=x, y=y, control_name=self.O_SS_SURE.name)
        return True

    def click_block_sure(self, interval: float = None) -> bool:
        """
        误触点到式神后弹出的「确定」。模板优先，OCR 兜底。
        """
        if self.appear_then_click(self.I_CHECK_BLOCK, interval=interval):
            return True
        return bool(self.ocr_appear_click(self.O_SS_BLOCK_SURE, interval=interval))

    def switch_soul_one(self, group: int, team: int) -> None:
        """
        设置一个队伍的预设御魂
        :param group: 只能是[1-7]
        :param team: 只能是[1-4]
        :return:
        """

        def get_group_assets(group: int) -> tuple:
            match = {
                1: tuple([self.C_SOU_GROUP_1, self.I_SOU_CHECK_GROUP_1]),
                2: tuple([self.C_SOU_GROUP_2, self.I_SOU_CHECK_GROUP_2]),
                3: tuple([self.C_SOU_GROUP_3, self.I_SOU_CHECK_GROUP_3]),
                4: tuple([self.C_SOU_GROUP_4, self.I_SOU_CHECK_GROUP_4]),
                5: tuple([self.C_SOU_GROUP_5, self.I_SOU_CHECK_GROUP_5]),
                6: tuple([self.C_SOU_GROUP_6, self.I_SOU_CHECK_GROUP_6]),
                7: tuple([self.C_SOU_GROUP_7, self.I_SOU_CHECK_GROUP_7]),
            }
            return match[group]

        def get_team_asset(team: int):
            match = {
                1: self.I_SOU_SWITCH_1,
                2: self.I_SOU_SWITCH_2,
                3: self.I_SOU_SWITCH_3,
                4: self.I_SOU_SWITCH_4,
            }
            return match[team]

        # 滑动至分组最上层(分組過多, 导致第一个分组显示不全)
        cur_text = ""
        while 1:
            self.screenshot()
            compare1 = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            ocr_text = str([result.ocr_text for result in compare1])
            # 相等时 滑动到最上层
            if cur_text == ocr_text:
                break
            cur_text = ocr_text
            # 向上滑动
            self.swipe(self.S_SS_GROUP_SWIPE_UP, 1.5)
            # 等待滑动动画
            sleep(0.5)

        if group < 1 or group > 7:
            raise ValueError('Switch soul_one group must be in [1-7]')
        if team < 1 or team > 4:
            raise ValueError('Switch soul_one team must be in [1-4]')
        # 这一步是选择组
        target_click, target_check = get_group_assets(group)
        # while 1:
        #     self.screenshot()
        #     if self.click(target_click, interval=1):
        #         continue
        #     if self.appear(target_check):
        #         break
        # 2023.8.5 修改为无反馈的点击切换
        for i in range(2):
            self.click(target_click)
            sleep(0.5)
        # 点击队伍
        target_team = get_team_asset(team)
        for i in range(3):
            sleep(0.8)
            self.screenshot()
            if self.click_sure():
                while 1:
                    self.click_sure(3)
                    self.screenshot()
                    if self.click_block_sure(3):
                        continue
                    if not self.sure_visible():
                        break
                continue
            # 队伍「切换」按钮的位置是固定的，直接按坐标点击。
            # 不再要求模板命中：更换幕间皮肤后模板会失效，但坐标不变。
            self.click(target_team, interval=3)
        # 兜底若还出现确认按钮则点击
        for _ in range(6):
            self.screenshot()
            if not self.sure_visible():
                break
            self.click_sure(1)
        logger.info(f'Switch soul_one group {group} team {team}')

    def switch_souls(self, target: tuple or list[tuple]) -> None:
        """
        切换御魂
        :param target: [(1, 1), (2, 2), (3, 3), (4, 4)]  或者是单独的一个元组(4, 4) 第一个是组, 第二个是队伍
        :return:
        """
        if isinstance(target, tuple):
            target = [target]
        for group, team in target:
            group = int(group)
            team = int(team)
            self.switch_soul_one(group, team)

    def run_switch_soul_by_name(self, groupName, teamName):
        """
        保证在式神录的界面
        :return:
        """
        if not isinstance(groupName, str) or not isinstance(teamName, str):
            return
        # 名字为空时下面的翻页查找会永远找不到，直接跳过
        if not groupName.strip() or not teamName.strip():
            logger.error(f'Switch soul by name: empty group/team name ({groupName!r}, {teamName!r}), skip')
            return
        if not self.click_preset():
            return
        self.switch_soul_by_name(groupName, teamName)

    def switch_soul_by_name(self, groupName, teamName):
        """
        保证在式神录的界面
        :return:
        """
        logger.hr('Switch soul by name')
        # 滑动至分组最上层
        last_group_text = ''
        while 1:
            self.screenshot()
            compare1 = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            now_group_text = str([result.ocr_text for result in compare1])
            if now_group_text == last_group_text:
                break
            self.swipe(self.S_SS_GROUP_SWIPE_UP, 2)
            sleep(2.5)
            last_group_text = now_group_text
        logger.info('Swipe to top of group')

        # 判断有无目标分组
        while 1:
            self.screenshot()
            # 获取当前分组名
            results = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # 判断当前分组有无目标分组
            result = set(text1).intersection({groupName})
            # 有则跳出检测
            if result and len(result) > 0:
                break
            self.swipe(self.S_SS_GROUP_SWIPE_DOWN)
            sleep(1.5)
        logger.info('Swipe down to find target group')

        # 选中分组
        while 1:
            self.screenshot()
            self.O_SS_GROUP_NAME.keyword = groupName
            if self.ocr_appear_click(self.O_SS_GROUP_NAME):
                break
        logger.info(f'Select group {groupName}')

        # 滑动至阵容最上层
        last_team_text = ''
        while 1:
            self.screenshot()
            compare1 = self.O_SS_TEAM_NAME.detect_and_ocr(self.device.image)
            now_team_text = str([result.ocr_text for result in compare1])
            # 向上滑动
            if now_team_text == last_team_text:
                break
            self.swipe(self.S_SS_TEAM_SWIPE_DOWN, 1.5)
            sleep(2)
            last_team_text = now_team_text
        logger.info('Swipe to top of team')

        # 判断当前分组有无目标阵容
        while 1:
            self.screenshot()
            # 获取当前阵容名
            results = self.O_SS_TEAM_NAME.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # 判断当前分组有无目标阵容
            result = set(text1).intersection({teamName})
            # 有则跳出检测
            if result and len(result) > 0:
                break
            self.swipe(self.S_SS_TEAM_SWIPE_UP, 0.3)
        logger.info('Swipe up to find target team')

        # 选中分组
        while 1:
            self.screenshot()
            self.O_SS_TEAM_NAME.keyword = teamName
            if self.ocr_appear_click(self.O_SS_TEAM_NAME):
                break
        logger.info(f'Select team {teamName}')
        # 切换御魂
        cnt_click: int = 0
        self.O_SS_TEAM_NAME.keyword = teamName
        while 1:
            self.screenshot()
            if cnt_click >= 4:
                break
            if self.click_sure(interval=0.8):
                continue
            if self.ocr_appear_click_team_switch(self.O_SS_TEAM_NAME, interval=1.5):
                cnt_click += 1
                continue
        logger.info(f'Switch soul_one group {groupName} team {teamName}')

    def ocr_appear_click_team_switch(self, target: RuleOcr, interval: float = None) -> bool:
        """
        OCR 命中阵容名后，点击该行右侧的「切换」按钮。

        旧实现要再匹配一次 I_SOU_CLICK_PRESENT(深色切换图标, threshold=0.9) 才肯点，
        图标颜色随幕间皮肤变化就会失效。这里改成：x 取切换按钮所在列的坐标
        （仍走 I_SOU_CLICK_PRESENT 的 roi，皮肤替换时一并生效），
        y 取 OCR 命中行的垂直中心，不再依赖模板匹配。
        :param target: 阵容名 OCR 规则（keyword 需已设置为目标阵容名）
        :param interval:
        :return:
        """
        if not self.ocr_appear(target, interval):
            return False
        x, _ = self.I_SOU_CLICK_PRESENT.coord()
        x1, y1, w1, h1 = target.area
        self.device.click(x=x, y=y1 + h1 // 2, control_name=target.name)
        return True

    def ocr_appear_click_by_rule(self,
                                 target: RuleOcr,
                                 action: Union[RuleClick, RuleLongClick] = None,
                                 interval: float = None,
                                 duration: float = None) -> bool:
        """
        ocr识别目标，如果目标存在，则触发动作
        :param target:
        :param action:
        :param interval:
        :param duration:
        :return:
        """
        appear = self.ocr_appear(target, interval)

        if not appear:
            return False

        x1, y1, w1, h1 = target.area
        x, y = action.coord()

        self.device.click(x=x, y=y1, control_name=target.name)
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    s = SwitchSoul(c, d)

    s.click_preset()
    # s.switch_soul_one(4, 1)
    # s.switch_soul_by_name('契灵', '茨球')
    s.switch_soul_by_name('默认分组', '队伍5')
