# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import json
import os
import random
from time import sleep
from datetime import time, datetime, timedelta
from pathlib import Path

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

# 需要「点一下屏幕才能继续」的两类界面，battle_wait 里没有任何模板能认它们：
#   1) 战前加成展示「额外加成：好友+10% 组队+20% 亲友+10% / 点击屏幕继续」
#      2026-10-30 18:46:58（log/error/1793357218730）第 51 局卡死在这。
#      这两个字实测在 x≈475~805 / y≈555~585。
#   2) 挑战失败的结算画面「提升式神/御魂 · 提升阴阳师/御灵 · 再次挑战 / 点击屏幕继续」
#      2026-10-31 21:57:06（log/error/1793455027143）：原来 ROI 只盖住第 1 类的
#      y≈555~585，这里「点击屏幕继续」在 y≈679~709 完全读不到（读到的其实是
#      y≈590 的阴阳师名字「无形同载」），于是 300 秒没人点 → GameStuckError 强杀。
#      **这个画面不点掉，后面那句「是否邀请队友继续进行战斗？」的确认框根本不会出现**，
#      所以用户看到的现象是「失败后从不点继续邀请队友的确认」。
# 现在统一成一个大 ROI (300,370,700,350)，一网打尽：第 2 类的「再次挑战」
# (y≈396~424)、第 1 类的「点击屏幕继续」(y≈555~585)、第 2 类的「点击屏幕继续」
# (y≈679~709)。两个关键词互为冗余 —— 实测其中一张截图把「点击屏幕继续」读成
# 「击屏幕继续」，靠「再次挑战」照样能命中。
# 误判验证：邀请弹窗、真战斗、贪吃鬼结算画面上两个关键词都不出现。
O_SETTLE_ADVANCE = RuleOcr(roi=(300, 370, 700, 350), area=(300, 370, 700, 350),
                            mode="Full", method="Default", keyword="",
                            name="settle_advance")
# 推进这个界面的落点：底部中央纯空白（沿用 reward_safe_b 实测 edge≈0.26% 的坐标），
# 避开中间那排式神头像（点头像会弹式神详情，反而更卡）
C_CLICK_TO_CONTINUE = RuleClick(roi_front=(720, 645, 200, 70),
                                roi_back=(720, 645, 200, 70),
                                name="click_to_continue")

# 庭院主界面底部那排功能按钮的文字（图鉴 / 珍旅居 / 纳物库 / 组队 / 阴阳寮 / 商店 /
# 花合战 / 好友 / 阴阳术 / 式神录）。这排按钮**不随昼夜、主题换肤变化**，比
# page_main 的 I_CHECK_MAIN 可靠得多：I_CHECK_MAIN 裁的是庭院天空的云纹，
# 2026-11-01 20:49 的夜间樱花庭院上只有 0.5268（阈值 0.8），根本认不出庭院。
#
# 用途：battle_wait 里如果发现画面已经回到庭院，说明这一局对本人早就结束了
# （典型是队长挑战失败后队伍被解散，游戏把队员直接抛回庭院），必须退出
# battle_wait 把控制权还给 run_member 主循环 —— 否则主循环里的
# check_then_accept() 永远得不到执行，队长重新邀请时队员就「永远不点接受」。
# 见 log/error/1793537377489（2026-11-01 20:47:21 第 108 局开战后，20:48:49
# 画面已经是庭院，一直空转到 20:49:37 被 GameStuckError 强杀）。
#
# ROI 必须**只盖住底部按钮栏**（y 545~720）。实测用大 ROI (300,370,700,350) 时，
# 战前加成界面的「额外加成：好友+10% 组队+20% 亲友+10%」会把「组队」「好友」两个
# 词送进来，于是战斗还没开始就被误判成「已经回到庭院」直接退局
# （log/error/1793357218730 就是这么误判的）。这个 175 高的扁 ROI 在加成界面上
# 只能读到「点击屏幕继续」和倒计时，一个按钮词都不出现。
O_PAGE_MAIN = RuleOcr(roi=(300, 545, 700, 175), area=(300, 545, 700, 175),
                      mode="Full", method="Default", keyword="",
                      name="page_main_buttons")
# 新版底部按钮文字。都是四个字的玩法名，判别力足够，要求命中 ≥2 个才判庭院。
# 故意不收「御魂」：御魂副本界面的标题就是这两个字，收进来等于给误判开门 ——
# 那个界面里「御魂」单独出现，「结界突破」「地域鬼王」这些不会跟着来。
O_PAGE_MAIN_KEYWORDS = ('觉醒材料', '结界突破', '式神委派', '秘闻副本', '地域鬼王',
                        '妖气探索', '百鬼夜行', '六道之门', '契灵之境', '御灵')

# 庭院指纹阈值。2026-11-11 换 UI 后改用**底部按钮栏**做模板（I_CHECK_MAIN 已改成
# 底部「觉醒材料 + 御魂」两枚按钮，见 tasks/GameUi/assets.py 的说明）：
#   真庭院 0.955 / 0.959（两台各测一次），御魂副本界面 0.327。
# 0.8 落在中间，比旧的「探索竖排标签」可靠得多 —— 那个标签在新 UI 里只剩 0.46，
# 而且它的点击落点（493,116 附近）现在什么都没有，点一次空一次。
PAGE_MAIN_EXPLORATION_THRESHOLD = 0.80


class ScriptTask(GeneralBattle, GeneralInvite, GeneralBuff, GeneralRoom, GameUi, SwitchSoul, OrochiAssets, TrueOrochiAssets):

    # ---------------- 本轮场次持久化 ----------------
    # 为什么要做：GameStuckError / 游戏崩溃会让 OAS 重启游戏并重开任务，
    # run() 里 current_count 一律归零，于是已经刷掉的几十场白干。
    # 2026-11-08 22:04 oas2 在 37/120 被 60 秒看门狗误杀，重启后从 1 开始，
    # 而 oas1 是 44 —— 两台彻底错位，还得再刷一小时。
    # 现在每场结束把 (场次, 目标, 时间) 写到 log/ 下按实例区分的小文件，
    # 下次任务启动时若仍在同一轮窗口内就接着数。
    # 内存影响：只有一个 str 路径 + 两个 int 标量，文件同一路径覆盖写，
    # 不累积、不随运行时长增长。
    ROUND_STATE_TTL_HOURS = 4

    def _round_state_path(self) -> Path:
        try:
            name = getattr(self.config, 'config_name', 'default')
        except Exception:
            name = 'default'
        return Path.cwd() / 'log' / f'.orochi_round_{name}.json'

    def _restore_round_count(self, limit_count: int) -> None:
        """任务启动时尝试续接上一轮场次。

        「同一轮」的判定：目标场次一致、上一轮没打满、距上次记录不超过
        ROUND_STATE_TTL_HOURS 小时，**并且是同一次脚本进程**（pid 相同）。

        最后那条最容易被忽略：用户在界面上点了停止再启动，OAS 是
        ScriptProcess.stop() -> terminate() 把子进程杀掉，再 start() 起一个
        全新进程，地址空间全清空，等于「重新开始」。这时候如果还去读上一轮
        的记录，两台实例就会各自接着自己的旧进度跑（实测 2026-11-09 01:18
        oas1 续接 49、oas2 续接 12，一个 51 一个 14，从头就错开）。
        续接只应该服务于「同一进程内任务失败重跑」——script.py 的 loop 里
        handle_error 会让任务在**同一个子进程**里 continue 重来，pid 不变。
        所以用 pid 区分：进程没换就续接（崩溃/游戏重启），进程换了就是从 1 开始。
        """
        path = self._round_state_path()
        try:
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding='utf-8'))
            count = int(data.get('count', 0))
            limit = int(data.get('limit', 0))
            saved_at = datetime.fromisoformat(str(data.get('saved_at')))
        except Exception as e:
            logger.warning(f'上一轮场次记录读不出来({e})，本次从 0 开始')
            return
        prev_pid = data.get('pid')
        if prev_pid is None or int(prev_pid) != os.getpid():
            logger.info(f'新的一次启动（上次 pid={prev_pid} / 本次 {os.getpid()}），'
                        f'上一轮 {count}/{limit} 不再续接，从 1 开始重新计')
            return
        if limit != limit_count:
            logger.info(f'场次目标变了（上次 {limit} / 本次 {limit_count}），不续接，从 0 开始')
            return
        if count <= 0 or count >= limit_count:
            return
        if datetime.now() - saved_at > timedelta(hours=self.ROUND_STATE_TTL_HOURS):
            logger.info(f'上一轮场次记录已过期（{saved_at:%m-%d %H:%M}），从 0 开始')
            return
        self.current_count = count
        self._saved_count = count
        logger.warning(f'续接上一轮场次：{count}/{limit_count}'
                       f'（上次记录 {saved_at:%H:%M:%S}，本轮接着刷，不重新计数）')

    def _save_round_count(self) -> None:
        """每场结束时落盘一次。场次没变就不写，避免每轮循环都碰磁盘。"""
        if self.current_count == getattr(self, '_saved_count', -1):
            return
        path = self._round_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {'count': self.current_count,
                    'limit': self.limit_count,
                    # pid 用来区分「同一进程内任务重跑」和「用户手动停止后重开」
                    'pid': os.getpid(),
                    'saved_at': datetime.now().isoformat(timespec='seconds')}
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            self._saved_count = self.current_count
        except Exception as e:
            # 落盘失败不能影响刷本，最多是这次卡死后进度回退
            logger.debug(f'场次记录写入失败: {e}')

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
        # 卡死强杀 / 游戏崩溃重启后接着上一轮的数继续刷（打满了才会归零）
        self._restore_round_count(limit_count)

        config: Orochi = self.config.orochi
        if not self.is_in_battle(True):
            self.ui_get_current_page()
            self.ui_goto(page_main)
            if config.orochi_config.soul_buff_enable:
                self.open_buff()
                # 开启御魂加成后再确认一次真的开了：没开就重点，直到确认开启或重试用完
                if not self.soul_on():
                    logger.warning('Soul buff still not ON after retries, continue task anyway')
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











    def _leader_rebuild_room(self) -> bool:
        """队长在房间丢失后重建房间，接着刷（不重置 current_count）。

        从 run_leader 的初始化段抽出来的复用版本：回御魂界面 → 选层 → 锁队 →
        建队 → 建房 → 设为私密 → 确认创建。调用方随后把 is_first 置 True 重新邀请。
        :return: True 表示新房间已建好
        """
        self.ui_get_current_page()
        self.ui_goto(page_soul_zones)
        self.orochi_enter()
        layer = self.config.orochi.orochi_config.layer
        self.check_layer(layer)
        self.config.orochi.general_battle_config.lock_team_enable = True
        self.check_lock(self.config.orochi.general_battle_config.lock_team_enable)
        logger.info('Rebuild team')
        deadline = datetime.now() + timedelta(seconds=40)
        while 1:
            self.screenshot()
            if self.appear(self.I_CHECK_TEAM):
                break
            if self.appear_then_click(self.I_FORM_TEAM, interval=1):
                continue
            if datetime.now() > deadline:
                logger.warning('Rebuild team: 组队面板 40s 未出现，放弃本次重建')
                return False
        self.create_room()
        self.ensure_private()
        self.create_ensure()
        return True

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
        # 队长一轮要连续刷满 limit_count 场（默认 120 场，实际要 1 小时以上）。
        # 期间只要某一局结束后游戏回到庭院（队员掉线/挑战失败/房间被解散），
        # 原逻辑只把「探索界面、组队界面」认定为房间失效，在庭院会一直 empty
        # continue 空转，直到 stuck record 300 秒超时被 GameStuckError 强杀游戏。
        # 实测 2026-11-07 全天 oas2 166 轮里有 144 轮是这么中途结束的，同时组队的
        # 队员（oas1）只能跟着散伙，每轮都刷不满 120 场。
        # 现在改为：庭院 / 探索 / 组队界面都算房间丢失，就地重建房间、重新邀请、
        # 接着原来的计数继续刷；连续重建 max_rebuild 次仍失败才放弃本轮。
        rebuild_count = 0
        max_rebuild = 4
        # 这个时候我已经进入房间了哦
        while 1:
            self.screenshot()
            self._save_round_count()
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
                # 房间丢失判定：庭院（模板快判 + OCR 兜底）、探索界面、组队界面
                room_lost = (self._is_page_main_by_bottombar()
                             or self.is_room_dead()
                             or self._is_page_main())
                if room_lost:
                    if rebuild_count >= max_rebuild:
                        logger.warning(f'Orochi room lost {rebuild_count} times in a row, '
                                       f'give up this round at {self.current_count}/{self.limit_count}')
                        success = False
                        break
                    rebuild_count += 1
                    logger.warning(f'Orochi room lost at {self.current_count}/{self.limit_count}, '
                                   f'rebuild room and re-invite ({rebuild_count}/{max_rebuild})')
                    self.device.stuck_record_clear()
                    if not self._leader_rebuild_room():
                        logger.warning('Rebuild room failed, retry in next loop')
                        continue
                    # 新房间要重新邀请第一个队员
                    is_first = True
                    continue
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
        # 队长中途回庭院重建房间时（见 run_leader 里的 rebuild 逻辑），队员会先遇到
        # 「房间被销毁」或「队长跑路」。原逻辑一遇到就 break 结束整轮，于是两边
        # 一散伙就都刷不满 120 场。现在允许连续失败几次，回庭院接着等下一封邀请。
        wait_fail = 0
        max_wait_fail = 6
        # 结算层连续点击次数（_clear_settle_layer 用），清零时机 = 画面上的结算层消失
        self._settle_try = 0
        while 1:
            self.screenshot()
            self._save_round_count()

            # 检查猫咪奖励
            if self.appear_then_click(self.I_PET_PRESENT, action=self.C_WIN_3, interval=1):
                continue

            if self.current_count >= self.limit_count:
                logger.info('Orochi count limit out')
                break
            if datetime.now() - self.start_time >= self.limit_time:
                logger.info('Orochi time limit out')
                break

            # 结算层清理（模板 8ms）：胜利/失败的结算与掉落展示是压在庭院上的
            # 半透明层，不点掉就永远停在那里；而 _is_page_main() 在这种画面上会
            # 读到底层按钮栏误判成庭院，下面所有分支就只会「等邀请」、不再点击，
            # 空转满 5 分钟整轮退出（2026-11-08 16:25 oas1 卡死即此）。
            if self._clear_settle_layer():
                idle_start = datetime.now()
                continue

            if self.check_then_accept():
                continue

            if self.is_in_room():
                idle_start = datetime.now()
                self.device.stuck_record_clear()
                if self.wait_battle(wait_time=self.config.orochi.invite_config.wait_time):
                    wait_fail = 0
                    # wait_battle() 只判断「还在不在房间里」，停在结算层时它同样返回
                    # True，随后 run_general_battle 就把上一场的结算残留当成新一局
                    # 再 +1。所以要正面确认：看到真战斗或准备界面才计入。
                    if not self._battle_confirmed(timeout=8):
                        logger.warning('Member: wait_battle said battle started but neither battle '
                                       f'nor prepare UI in 8s (page_main={self._is_page_main()}), '
                                       'skip counting this round')
                        idle_start = datetime.now()
                        continue
                    self.run_general_battle(config=self.config.orochi.general_battle_config)
                else:
                    # wait_battle 内部已经 exit_room 回到庭院。队长可能只是丢了房间
                    # 正在重建，所以先别结束整轮，回庭院继续等邀请。
                    wait_fail += 1
                    if wait_fail >= max_wait_fail:
                        logger.warning(f'Member: wait battle failed {wait_fail} times in a row, '
                                       f'exit this orochi task at {self.current_count}/{self.limit_count}')
                        break
                    logger.warning(f'Member: wait battle failed ({wait_fail}/{max_wait_fail}), '
                                   f'keep waiting for invite (count={self.current_count}/{self.limit_count})')
                    idle_start = datetime.now()
                    continue
            # 队长秒开的时候，检测是否进入到战斗中。
            # is_in_battle() 把 I_WIN / I_REWARD（结算层）也算「在战斗中」，队长散伙后
            # 结算残留会让 check_take_over_battle 返回 True 并凭空 +1（实测这种假战斗
            # 每场只持续 5.4~6.1 秒，2026-11-08 共 41 次），所以这里改成必须先看到
            # 真战斗（I_BATTLE_INFO）或准备界面（I_PREPARE_* / I_BUFF）才算真的开打。
            elif not self._is_page_main() and self._battle_confirmed(timeout=6):
                if self.is_in_real_battle(False):
                    # 已经在真战斗里（队长秒开），接管并把这一局计入
                    self.check_take_over_battle(False, config=self.config.orochi.general_battle_config)
                else:
                    # 停在准备界面：和 wait_battle 返回 True 后是同一条路，正常开打
                    self.run_general_battle(config=self.config.orochi.general_battle_config)
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
            self._save_round_count()

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
            self._save_round_count()
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

    def _settle_advance_keyword(self) -> str:
        """当前界面是否是「点一下屏幕才能推进」的界面，是则返回命中的关键词。

        覆盖两类：战前加成展示、挑战失败的结算画面。这类界面点一下就能推进，
        但 battle_wait 里没有任何模板能认它。不加 OCR 判断就无脑点的话，
        真战斗中会点到式神弹出技能详情。
        """
        try:
            # logDisplay=False：这个判定每 5 秒就执行一次（battle_wait 的未知界面兜底），
            # 开着会把每次 OCR 的原文都写一行日志 —— 2026-11-08 实测占全天日志 45%。
            # 命中后的关键结果由调用方打印（「卡在 xxx 界面，主动点击推进」），信息不丢。
            results = O_SETTLE_ADVANCE.detect_and_ocr(self.device.image, logDisplay=False)
        except Exception as e:
            logger.warning(f'OCR 失败，跳过结算界面判定: {e}')
            return ''
        text = ''.join(r.ocr_text for r in results).replace(' ', '')
        for kw in ('点击屏幕继续', '再次挑战'):
            if kw in text:
                return kw
        return ''

    def _is_page_main_by_bottombar(self) -> bool:
        """用主界面底部那排玩法按钮做模板匹配，约 8ms，不跑 OCR。

        2026-11-11 游戏换成水墨风主界面，原来那枚金底竖排「探索」标签
        （I_MAIN_GOTO_EXPLORATION）整个没有了，实测掉到 0.46，连带点击落点
        （493,116）也点空 —— 这就是两台实例在「Page switch: page_main ->
        page_exploration」上死循环的原因。
        现在改用底部按钮栏（觉醒材料 + 御魂两枚按钮）：真庭院 0.955 / 0.959，
        御魂副本界面 0.327，战斗/结算/房间界面根本没有这一排，判别力比以前更强。

        ⚠️ 仍不能当唯一依据：庭院上弹的模态弹窗会把它盖住。所以只做快路径，
        漏判交给 _is_page_main() 的底部按钮栏 OCR 兜底。
        """
        return self.appear(self.I_CHECK_MAIN,
                           threshold=PAGE_MAIN_EXPLORATION_THRESHOLD)

    def _is_settle_layer(self) -> bool:
        """画面中央是否压着一层奖励结算（I_REWARD = 结算框里的奖励图标）。

        胜利/失败的结算、掉落展示都是**半透明层**，压在庭院之上：底部的
        「组队 / 好友」还能透出来被 OCR 读到，于是 _is_page_main() 会把它误判成
        庭院（2026-11-08 16:25:13 实测日志 `[PAGE_MAIN] 庭院底部按钮命中 ['组队', '好友']`，
        而当时真实画面是「掉落展示 + 底部 点击屏幕继续」）。

        判别力实测（settle_layer_probe.py）：
        - 133 张 log/error 报错截图里，该模板只在 33 张结算界面上命中，分数 0.985~0.987；
        - 房间画面 0.365、战斗/加成画面 0.409、庭院 0.3x —— 0.8 的阈值非常干净。
        模板匹配约 8ms，比 OCR 快 20 倍，适合每个主循环都查一次。
        """
        return self.appear(self.I_REWARD)

    def _clear_settle_layer(self) -> bool:
        """结算层压着画面就点掉它，返回本轮是否点过（点过就 continue 重新判断画面）。

        为什么必须有这一步：结算层没人点就永远停在那里。battle_wait 的未知界面兜底
        虽然会 OCR「点击屏幕继续」，但它要求 idle_round >= 6（约 2.5 秒一次），而且
        结算动画刚出现的那一两秒读不到文字；此时 _is_page_main() 已经靠下层按钮判成
        庭院并放弃本场，控制权回到 run_member 走「庭院里等邀请」分支 —— 那个分支
        只等邀请、不含任何点击，于是结算层再没人处理，空转满 5 分钟整轮退出。
        这就是 2026-11-08 16:25 用户看到的「oas1 卡在结算界面」。

        最多连点 20 次（约 25 秒）：真点不掉说明不是普通结算层，交回上层按空闲超时处理。
        """
        if not self._is_settle_layer():
            self._settle_try = 0
            return False
        # 真战斗里 I_REWARD 也可能一闪而过，那种时候别去点（落点在底部技能栏附近）
        if self.is_in_real_battle(False):
            return False
        # getattr 兜底：万一以后从别的入口调用而没走 run_member 的初始化，
        # 不要变成 AttributeError 把整轮任务打断（2026-11-08 的 soul_on 就是这么炸的）
        try_count = getattr(self, '_settle_try', 0)
        if try_count >= 20:
            return False
        self._settle_try = try_count + 1
        logger.info(f'结算层压在画面上，点击推进 ({self._settle_try}/20)')
        self.click(C_CLICK_TO_CONTINUE)
        sleep(1.2)
        # self.click() 内部会走 stuck_record_clear()，把 300 秒的长等待降级成 60 秒，
        # 这里补回来（与 battle_wait 未知界面兜底里的处理一致）
        self.device.stuck_record_add('BATTLE_STATUS_S')
        return True

    def _is_page_main(self) -> bool:
        """当前画面是不是庭院主界面。

        先走 8ms 的「探索」标签模板匹配；不命中再退回底部按钮栏 OCR（约 0.18s）。
        两级是有必要的：探索标签会被弹窗盖住，而底部按钮栏在弹窗下方基本不会被遮，
        两者互补。

        战斗界面底部是技能栏、房间界面底部是「开始战斗」，都不会出现
        「纳物库 / 阴阳寮 / 花合战」这类按钮词；要求**至少命中 2 个**不同的按钮，
        单个词命中不足以下结论。
        """
        # 结算/掉落层压在庭院上是半透明的，底部按钮栏能透出来被 OCR 读到，
        # 会把这个画面误判成庭院。有 I_REWARD（结算框）就说明上方还有一层没点掉，
        # 不算「干净的庭院」——让调用方走 _clear_settle_layer() 去点它。
        if self._is_settle_layer():
            return False
        if self._is_page_main_by_bottombar():
            return True
        try:
            # 同上：每 5 秒一次的兜底判定，关掉逐次 OCR 原文（命中时下面会打 [PAGE_MAIN]）
            results = O_PAGE_MAIN.detect_and_ocr(self.device.image, logDisplay=False)
        except Exception as e:
            logger.warning(f'OCR 失败，跳过庭院判定: {e}')
            return False
        text = ''.join(r.ocr_text for r in results).replace(' ', '')
        hits = [kw for kw in O_PAGE_MAIN_KEYWORDS if kw in text]
        if len(hits) >= 2:
            # 在庭院干等邀请时这里每 0.6 秒被调一次，原来每次都打一行
            # （2026-11-08 15:56:31~15:56:40 十秒里 19 行），只在「刚进入庭院」时打一次
            if not getattr(self, '_page_main_logged', False):
                logger.info(f'[PAGE_MAIN] 庭院底部按钮命中 {hits}')
                self._page_main_logged = True
            return True
        self._page_main_logged = False
        return False

    def _battle_confirmed(self, timeout: float = 8.0) -> bool:
        """等最多 timeout 秒，正面确认「真的开打了」：出现真战斗 UI 或准备界面。

        为什么不能用 is_in_battle()：它把 I_WIN / I_REWARD / I_FRIENDS 也算「在战斗中」。
        队长散伙后游戏把队员丢在结算层上（半透明的胜利/加成结算压在庭院之上），
        这时 is_in_battle() 为真、_is_page_main() 又可能因为 OCR 读到下层按钮而误判，
        于是结算残留被当成新一局，current_count 凭空 +1。

        2026-11-08 全天实测证据：
        - 这种假战斗在 oas1（队员）身上出现 41 次，每次从「开战」到「胜利」只有
          5.4~6.1 秒（02:18:31 / 06:19:24 / 07:41:20 / 09:25:19 / 14:28:11 /
          15:15:29 / 15:56:42 …），每一场都对应监控里 d=oas1-oas2 的 +1。
        - 同期 oas2（队长）1173 场、最短 25 秒，一次假战斗都没有；oas1 的真战斗
          最短 9.8 秒（1407 场）。所以「5 秒就赢」只可能是结算残留。
        - 这些假战斗里 battle_before() 整整跑了 5 秒超时（06:19:24~06:19:29），
          说明那段时间里 is_in_real_battle() 和 is_in_prepare() **都是假**
          （否则它早就 return 或去点准备了），拿这两个做正面判据是安全的。

        真战斗用 I_BATTLE_INFO（战斗界面左上角状态条），准备界面用
        I_BUFF / I_PREPARE_HIGHLIGHT / I_PREPARE_DARK，结算层三者都不具备。
        """
        deadline = datetime.now() + timedelta(seconds=timeout)
        while 1:
            if self.is_in_real_battle() or self.is_in_prepare(False):
                return True
            if datetime.now() >= deadline:
                return False
            sleep(0.3)

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
        # 每局都打一次、信息量为零（下一行的 GENERAL BATTLE START 已经标出开战），降为 debug
        logger.debug("Start battle process")
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
        # 「点一下屏幕才能推进」的界面（战前加成 / 失败结算）已经被点了多少次。
        # 加个上限是为了别在真点不掉的画面上一直点到看门狗强杀游戏。
        advance_try = 0
        # 单场战斗的时长看门狗（自救用，不是判死用）。
        # 正常一场 25~30 秒（2026-11-08 21:59~22:03 连续 9 场实测都是 26~27 秒）。
        # soft：超过就点一下屏幕，帮可能僵住的动画推进；最多 3 次。
        # hard：超过就主动把控制权交回外层轮询（战斗界面本来就会自己打完/打完结算），
        #       硬上限必须 < 300 秒（BATTLE_STATUS_S 的长等待豁免），否则还是会被
        #       GameStuckError 强杀游戏 —— 强杀的代价是整个任务重启、本轮 120 场计数归零。
        battle_start = datetime.now()
        battle_soft_limit = 120
        battle_hard_limit = 180
        battle_advance_try = 0
        while 1:
            self.screenshot()
            # ⚠️ 每轮补一次 BATTLE_STATUS_S，别删！
            # swipe / click 都会走 device.handle_control_check() -> stuck_record_clear()，
            # 把这条例外记录连同 60/300 秒计时器一起清掉。清掉之后「战斗中长等待」的
            # 300 秒豁免就失效了，只要 60 秒内没有任何点击（random_click_swipt 命中率
            # 只有 4/501≈0.8%，还带 interval=20 节流，60 秒里常常一次都不点），
            # stuck_record_check() 就会抛 GameStuckError 把游戏强杀重启。
            # 2026-11-08 22:03:56 的第 37 场就是这么死的：random_click_swipt 的 swipe
            # 清掉了记录，那场偏偏慢到 66 秒（oas1 22:04:59 才 GB_WIN），oas2 在
            # 22:04:56 整 60 秒抛 Wait too long / Waiting for set()（空集合），
            # 队长重启游戏 -> 队员 22:05:16 Leader run away -> 两边 37/120 全部归零。
            # 每轮补一次是幂等的（set.add），唯一代价是一个 dict 查找。
            if 'BATTLE_STATUS_S' not in self.device.detect_record:
                self.device.stuck_record_add('BATTLE_STATUS_S')
            battle_elapsed = (datetime.now() - battle_start).total_seconds()
            if battle_elapsed > battle_soft_limit:
                if battle_advance_try >= 3 or battle_elapsed > battle_hard_limit:
                    logger.warning(f'本局已打 {int(battle_elapsed)} 秒仍未结束，放弃本局并交回外层轮询'
                                   f'（保留计数 {self.current_count}，不重启游戏）')
                    return False
                battle_advance_try += 1
                logger.warning(f'本局已打 {int(battle_elapsed)} 秒仍未结束，点一下屏幕尝试推进'
                               f'（{battle_advance_try}/3）')
                self.click(C_CLICK_TO_CONTINUE)
                sleep(2)
                continue
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
            # 连续几轮一个分支都没命中，说明界面停在我们不认识的画面上。先 OCR 确认
            # 是不是「点击屏幕继续 / 再次挑战」这种点一下就推进的界面，是就主动点。
            # 顺手把 stuck 记录补回来：self.click() 内部会走 handle_control_check →
            # stuck_record_clear()，把 BATTLE_STATUS_S 抹掉、并重置 60 秒计时器，
            # 于是下一次点击后 60 秒（而不是 long_wait_list 给的 300 秒）就会
            # GameStuckError 强杀游戏 —— 这正是 18:46:58 只等了 60 秒的原因。
            idle_round += 1
            # 6 轮（约 2.5 秒）就查一次，比原来的 12 轮更及时：失败结算画面停留太久时，
            # 游戏可能自己跳走或者队友先退了，越早点掉越不容易错过「继续邀请」窗口
            if idle_round >= 6:
                idle_round = 0
                # 先花 8ms 用「探索」标签确认是不是已经回庭院了（纯模板匹配，不跑 OCR）。
                # 庭院是最常见的卡死现场，命中就直接交还控制权，省掉下面两次 OCR
                # （_settle_advance_keyword + _is_page_main 合计 0.36s/轮）。
                if self._is_page_main_by_bottombar():
                    logger.warning('Battle is over, game already back to main page '
                                   '(team dissolved by leader?), give up this round '
                                   'and let the member loop handle invitations')
                    return False
                keyword = self._settle_advance_keyword()
                if keyword:
                    advance_try += 1
                    if advance_try > 10:
                        # 点了 10 次（约 25 秒）还没推进，说明这画面点不掉了，
                        # 主动交出控制权，让调度器重开任务，别等看门狗强杀游戏
                        logger.warning(f'卡在「{keyword}」界面点不掉，放弃本局')
                        return False
                    logger.info(f'卡在「{keyword}」界面，主动点击推进 ({advance_try}/10)')
                    self.click(C_CLICK_TO_CONTINUE)
                    sleep(1.5)
                    # self.click() 内部会 stuck_record_clear()，把 300 秒的长等待
                    # 降级成 60 秒，这里补回来
                    self.device.stuck_record_add('BATTLE_STATUS_S')
                    continue
                # 画面已经在庭院主界面了，说明这一局对本人早就结束（典型：队长
                # 挑战失败后队伍被解散，游戏直接把队员抛回庭院）。这里必须退出，
                # 把控制权还给 run_member 主循环 —— 主循环里才有 check_then_accept()，
                # 卡在这里的后果就是「队长重新邀请，队员永远不点接受」，
                # 然后 300 秒被 GameStuckError 强杀（log/error/1793537377489）。
                if self._is_page_main():
                    logger.warning('Battle is over, game already back to main page '
                                   '(team dissolved by leader?), give up this round '
                                   'and let the member loop handle invitations')
                    return False
                # 战斗失败点掉结算画面后，有时不回弹窗而是直接退回房间，
                # 这时 battle_wait 再不退出就会原地空转到看门狗（三张失败/弹窗截图上
                # 这三个房间模板的匹配分都是 0.02~0.11，不会误判成房间）
                if self.is_in_room(False):
                    logger.warning('Battle ended, back to room without retry dialog, '
                                   'give up this round')
                    return False
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








