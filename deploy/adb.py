# This Python file uses the following encoding: utf-8
# copy from alas https://github.com/LmeSzinc/AzurLaneAutoScript
import logging
import subprocess

from deploy.config import DeployConfig
from deploy.emulator import EmulatorConnect
from deploy.logger import logger
from deploy.utils import *

def show_fix_tip(module):
    logger.info(f"""
    To fix this:
    1. Open console.bat
    2. Execute the following commands:
        pip uninstall -y {module}
        pip install --no-cache-dir {module}
    3. Re-open Alas.exe
    """)


class AdbManager(DeployConfig):
    # 单台设备的探测超时（秒）。
    # adbutils 0.11 的 _read_fully() 是裸 socket.recv，没有超时；只要 adb server 那头
    # 不吐数据，调用方就永久阻塞。而 `adb devices` 里经常残留状态显示为 device、
    # 实际 guest 已经死掉的僵尸连接（模拟器异常退出、端口漂移后旧端口没清理干净），
    # 对它执行 adb shell 永远是「连得上、没回音」。
    DEVICE_PROBE_TIMEOUT = 8

    @cached_property
    def adb(self):
        return self.filepath('AdbExecutable')

    def probe_device(self, serial, timeout=None):
        """探测设备真的能执行 shell，而不是只看 `adb devices` 里的 device 状态。

        2026-11-11 踩坑：oasx 点「启动」后卡在服务启动日志的
        `UIAUTOMATOR2 INIT`，一卡十几分钟不往下走。py-spy 抓到主线程停在
            getprop (adbutils) -> __init__ (uiautomator2/init.py:146)
            -> adb_install (deploy/adb.py)
        原因是下面这个循环 `for device in adbutils.adb.iter_device()` 会把 adb
        设备表里所有 device 全部初始化一遍，当时表里混着 3 个僵尸：
            127.0.0.1:7555 / emulator-5554 / emulator-5556
        它们（以及清理前的 127.0.0.1:16384 / 16416）是模拟器端口漂移后留下的
        死连接，TCP 能连上但 guest 的 adbd 不响应，于是 getprop 永久阻塞。

        所以初始化前先用带超时的 subprocess 探一下，不通就跳过。

        Args:
            serial (str): 设备序列号，如 '127.0.0.1:16385'
            timeout (float): 覆盖默认超时

        Returns:
            bool: 能正常执行 shell 返回 True
        """
        timeout = self.DEVICE_PROBE_TIMEOUT if timeout is None else timeout
        try:
            ret = subprocess.run(
                [self.adb, '-s', str(serial), 'shell', 'echo', 'oas'],
                capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        except Exception as e:
            logger.info(f'Probe device {serial} error: {e}')
            return False
        return ret.returncode == 0 and b'oas' in ret.stdout

    def iter_device_safely(self):
        """`adbutils.adb.iter_device()` 的安全版：跳过探测不通的设备。

        只过滤，不改变其它行为；一个都通不了时和原来一样什么都不做。
        """
        import adbutils

        total = 0
        for device in adbutils.adb.iter_device():
            total += 1
            if not self.probe_device(device.serial):
                logger.info(
                    f'Skip device {device.serial}: adb shell 无响应'
                    f'（>{self.DEVICE_PROBE_TIMEOUT}s），'
                    f'疑似模拟器端口漂移后残留的僵尸连接')
                continue
            yield device
        if total == 0:
            logger.info('No device found, skip uiautomator2 init')

    def adb_install(self):
        logger.hr('Start ADB service', 0)

        emulator = EmulatorConnect(adb=self.adb)
        if self.ReplaceAdb:
            logger.hr('Replace ADB', 1)
            emulator.adb_replace()
        elif self.AutoConnect:
            logger.hr('ADB Connect', 1)
            emulator.brute_force_connect()

        if self.InstallUiautomator2:
            logger.hr('Uiautomator2 Init', 1)
            try:
                import adbutils
                from uiautomator2 import init
            except ModuleNotFoundError as e:
                message = str(e)
                for module in ['apkutils2', 'progress']:
                    # ModuleNotFoundError: No module named 'apkutils2'
                    # ModuleNotFoundError: No module named 'progress.bar'
                    if module in message:
                        show_fix_tip(module)
                        exit(1)
                raise

            # Remove global proxies, or uiautomator2 will go through it
            for k in list(os.environ.keys()):
                if k.lower().endswith('_proxy'):
                    del os.environ[k]

            # 用 iter_device_safely() 而不是 adbutils.adb.iter_device()：
            # 后者会把设备表里的僵尸连接也拿去初始化，getprop 永久阻塞（见 probe_device 注释）。
            for device in self.iter_device_safely():
                initer = init.Initer(device, loglevel=logging.DEBUG)
                # MuMu X has no ro.product.cpu.abi, pick abi from ro.product.cpu.abilist
                if initer.abi not in ['x86_64', 'x86', 'arm64-v8a', 'armeabi-v7a', 'armeabi']:
                    initer.abi = initer.abis[0]
                initer.set_atx_agent_addr('127.0.0.1:7912')

                for _ in range(2):
                    try:
                        initer.install()
                        break
                    except AssertionError:
                        logger.info(f'AssertionError when installing uiautomator2 on device {device.serial}')
                        logger.info('If you are using BlueStacks or LD player or WSA, '
                                    'please enable ADB in the settings of your emulator')
                        exit(1)
                    except ConnectionError:
                        if _ == 1:
                            raise
                        init.GITHUB_BASEURL = 'http://tool.appetizer.io/openatx'

                initer._device.shell(["rm", "/data/local/tmp/minicap"])
                initer._device.shell(["rm", "/data/local/tmp/minicap.so"])
