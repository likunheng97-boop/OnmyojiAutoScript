# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random
from time import sleep
from datetime import time, datetime, timedelta

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.GeneralBuff.general_buff import GeneralBuff
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_soul_zones, page_shikigami_records
from tasks.Orochi.assets import OrochiAssets
from tasks.Orochi.config import Orochi, UserStatus, Layer
from tasks.TrueOrochi.assets import TrueOrochiAssets
from module.logger import logger
from module.exception import TaskEnd
from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr

# 战前「额外加成：好友+10% 组队+20% 亲友+10% / 点击屏幕继续」展示界面。
# 2026-10-30 18:46:58（log/error/1793357218730）第 51 局就卡在这个界面上，
# battle_wait 里没有任何分支认它，只能等 random_click_swipt 那 0.8% 的概率。
# 文字实测位于 1280×720 的 x≈475~805 / y≈555~585，ROI 取 (360,535,560,80)
# 后，在 log/error 全部 38 张历史截图上只命中本次卡死那一张，其余 0 误判。
O_CLICK_TO_CONTINUE = RuleOcr(roi=(360, 535, 560, 80), area=(360, 535, 560, 80),
                              mode="Full", method="Default", keyword="",
                              name="click_to_continue")
# 推进这个界面的落点：底部中央纯空白（沿用 reward_safe_b 实测 edge≈0.26% 的坐标），
# 避开中间那排式神头像（点头像会弹式神详情，反而更卡）
C_CLICK_TO_CONTINUE = RuleClick(roi_front=(720, 645, 200, 70),
                                roi_back=(720, 645, 200, 70),
                                name="click_to_continue")


class ScriptTask(GeneralBattle, GeneralInvite, GeneralBuff, GeneralRoom, GameUi, SwitchSoul, OrochiAssets, TrueOrochiAssets):

    def run(self) -> bool:
        # 御魂切换方式一
        if self.config.orochi.switch_soul.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(self.config.orochi.switch_soul.switch_group_team)

        # 御魂切换方式二
        if self.config.orochi.switch_soul.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(self.config.orochi.switch_soul.group_name,
                                         self.config.orochi.switch_soul.team_name)
        # 根据选层切换御魂
        self.orochi_switch_soul()

        limit_count = self.config.orochi.orochi_config.limit_count
        limit_time = self.config.orochi.orochi_config.limit_time
        self.current_count = 0
        self.limit_count: int = limit_count
        self.limit_time: timedelta = timedelta(hours=limit_time.hour, minutes=limit_time.minute, seconds=limit_time.second)

        config: Orochi = self.config.orochi
        if not self.is_in_battle(True):
            self.ui_get_current_page()
            self.ui_goto(page_main)
            if config.orochi_config.soul_buff_enable:
                self.open_buff()
                self.soul(is_open=True)
                self.close_buff()

        success = True
        match config.orochi_config.user_status:
            case UserStatus.LEADER: success = self.run_leader()
            case UserStatus.MEMBER: success = self.run_member()
            case UserStatus.ALONE: self.run_alone()
            case UserStatus.WILD: success = self.run_wild()
            case _: logger.error('Unknown user status')

        # 御魂结束后检测是否出现真蛇
        if config.orochi_config.check_true_orochi_enable:
            self.ui_get_current_page()
            self.ui_goto(page_soul_zones)
            self.orochi_enter()
            self.screenshot()
            if self.appear(self.I_FIND_TS):
                logger.info('Find true orochi after orochi battle, set TrueOrochi task to run now')
                self.set_next_run(task='TrueOrochi', success=False, finish=False, server=False, target=datetime.now())
        self.ui_goto(page_main)
        # 记得关掉
        if config.orochi_config.soul_buff_enable:
            self.open_buff()
            self.soul(is_open=False)
            self.close_buff()
        # 下一次运行时间
        if success:
            self.set_next_run('Orochi', finish=True, success=True)
        else:
            self.set_next_run('Orochi', finish=False, success=False)

        raise TaskEnd

    def orochi_enter(self) -> bool:
        logger.info('Enter orochi')
        while True:
            self.screenshot()
            if self.appear(self.I_FORM_TEAM):
                return True
            if self.appear_then_click(self.I_OROCHI, interval=1):
                continue

    def check_layer(self, layer: str) -> bool:
        """
        检查挑战的层数, 并选中挑战的层
        :return:
        """
        pos = self.list_find(self.L_LAYER_LIST, layer)
        if pos:
            self.device.click(x=pos[0], y=pos[1])
            return True

    def check_lock(self, lock: bool = True) -> bool:
        """
        检查是否锁定阵容, 要求在八岐大蛇界面
        :param lock:
        :return:
        """
        logger.info('Check lock: %s', lock)
        if lock:
            while 1:
                self.screenshot()
                if self.appear(self.I_OROCHI_LOCK):
                    return True
                if self.appear_then_click(self.I_OROCHI_UNLOCK, interval=1):
                    continue
        else:
            while 1:
                self.screenshot()
                if self.appear(self.I_OROCHI_UNLOCK):
                    return True
                if self.appear_then_click(self.I_OROCHI_LOCK, interval=1):
                    continue











    def run_leader(self):
        logger.info('Start run leader')
        self.ui_get_current_page()
        self.ui_goto(page_soul_zones)
        self.orochi_enter()
        layer = self.config.orochi.orochi_config.layer
        self.check_layer(layer)
        # https://github.com/runhey/OnmyojiAutoScript/issues/592
        self.config.orochi.general_battle_config.lock_team_enable = True
        self.check_lock(self.config.orochi.general_battle_config.lock_team_enable)
        # 创建队伍
        logger.info('Create team')
        while 1:
            self.screenshot()
            if self.appear(self.I_CHECK_TEAM):
                break
            if self.appear_then_click(self.I_FORM_TEAM, interval=1):
                continue
        # 创建房间
        self.create_room()
        self.ensure_private()
        self.create_ensure()

        # 邀请队友
        success = True
        is_first = True
        # 这个时候我已经进入房间了哦
        while 1:
            self.screenshot()
            # 无论胜利与否, 都会出现是否邀请一次队友
            # 区别在于，失败的话不会出现那个勾选默认邀请的框
            if self.check_and_invite(self.config.orochi.invite_config.default_invite):
                continue

            # 检查猫咪奖励
            if self.appear_then_click(self.I_PET_PRESENT, action=self.C_WIN_3, interval=1):
                continue

            if self.current_count >= self.limit_count:
                if self.is_in_room():
                    logger.info('Orochi count limit out')
                    break

            if datetime.now() - self.start_time >= self.limit_time:
                if self.is_in_room():
                    logger.info('Orochi time limit out')
                    break



            # 如果没有进入房间那就不需要后面的邀请
            if not self.is_in_room():
                if self.is_room_dead():
                    logger.warning('Orochi task failed')
                    success = False
                    break
                continue

            # 点击挑战
            if not is_first:
                if self.run_invite(config=self.config.orochi.invite_config):
                    self.run_general_battle(config=self.config.orochi.general_battle_config)
                else:
                    # 邀请失败，退出任务
                    logger.warning('Invite failed and exit this orochi task')
                    success = False
                    break

            # 第一次会邀请队友
            if is_first:
                if not self.run_invite(config=self.config.orochi.invite_config, is_first=True):
                    logger.warning('Invite failed and exit this orochi task')
                    success = False
                    break
                else:
                    is_first = False
                    self.run_general_battle(config=self.config.orochi.general_battle_config)

        # 当结束或者是失败退出循环的时候只有两个UI的可能，在房间或者是在组队界面
        # 如果在房间就退出
        if self.exit_room():
            pass
        # 如果在组队界面就退出
        if self.exit_team():
            pass

        self.ui_get_current_page()
        self.ui_goto(page_main)

        if not success:
            return False
        return True

    def run_member(self):
        logger.info('Start run member')
        self.ui_get_current_page()
        # self.ui_goto(page_soul_zones)
        # self.orochi_enter()
        # self.check_lock(self.config.orochi.general_battle_config.lock_team_enable)

        # 进入战斗流程
        self.device.stuck_record_add('BATTLE_STATUS_S')
        # 队员在庭院等队长邀请时一个点击都没有，stuck record 不会被任何点击刷新，
        # 300 秒一到就被判 GameStuckError 直接强杀游戏。
        # 见 log/error/1793372346525 / 1793372817517 / 1793373132811（2026-10-30
        # 22:54~23:12：队长 oas2 在 22:43 已经三次失败退出，队员 oas1 在庭院干等
        # 5 分钟连挂三次，最后整个 Orochi 任务被判失败要求人工接管）。
        # 在庭院等邀请是正常等待而不是卡死，所以等待期间清掉 stuck record；
        # 真正开战后 run_general_battle 会重新 add。
        # 另外自己给等待设个上限，超时就正常退出本任务让调度器稍后重试。
        idle_timeout = timedelta(minutes=5)
        idle_start = datetime.now()
        success = True
        while 1:
            self.screenshot()

            # 检查猫咪奖励
            if self.appear_then_click(self.I_PET_PRESENT, action=self.C_WIN_3, interval=1):
                continue

            if self.current_count >= self.limit_count:
                logger.info('Orochi count limit out')
                break
            if datetime.now() - self.start_time >= self.limit_time:
                logger.info('Orochi time limit out')
                break

            if self.check_then_accept():
                continue

            if self.is_in_room():
                idle_start = datetime.now()
                self.device.stuck_record_clear()
                if self.wait_battle(wait_time=self.config.orochi.invite_config.wait_time):
                    self.run_general_battle(config=self.config.orochi.general_battle_config)
                else:
                    break
            # 队长秒开的时候，检测是否进入到战斗中
            elif self.check_take_over_battle(False, config=self.config.orochi.general_battle_config):
                idle_start = datetime.now()
                continue
            else:
                # 还在庭院里等邀请
                self.device.stuck_record_clear()
                if datetime.now() - idle_start >= idle_timeout:
                    logger.warning('Member: still not invited after 5 minutes, exit this orochi task')
                    success = False
                    break

        while 1:
            # 有一种情况是本来要退出的，但是队长邀请了进入的战斗的加载界面
            if self.appear(self.I_CHECK_MAIN) or self.appear(self.I_CHECK_EXPLORATION):
                break
            # 如果可能在房间就退出
            if self.exit_room():
                pass
            # 如果还在战斗中，就退出战斗
            if self.exit_battle():
                pass


        self.ui_get_current_page()
        self.ui_goto(page_main)
        return success

    def run_alone(self):
        logger.info('Start run alone')
        self.ui_get_current_page()
        self.ui_goto(page_soul_zones)
        self.orochi_enter()
        layer = self.config.orochi.orochi_config.layer
        self.check_layer(layer)
        self.check_lock(self.config.orochi.general_battle_config.lock_team_enable)

        def is_in_orochi(screenshot=False) -> bool:
            if screenshot:
                self.screenshot()
            return self.appear(self.I_OROCHI_FIRE)

        while 1:
            self.screenshot()

            # 检查猫咪奖励
            if self.appear_then_click(self.I_PET_PRESENT, action=self.C_WIN_3, interval=1):
                continue

            if not is_in_orochi():
                continue

            if self.current_count >= self.limit_count:
                logger.info('Orochi count limit out')
                break
            if datetime.now() - self.start_time >= self.limit_time:
                logger.info('Orochi time limit out')
                break

            # 点击挑战
            while 1:
                self.screenshot()
                if self.appear_then_click(self.I_OROCHI_FIRE, interval=1):
                    pass

                if not self.appear(self.I_OROCHI_FIRE):
                    self.run_general_battle(config=self.config.orochi.general_battle_config)
                    break

        # 回去
        while 1:
            self.screenshot()
            if not self.appear(self.I_FORM_TEAM):
                break
            if self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1):
                continue

        self.ui_current = page_soul_zones
        self.ui_goto(page_main)

    def run_wild(self):
        logger.info('Start run wild')

        # 已经在战斗中不必初始化，保证已经组队开始战斗的情况下可以自动执行后续任务
        if not self.is_in_battle(True):
            self.ui_get_current_page()
            self.ui_goto(page_soul_zones)
            self.orochi_enter()
            layer = self.config.orochi.orochi_config.layer
            self.check_layer(layer)
            self.check_lock(self.config.orochi.general_battle_config.lock_team_enable)
            # 创建队伍
            logger.info('Create team')
            while 1:
                self.screenshot()
                if self.appear(self.I_CHECK_TEAM):
                    break
                if self.appear_then_click(self.I_FORM_TEAM, interval=1):
                    continue
            # 创建房间
            self.create_room()
            self.ensure_public()
            self.create_ensure()

        success = True
        while 1:
            self.screenshot()
            # 无论胜利与否, 都会出现是否邀请一次队友
            # 区别在于，失败的话不会出现那个勾选默认邀请的框
            if self.check_and_invite(self.config.orochi.invite_config.default_invite):
                continue

            # 检查猫咪奖励
            if self.appear_then_click(self.I_PET_PRESENT, action=self.C_WIN_3, interval=1):
                continue

            if self.current_count >= self.limit_count:
                if self.is_in_room():
                    logger.info('Orochi count limit out')
                    break

            if datetime.now() - self.start_time >= self.limit_time:
                if self.is_in_room():
                    logger.info('Orochi time limit out')
                    break

            if not self.is_in_room():
                if self.is_room_dead():
                    logger.warning('Orochi task failed')
                    success = False
                    break
                continue

            # 点击挑战
            logger.info('Wait for starting')
            while 1:
                self.screenshot()
                # 在进入战斗前必然会出现挑战界面，因此点击失败必须重复点击，防止卡在挑战界面，
                # 点击成功后如果网络卡顿，导致没有进入战斗，则无法进入 run_general_battle 流程，
                # 所以如果判断是在战斗中，则执行通用战斗流程
                if not self.is_in_battle(False):
                    if not self.is_in_room() and self.is_room_dead():
                        break
                    if not self.appear_then_click(self.I_OROCHI_WILD_FIRE, interval=1, threshold=0.8):
                        continue

                self.screenshot()
                if not self.appear(self.I_OROCHI_WILD_FIRE, threshold=0.8):
                    self.run_general_battle(config=self.config.orochi.general_battle_config)
                    break

        # 当结束或者是失败退出循环的时候只有两个UI的可能，在房间或者是在组队界面
        # 如果在房间就退出
        if self.exit_room():
            pass
        # 如果在组队界面就退出
        if self.exit_team():
            pass

        self.ui_get_current_page()
        self.ui_goto(page_main)

        if not success:
            return False
        return True

    def is_room_dead(self) -> bool:
        # 如果在探索界面或者是出现在组队界面，那就是可能房间死了
        sleep(0.5)
        if self.appear(self.I_MATCHING) or self.appear(self.I_CHECK_EXPLORATION):
            sleep(0.5)
            if self.appear(self.I_MATCHING) or self.appear(self.I_CHECK_EXPLORATION):
                return True
        return False

    def _is_continue_battle_dialog(self) -> bool:
        """当前的双按钮卷轴弹窗是不是「是否邀请队友继续进行战斗？」

        ⚠️ 不能用 `self.ocr_appear(self.O_FAIL_INVITE)`：BaseCor.filter() 在整串不匹配时
        会退化成「逐字命中」（为了兼容竖排文本），"确认退出组队面板吗？" 只因为含一个
        "队"字就被判定命中（实测 10-23 / 10-26 两张报错截图全部误判成 True）。
        这里直接拿 OCR 原始文本做严格子串判断。
        """
        try:
            results = self.O_FAIL_INVITE.detect_and_ocr(self.device.image)
        except Exception as e:
            logger.warning(f'OCR 失败，跳过继续战斗判定: {e}')
            return False
        text = ''.join(r.ocr_text for r in results)
        if '邀请队友' in text:
            logger.info(f'Challenge failed dialog: {text}')
            return True
        # 队员视角的文案没有样本，只认「加入」+「继续」同时出现，
        # 避免把「…是否继续？」这种数量上限提示当成继续战斗
        if '加入' in text and '继续' in text:
            logger.info(f'Challenge failed dialog (member side): {text}')
            return True
        logger.warning(f'双按钮弹窗但不是邀请继续战斗: {text}')
        return False

    def _is_click_to_continue(self) -> bool:
        """当前界面是否有「点击屏幕继续」提示。

        这类界面（战前加成展示、结算提示）点一下就能推进，但 battle_wait 里没有任何
        模板能认它。不加 OCR 判断就无脑点的话，真战斗中会点到式神弹出技能详情。
        """
        try:
            results = O_CLICK_TO_CONTINUE.detect_and_ocr(self.device.image)
        except Exception as e:
            logger.warning(f'OCR 失败，跳过「点击屏幕继续」判定: {e}')
            return False
        text = ''.join(r.ocr_text for r in results).replace(' ', '')
        return '点击屏幕继续' in text

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        """
        重写战斗等待
        # https://github.com/runhey/OnmyojiAutoScript/issues/95
        :param random_click_swipt_enable:
        :return:
        """
        # 重写
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        self.C_REWARD_1.name = 'C_REWARD'
        self.C_REWARD_2.name = 'C_REWARD'
        self.C_REWARD_3.name = 'C_REWARD'
        # 战斗过程 随机点击和滑动 防封
        logger.info("Start battle process")
        # 挑战失败后游戏会弹「是否邀请队友继续进行战斗？」（卷轴 + 取消/确定）。
        # 原来这里只认 I_FALSE（结算界面的「失败」字样），但 2026-10 UI 改版后该模板
        # 已经失配（实测在失败弹窗截图上只有 0.0541，阈值 0.8），于是这场战斗**没有任何
        # 分支能命中** → while 1 里一直 random_click_swipt 空转，直到 BATTLE_STATUS_S
        # 卡死看门狗把游戏强杀重启（log/error/1793349460935：16:34:42 开战 + 3 分钟没有
        # 'Win battle'，然后 Game stuck）。两台实例各失败 3 次后整个 Orochi 任务退出。
        # 现在识别到弹窗就点「确定」：
        #   队长 = 继续邀请刚才的队友，队员 = 继续加入这场战斗。
        # 判据要求「取消」和「确定」同时命中 —— 只有这个双按钮卷轴弹窗才两者都在，
        # 单按钮提示（如体力不足）不会满足，避免误点消耗。
        fail_invite_try = 0
        # 连续「什么都没命中」的轮数。用于发现卡在未知界面（典型是「点击屏幕继续」）
        # 的情况：原来这里只靠 random_click_swipt，但它触发概率 4/501≈0.8%、
        # 还带 interval=20 的节流，60 秒里往往只点一次 —— 2026-10-30 18:46:58 就是
        # 只点了 1 次（18:45:58）没推进，然后被看门狗强杀。
        idle_round = 0
        while 1:
            self.screenshot()
            if self.appear(self.I_GI_SURE) and self.appear(self.I_GI_CANCEL):
                idle_round = 0
                # 再加一层 OCR 确认：只处理标题含「邀请队友」的弹窗。
                # 同样是「取消+确定」卷轴，还有别的文案（例如「式盘达到数量上限，
                # 是否继续？」「确认退出组队面板吗？」），在战斗里点错会白白消耗资源。
                fail_invite = self._is_continue_battle_dialog()
                if not fail_invite:
                    logger.warning('双按钮弹窗不是「邀请队友继续战斗」，不处理')
                if fail_invite:
                    fail_invite_try += 1
                    if fail_invite_try > 6:
                        # 点了 6 次（约 12 秒）弹窗还不消失，说明队友已经散了、继续邀请没有回应。
                        # 点取消退出本轮，把界面还给房间流程，别在这里死循环到看门狗强杀。
                        logger.warning('Continue-battle dialog keeps showing, click cancel and '
                                       'give up this round')
                        self.appear_then_click(self.I_GI_CANCEL, interval=0)
                        sleep(1.5)
                        return False
                    logger.info(f'Battle failed, click confirm to continue with teammates '
                                f'({fail_invite_try}/6)')
                    # 用 interval=0 + 显式 sleep 控制节奏：interval 的语义是「距上次点击是否满 N 秒」，
                    # 拿它当节流会让 12 秒的等待窗口被几次快速循环吃光（见 battle_wait 里贪吃鬼那段注释）
                    self.appear_then_click(self.I_GI_SURE, interval=0)
                    sleep(2)
                    continue
            # 弹窗消失（继续成功 / 本来就没失败）就把重试计数清零，
            # 这样下一场再失败时是新的 6 次配额
            fail_invite_try = 0
            action_click = random.choice([self.C_WIN_1, self.C_WIN_2, self.C_WIN_3])
            if self.appear_then_click(self.I_WIN, action=action_click ,interval=0.8):
                # 赢的那个鼓
                idle_round = 0
                continue
            if self.appear(self.I_GREED_GHOST):
                idle_round = 0
                # 贪吃鬼
                logger.info('Win battle')
                self.wait_until_appear(self.I_REWARD, wait_time=1.5)
                self.screenshot()
                if not self.appear(self.I_GREED_GHOST):
                    logger.warning('Greedy ghost disappear. Maybe it is a false battle')
                    continue
                # 识别到贪吃鬼后**先等 2 秒再开始点**。
                # 贪吃鬼吃到金币/经验时会播一段结算动画（截图中央「+1051 金币」飞入），
                # 动画期间输入被锁，这 1~2 秒里点空白完全是白点，还会白白消耗 miss 配额，
                # 连续几局撞上就把重试次数烧光，看起来像「卡在结算界面」。
                # 等动画播完再点，正常 2~3 次空白就能推进。
                logger.info('Greedy ghost detected, wait 2s for settlement animation')
                sleep(2)
                # 结算界面点空白就能推进，但**不能点到中间的掉落物**：
                # 点了会弹「获取途径」详情，界面就卡在这一层。
                # 原来 random.choice([C_REWARD_1, C_REWARD_2, C_REWARD_3]) 里
                # C_REWARD_2 有 30% 面积压在左侧物品卡上、C_REWARD_3 压着右侧，
                # 实测 10 次随机全落在物品区（log/error/1793021787203），while 1 永远退不出去。
                # 所以改用实测 edge≈0 的纯空白区 + 原 C_REWARD_1（底部也是空的）。
                # 权重 3:3:3:1 —— 三块纯空白优先，C_REWARD_1 里含「点击屏幕继续」文字，少用。
                #
                # ⚠️ 千万别用 self.click(btn, interval=x) 的返回值做流程控制！
                # base_task.click() 的返回值表示「interval 是否到了」，**不是「点击是否成功」**：
                # 间隔没到时它直接 return False 且根本不点击。写成 `if self.click(...): continue`
                # 就会掉进下面的重试分支，几毫秒一轮空转，把 miss 计数瞬间冲爆
                # （log/error/1793024857340：3 次真实点击之后 1.2 秒内 miss 从 3 冲到 7 直接放弃）。
                # 这里统一改成「无 interval 的 click + 显式 sleep」控制节奏。
                reward_safe = [self.C_REWARD_SAFE_L, self.C_REWARD_SAFE_R,
                               self.C_REWARD_SAFE_B, self.C_REWARD_1]
                reward_w = [3, 3, 3, 1]

                def _click_blank(wait: float = 1.3):
                    self.click(random.choices(reward_safe, weights=reward_w, k=1)[0])
                    # ⚠️ 是本模块顶部的 `from time import sleep`，不是 self.sleep ——
                    # ScriptTask 的 MRO 里**没有** sleep 方法（base_task 也只 import 了函数），
                    # 写成 self.sleep() 会直接 AttributeError 把整个任务进程打挂
                    # （log/error/1793025858372 + 1793025858640，22:44:17 两台实例同时崩）。
                    sleep(wait)

                miss = 0
                fix_try = 0
                while 1:
                    self.screenshot()
                    # 万一还是点到了物品，先把它关掉再继续
                    if self.appear(self.I_END_FIX_1) or self.appear(self.I_END_FIX_2):
                        fix_try += 1
                        if fix_try > 6:
                            logger.warning('物品详情弹窗关不掉，放弃本局结算')
                            return True
                        logger.info(f'物品详情弹窗出现，点空白关闭 ({fix_try}/6)')
                        _click_blank(1.2)
                        continue
                    if not self.appear(self.I_GREED_GHOST):
                        break
                    # 防封：保留 2% 概率「手滑」点到掉落物，弹详情后再点空白关掉。
                    # 真实玩家不可能一局都不会误触，长期 100% 绕开物品本身也是一种特征。
                    # 这里点完 continue，下一轮循环开头的 I_END_FIX_1/2 会识别详情弹窗并点空白关闭，
                    # 正好构成「点物品 -> 点空白」的完整拟人动作。本分支不计入 miss 配额。
                    if random.random() < 0.02:
                        logger.info('模拟误触掉落物(防封)，随后点空白关闭详情')
                        self.click(random.choice([
                            self.C_END_1_1, self.C_END_1_2, self.C_END_1_3,
                            self.C_END_1_4, self.C_END_1_5, self.C_END_1_6,
                        ]))
                        sleep(1.5)
                        continue
                    miss += 1
                    if miss > 20:
                        # 贪吃鬼吃到金币时会播一段动画（截图里「+1051 金币」），
                        # 动画期间输入被锁、点空白完全没用。20 次 × 1.3s ≈ 26 秒，
                        # 足够任何一段结算动画播完；到这里才算真卡住。
                        # 最后一搏：点左上角贪吃鬼图标本身（TrueOrochi 验证过的推进点），
                        # 再退出，至少别让界面留在原地被 stuck 检测打成 GameStuckError。
                        logger.warning('Greedy ghost 一直不消失(点空白也推不动)，'
                                       '点贪吃鬼图标做最后一搏')
                        for _ in range(3):
                            self.appear_then_click(self.I_GREED_GHOST, interval=1)
                            sleep(0.8)
                        return True
                    _click_blank(1.3)
                return True
            if self.appear(self.I_REWARD):
                # 魂
                idle_round = 0
                logger.info('Win battle')
                appear_greed_ghost = self.appear(self.I_GREED_GHOST)
                while 1:
                    self.screenshot()
                    action_click = random.choice([self.C_REWARD_1, self.C_REWARD_2, self.C_REWARD_3])
                    if self.appear_then_click(self.I_REWARD, action=action_click, interval=1.5):
                        continue
                    if not self.appear(self.I_REWARD):
                        break
                return True

            if self.appear(self.I_FALSE):
                idle_round = 0
                logger.warning('False battle')
                self.ui_click_until_disappear(self.I_FALSE)
                return False

            # ---------------- 未知界面兜底 ----------------
            # 连续 12 轮（每轮约 0.15~0.5s，合计 4~8 秒）一个分支都没命中，说明界面
            # 停在我们不认识的画面上。先 OCR 确认是不是「点击屏幕继续」，是就主动点一下。
            # 顺手把 stuck 记录补回来：self.click() 内部会走 handle_control_check →
            # stuck_record_clear()，把 BATTLE_STATUS_S 抹掉、并重置 60 秒计时器，
            # 于是下一次点击后 60 秒（而不是 long_wait_list 给的 300 秒）就会
            # GameStuckError 强杀游戏 —— 这正是 18:46:58 只等了 60 秒的原因。
            idle_round += 1
            if idle_round >= 12:
                idle_round = 0
                if self._is_click_to_continue():
                    logger.info('卡在「点击屏幕继续」提示(通常是战前加成展示)，主动点击推进')
                    self.click(C_CLICK_TO_CONTINUE)
                    sleep(1.2)
                    self.device.stuck_record_add('BATTLE_STATUS_S')
                    continue
            # 如果开启战斗过程随机滑动
            if random_click_swipt_enable:
                self.random_click_swipt()

    def orochi_switch_soul(self) -> None:
        # 判断是否开启根据选层切换御魂
        orochi_switch_soul = self.config.orochi.switch_soul
        if not orochi_switch_soul.auto_switch_soul:
            return

        group_team: str = None
        layer = self.config.orochi.orochi_config.layer
        match layer:
            case Layer.TEN:
                group_team = orochi_switch_soul.ten_switch
            case Layer.ELEVEN:
                group_team = orochi_switch_soul.eleven_switch
            case Layer.TWELVE:
                group_team = orochi_switch_soul.twelve_switch
            case Layer.THIRTEEN:
                group_team = orochi_switch_soul.thirteen_switch

        if orochi_switch_soul.auto_switch_soul:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(group_team)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()








