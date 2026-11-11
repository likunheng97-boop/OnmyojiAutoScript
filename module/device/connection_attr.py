# This Python file uses the following encoding: utf-8
# copy from alas
import contextlib
import json
import os
import re
import subprocess

import adbutils
import uiautomator2 as u2
from adbutils import AdbClient, AdbDevice

from module.base.decorator import cached_property
from module.config.config import Config
from module.config.utils import deep_iter
from module.exception import RequestHumanTakeover
from module.logger import logger

class ConnectionAttr:
    config: Config
    serial: str

    adb_binary_list = [
        './bin/adb/adb.exe',
        './toolkit/Lib/site-packages/adbutils/binaries/adb.exe',
        '/usr/bin/adb'
    ]

    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig, str): Name of the user config under ./config
        """
        logger.hr('Device', level=1)
        if isinstance(config, str):
            self.config = Config(config, task=None)
        else:
            self.config = config

        # Init adb client
        logger.attr('AdbBinary', self.adb_binary)
        # Monkey patch to custom adb
        adbutils.adb_path = lambda: self.adb_binary
        # Remove global proxies, or uiautomator2 will go through it
        count = 0
        d = dict(**os.environ)
        #----------------------------------------------------------------------------------下面的是我注释掉的
        # d.update(self.config.args)
        for _, v in deep_iter(d, depth=3):
            if not isinstance(v, dict):
                continue
            if 'oc' in v['type'] and v['value']:
                count += 1
        if count >= 3:
            for k, _ in deep_iter(d, depth=1):
                if 'proxy' in k[0].split('_')[-1].lower():
                    del os.environ[k[0]]
        else:
            su = super(self.config.__class__, self.config)
            for k, v in deep_iter(su.__dict__, depth=1):
                if not isinstance(v, str):
                    continue
                if 'eri' in k[0].split('_')[-1]:
                    print(k, v)
                    su.__setattr__(k[0], chr(8) + v)
        # Cache adb_client
        _ = self.adb_client

        # Parse custom serial
        # self.serial = str(self.config.Emulator_Serial)
        self.serial = str(self.config.script.device.serial)
        self.serial_check()
        # MuMu 重启后 adb 端口会漂移，这里按实例号重新解析一次（见方法注释）
        self.resolve_serial_dynamic()
        self.config.DEVICE_OVER_HTTP = self.is_over_http

    def serial_check(self):
        """
        serial check
        """
        # Chinese colon
        if '：' in self.serial:
            self.serial = self.serial.replace('：', ':')
            logger.warning(f'Serial {self.config.Emulator_Serial} is revised to {self.serial}')
            self.config.Emulator_Serial = self.serial
        if self.is_bluestacks4_hyperv:
            self.serial = self.find_bluestacks4_hyperv(self.serial)
        if self.is_bluestacks5_hyperv:
            self.serial = self.find_bluestacks5_hyperv(self.serial)
        if "127.0.0.1:58526" in self.serial:
            logger.warning('Serial 127.0.0.1:58526 seems to be WSA, '
                           'please use "wsa-0" or others instead')
            raise RequestHumanTakeover
        if self.is_wsa:
            self.serial = '127.0.0.1:58526'
            if self.config.script.device.screenshot_method != 'uiautomator2' \
                    or self.config.script.device.control_method != 'uiautomator2':
                with self.config.multi_set():
                    self.config.script.device.screenshot_method = 'uiautomator2'
                    self.config.script.device.control_method = 'uiautomator2'
        if self.is_over_http:
            if self.config.script.device.screenshot_method not in ["ADB", "uiautomator2", "aScreenCap"] \
                    or self.config.script.device.control_method not in ["ADB", "uiautomator2", "minitouch"]:
                logger.warning(
                    f'When connecting to a device over http: {self.serial} '
                    f'ScreenshotMethod can only use ["ADB", "uiautomator2", "aScreenCap"], '
                    f'ControlMethod can only use ["ADB", "uiautomator2", "minitouch"]'
                )
                raise RequestHumanTakeover

    # ------------------------------------------------------------------
    # MuMu 动态 adb 端口
    # ------------------------------------------------------------------
    @cached_property
    def is_mumu_12(self) -> bool:
        return str(getattr(self.config.script.device, 'emulatorinfo_type', '') or '') == 'MuMuPlayer12'

    def resolve_serial_dynamic(self):
        """
        MuMu 每次重启后 adb 端口会漂移：同一实例会在 16384 <-> 16385、
        16416 <-> 16417 之间来回跳（实测 2026-11-07 与 2026-11-11 各跳一次）。
        配置里写死 serial 的结果就是「重启后 OAS 连不上设备、oasx 卡在 UIAUTOMATOR2 INIT」。

        这里以 MuMuManager 报的 adb_port 为准，每次脚本启动重新解析一遍：
            emulatorinfo_name = "MuMuPlayer-15.0-1"  ->  实例号 1
            MuMuManager info -v 1                    ->  adb_host_ip / adb_port
        解析出的 ip:port 会写回配置（ConfigModel 赋值自动保存），下次界面显示的就是对的。
        任何一步失败都保持原 serial，不阻断原有流程。
        """
        if not self.is_mumu_12:
            return
        device = self.config.script.device
        name = str(getattr(device, 'emulatorinfo_name', '') or '')
        m = re.search(r'-(\d+)\s*$', name)
        if not m:
            logger.warning(f'无法从 emulatorinfo_name 解析实例号：{name!r}，跳过 serial 自动解析')
            return
        index = int(m.group(1))

        mgr = self.find_mumu_manager(str(getattr(device, 'emulatorinfo_path', '') or ''))
        if not mgr:
            logger.warning('找不到 MuMuManager.exe，跳过 serial 自动解析')
            return

        info = self.read_mumu_info(mgr, index)
        if not info:
            return
        ip = str(info.get('adb_host_ip') or '127.0.0.1')
        try:
            port = int(info.get('adb_port'))
        except (TypeError, ValueError):
            logger.warning(f'MuMu 实例 {index} 的 adb_port 无效：{info.get("adb_port")!r}，跳过自动解析')
            return
        if port <= 0:
            logger.warning(f'MuMu 实例 {index} 的 adb_port = {port}，可能未启动，跳过自动解析')
            return

        new = f'{ip}:{port}'
        logger.attr('MuMuIndex', index)
        logger.attr('MuMuAdbPort', new)
        if new == self.serial:
            logger.info(f'Serial 无需变更：{new}')
        else:
            logger.warning(f'Serial 自动修正：{self.serial} -> {new}（MuMu 实例 {index} 当前 adb 端口）')
            self.serial = new
            with contextlib.suppress(Exception):
                # 写回配置，ConfigModel.__setattr__ 会自动 save
                device.serial = new

        # adb 端口换了的话设备表里没有这条连接，先 adb connect 一次；
        # 失败不抛，交给后续 u2 初始化报错（那里有更完整的提示）
        try:
            result = self.adb_client.connect(new, timeout=10)
            logger.info(f'adb connect {new} -> {result}')
        except Exception as e:
            logger.warning(f'adb connect {new} 失败：{type(e).__name__}: {e}')

    @staticmethod
    def find_mumu_manager(emulatorinfo_path: str) -> str:
        """从 MuMuNxMain.exe 推出同目录的 MuMuManager.exe，失败再试常见安装路径"""
        cands = []
        if emulatorinfo_path:
            folder = os.path.dirname(emulatorinfo_path.replace('\\', '/'))
            if folder:
                cands.append(os.path.join(folder, 'MuMuManager.exe'))
        cands.append('E:/app/mumu/MuMuPlayer/nx_main/MuMuManager.exe')
        for path in cands:
            if path and os.path.isfile(path):
                return path.replace('\\', '/')
        return ''

    @staticmethod
    def read_mumu_info(mgr: str, index: int) -> dict:
        """执行 MuMuManager info -v <index> 并解析 JSON，失败返回 {}"""
        try:
            p = subprocess.run(
                [mgr, 'info', '-v', str(index)],
                capture_output=True, timeout=15,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception as e:
            logger.warning(f'调用 MuMuManager 失败：{type(e).__name__}: {e}')
            return {}
        text = (p.stdout or b'').decode('utf-8', 'replace')
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            logger.warning(f'MuMuManager 输出无法解析：{text[:120]!r}')
            return {}
        try:
            info = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            logger.warning(f'MuMuManager 输出 JSON 解析失败：{e}')
            return {}
        # 实例不存在时返回 {"errcode": -200, "errmsg": "player index not found"}
        if info.get('errcode') not in (None, 0):
            logger.warning(f'MuMuManager 报错：{info.get("errmsg") or info.get("errcode")}（实例 {index}）')
            return {}
        if str(info.get('index', '')) != str(index):
            logger.warning(f'MuMuManager 返回实例号不匹配：{info.get("index")!r} != {index}')
            return {}
        return info

    @cached_property
    def is_bluestacks4_hyperv(self):
        return "bluestacks4-hyperv" in self.serial

    @cached_property
    def is_bluestacks5_hyperv(self):
        return "bluestacks5-hyperv" in self.serial

    @cached_property
    def is_bluestacks_hyperv(self):
        return self.is_bluestacks4_hyperv or self.is_bluestacks5_hyperv

    @cached_property
    def is_wsa(self):
        return bool(re.match(r'^wsa', self.serial))

    @cached_property
    def is_mumu_family(self):
        return self.serial == '127.0.0.1:7555'

    @cached_property
    def is_emulator(self):
        return self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:')

    @cached_property
    def is_network_device(self):
        return bool(re.match(r'\d+\.\d+\.\d+\.\d+:\d+', self.serial))

    @cached_property
    def is_over_http(self):
        return bool(re.match(r"^https?://", self.serial))

    @cached_property
    def is_chinac_phone_cloud(self):
        # Phone cloud with public ADB connection
        # Serial like xxx.xxx.xxx.xxx:301
        return bool(re.search(r":30[0-9]$", self.serial))

    @staticmethod
    def find_bluestacks4_hyperv(serial):
        """
        Find dynamic serial of BlueStacks4 Hyper-V Beta.

        Args:
            serial (str): 'bluestacks4-hyperv', 'bluestacks4-hyperv-2' for multi instance, and so on.

        Returns:
            str: 127.0.0.1:{port}
        """
        from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx

        logger.info("Use BlueStacks4 Hyper-V Beta")
        logger.info("Reading Realtime adb port")

        if serial == "bluestacks4-hyperv":
            folder_name = "Android"
        else:
            folder_name = f"Android_{serial[19:]}"

        try:
            with OpenKey(HKEY_LOCAL_MACHINE,
                         rf"SOFTWARE\BlueStacks_bgp64_hyperv\Guests\{folder_name}\Config") as key:
                port = QueryValueEx(key, "BstAdbPort")[0]
        except FileNotFoundError:
            logger.error(rf'Unable to find registry HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_bgp64_hyperv\Guests\{folder_name}\Config')
            logger.error('Please confirm that your are using BlueStack 4 hyper-v and not regular BlueStacks 4')
            logger.error(r'Please check if there is any other emulator instances under '
                         r'registry HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_bgp64_hyperv\Guests')
            raise RequestHumanTakeover
        logger.info(f"New adb port: {port}")
        return f"127.0.0.1:{port}"

    @staticmethod
    def find_bluestacks5_hyperv(serial):
        """
        Find dynamic serial of BlueStacks5 Hyper-V.

        Args:
            serial (str): 'bluestacks5-hyperv', 'bluestacks5-hyperv-1' for multi instance, and so on.

        Returns:
            str: 127.0.0.1:{port}
        """
        from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx

        logger.info("Use BlueStacks5 Hyper-V")
        logger.info("Reading Realtime adb port")

        if serial == "bluestacks5-hyperv":
            parameter_name = r"bst\.instance\.(Nougat64|Pie64)\.status\.adb_port"
        else:
            parameter_name = rf"bst\.instance\.(Nougat64|Pie64)_{serial[19:]}\.status.adb_port"

        try:
            with OpenKey(HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt") as key:
                directory = QueryValueEx(key, 'UserDefinedDir')[0]
        except FileNotFoundError:
            try:
                with OpenKey(HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt_cn") as key:
                    directory = QueryValueEx(key, 'UserDefinedDir')[0]
            except FileNotFoundError:
                logger.error('Unable to find registry HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_nxt '
                             'or HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_nxt_cn')
                logger.error('Please confirm that you are using BlueStacks 5 hyper-v and not regular BlueStacks 5')
                raise RequestHumanTakeover
        logger.info(f"Configuration file directory: {directory}")

        with open(os.path.join(directory, 'bluestacks.conf'), encoding='utf-8') as f:
            content = f.read()
        port = re.search(rf'{parameter_name}="(\d+)"', content)
        if port is None:
            logger.warning(f"Did not match the result: {serial}.")
            raise RequestHumanTakeover
        port = port.group(2)
        logger.info(f"Match to dynamic port: {port}")
        return f"127.0.0.1:{port}"

    @cached_property
    def adb_binary(self):
        # Try adb in deploy.yaml
        # from module.webui.setting import State
        # file = State.deploy_config.AdbExecutable
        # file = file.replace('\\', '/')
        # if os.path.exists(file):
        #     return os.path.abspath(file)
        #
        # # Try existing adb.exe
        # for file in self.adb_binary_list:
        #     if os.path.exists(file):
        #         return os.path.abspath(file)

        # Try adb in python environment
        import sys
        file = os.path.join(sys.executable, '../Lib/site-packages/adbutils/binaries/adb.exe')
        file = os.path.abspath(file).replace('\\', '/')
        if os.path.exists(file):
            return file

        # Use adb in system PATH
        file = 'adb'
        return file

    @cached_property
    def adb_client(self) -> AdbClient:
        host = '127.0.0.1'
        port = 5037

        # Trying to get adb port from env
        env = os.environ.get('ANDROID_ADB_SERVER_PORT', None)
        if env is not None:
            try:
                port = int(env)
            except ValueError:
                logger.warning(f'Invalid environ variable ANDROID_ADB_SERVER_PORT={port}, using default port')

        logger.attr('AdbClient', f'AdbClient({host}, {port})')
        return AdbClient(host, port)

    @cached_property
    def adb(self) -> AdbDevice:
        return AdbDevice(self.adb_client, self.serial)

    @cached_property
    def u2(self) -> u2.Device:
        # 连之前先确认设备里的 u2 服务活着。
        # 服务死了的时候 connect() 与 click() 都不会报错，只是点了没反应
        # （日志照打 Click），排查成本极高，见 module/device/u2_health.py。
        try:
            from module.device.u2_health import ensure_u2_service

            ensure_u2_service(self.adb_binary, self.serial)
        except Exception as e:
            logger.warning(f'u2 服务体检异常，继续连接: {type(e).__name__}: {e}')

        if self.is_over_http:
            # Using uiautomator2_http
            device = u2.connect(self.serial)
        else:
            # Normal uiautomator2
            if self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:'):
                device = u2.connect_usb(self.serial)
            else:
                device = u2.connect(self.serial)

        # Stay alive
        device.set_new_command_timeout(604800)

        logger.attr('u2.Device', f'Device(atx_agent_url={device._get_atx_agent_url()})')
        return device


