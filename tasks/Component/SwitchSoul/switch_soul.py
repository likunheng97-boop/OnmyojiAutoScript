# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from typing import Union

import cv2

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
        # switch_group_team 默认就是 "-1,-1"（表示没填）。原实现会一路走进
        # switch_soul_one 然后抛 ValueError，把整个任务打断；这里先判掉，
        # 让「只勾了启用、没填序号」的配置安静地跳过，不影响后续打怪。
        targets = target if isinstance(target, list) else [target]
        try:
            invalid = any(not (1 <= int(g) <= 7) or not (1 <= int(t) <= 4) for g, t in targets)
        except (TypeError, ValueError):
            logger.error(f'Switch soul config error: {target}')
            return
        if invalid:
            logger.info(f'Switch soul by index skipped: group/team not configured ({target})')
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
            # 队伍「切换」按钮：y 取该行坐标，x 交给模板定位。
            # 幕间皮肤会把整排图标右移（老皮肤 978 / 新皮肤 1014），
            # 模板都失配时宁可不点，也不要在旧坐标上盲点（那里可能是『≡』菜单）。
            switch_x = self.team_switch_button_x()
            if switch_x is None:
                break
            _, switch_y = target_team.coord()
            self.device.click(x=switch_x, y=switch_y, control_name=target_team.name)
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
        miss: int = 0
        sure_seen: bool = False
        self.O_SS_TEAM_NAME.keyword = teamName
        while 1:
            self.screenshot()
            if cnt_click >= 4 or miss >= 5:
                break
            if self.click_sure(interval=0.8):
                sure_seen = True
                miss = 0
                continue
            if self.ocr_appear_click_team_switch(self.O_SS_TEAM_NAME, interval=1.5):
                cnt_click += 1
                miss = 0
                continue
            # 点不到（模板失配 / OCR 间歇性读不到）就累加失败次数，避免死循环
            miss += 1
        if cnt_click and not sure_seen:
            # 点了「切换」但始终没弹「确定」：多半是点到了同一排的其它图标（≡ 菜单 / 分享），
            # 把日志写清楚，方便下次直接看出是皮肤适配问题而不是「点了没反应」。
            logger.warning(f'Switch soul: 已点击「切换」{cnt_click} 次但始终未出现「确定」弹窗，'
                           f'请确认队伍预设面板的切换图标位置（皮肤适配）')
        if miss >= 5:
            logger.warning(f'Switch soul: 连续 {miss} 次点不到「切换」，跳过分组 {groupName} 阵容 {teamName}')
        logger.info(f'Switch soul_one group {groupName} team {teamName}')

    # 灰度匹配阈值。实测四套皮肤/主题最低 0.910（青竹），背景次高点只有 0.46，
    # 取 0.85 既能跨主题命中，又离背景噪声很远。
    SWITCH_GRAY_THRESHOLD: float = 0.85

    def _gray_switch_x(self) -> Union[int, None]:
        """
        用**灰度**模板匹配定位『切换』图标，返回可点击的 x。

        为什么不用 RuleImage.match()（RGB 三通道）：这个图标只有灰白笔画，
        真正随皮肤变化的是**背景配色**，而 RGB 匹配会把这部分背景也算进相关系数，
        于是同一个模板在绿调皮肤上只有 0.854、在青竹主题只有 0.850（勉强过线）。
        丢掉色彩只留亮度后，同一个模板在四套皮肤上分别是
        1.000 / 0.964 / 0.966 / 0.910 —— 最低分也高出阈值 6 个百分点。

        只在 icon 列（x 960~1040）接受命中，避免在背景上误匹配。
        :return: 命中返回图标中心的 x，未命中返回 None
        """
        rule = self.I_SOU_CLICK_PRESENT_3
        x0, y0, w0, h0 = rule.roi_back
        image = self.device.image
        if image is None or len(getattr(image, 'shape', ())) != 3:
            return None
        src = image[y0:y0 + h0, x0:x0 + w0]
        tpl = rule.image
        if src.size == 0 or tpl.size == 0:
            return None
        src_gray = cv2.cvtColor(src, cv2.COLOR_RGB2GRAY)
        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_RGB2GRAY)
        if tpl_gray.shape[0] > src_gray.shape[0] or tpl_gray.shape[1] > src_gray.shape[1]:
            return None
        res = cv2.matchTemplate(src_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        center = x0 + max_loc[0] + tpl_gray.shape[1] // 2
        if max_val < self.SWITCH_GRAY_THRESHOLD:
            return None
        if not 960 <= center <= 1040:
            logger.warning(f'Switch soul: 灰度匹配命中位置异常 x={center}(score={max_val:.3f})，忽略')
            return None
        logger.info(f'Switch soul: 切换按钮灰度匹配 score={max_val:.3f} -> x={center}')
        return center

    def team_switch_button_x(self) -> Union[int, None]:
        """
        定位「队伍预设」列表里行内『切换』按钮的 x 坐标。

        这个图标的**位置和配色都会随幕间(式神录)皮肤变化**，目前已见四套：
            默认主题 / 木质 / 绿调 -> 图标中心 x≈992
            青竹 / 绯夜猎刃         -> 图标中心 x≈1015
        所以先用**灰度匹配**（不受配色影响，见 `_gray_switch_x`）走主路径，
        失配再退回「三模板 RGB 依次尝试」的老路径，全部失败才返回 None。

        返回 None 时调用方必须放弃点击：按固定坐标盲点有可能打开『≡』编辑菜单，
        而菜单里就有「删除预设队伍」，比这次切不过去危险得多。

        center 护栏（960~1040）两条路径都有：只接受图标那一列的命中结果，
        防止模板在背景上误匹配到别处。
        """
        x = self._gray_switch_x()
        if x is not None:
            return x

        for rule in (self.I_SOU_CLICK_PRESENT_3,
                     self.I_SOU_CLICK_PRESENT_2,
                     self.I_SOU_CLICK_PRESENT):
            if not rule.match(self.device.image):
                continue
            # 护栏用模板命中框的固定中心，避免 coord() 的随机点在边界抖动
            center = rule.roi_front[0] + rule.roi_front[2] // 2
            if not 960 <= center <= 1040:
                logger.warning(f'Switch soul: {rule.name} 命中位置异常 x={center}，忽略')
                continue
            x, _ = rule.coord()
            logger.info(f'Switch soul: 切换按钮由 {rule.name} 定位到 x={center}')
            return x
        logger.warning('Switch soul: 切换按钮模板全部失配，跳过点击(幕间皮肤未适配?)')
        return None

    def ocr_appear_click_team_switch(self, target: RuleOcr, interval: float = None) -> bool:
        """
        OCR 命中阵容名后，点击该行右侧的「切换」按钮。

        旧实现要再匹配一次 I_SOU_CLICK_PRESENT(深色切换图标, threshold=0.9) 才肯点，
        图标颜色随幕间皮肤变化就会失效。这里改成：x 由模板动态定位(见 team_switch_button_x)，
        y 取 OCR 命中行的垂直中心，不再要求『切换』图标本身匹配成功。
        :param target: 阵容名 OCR 规则（keyword 需已设置为目标阵容名）
        :param interval:
        :return:
        """
        if not self.ocr_appear(target, interval):
            return False
        x = self.team_switch_button_x()
        if x is None:
            return False
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
