# This Python file uses the following encoding: utf-8
"""uiautomator2 服务（com.github.uiautomator）的健康检查。

2026-11-11 踩坑：模拟器里的 atx-agent 进程还活着（`/ping` 返回 pong、
`/shell?command=echo` 正常执行），但它托管的 u2 服务已经死了。
OAS 的点击/滑动全部经由这个服务下发，服务不在时：

  * ``u2.Device.click()`` 不报错，日志照打 ``Click (x, y) @ xxx``；
  * 屏幕上什么都不发生，``ui_page_appear()`` 一直等到超时；
  * atx-agent 的 ``/screenshot/0`` 返回 500 + ``screencap: exit status 1``
    —— 它取的图也走这个服务。

表现就是「能看画面、日志在点、游戏不动」，跟 atx-agent 僵死一模一样，
但只需要把 u2 服务拉起来，不必重启 atx-agent（重启会断掉已有会话）。

本模块只做「探测 + 拉起」，全部带超时，失败只打日志不抛异常，
不阻塞任务启动。
"""
import subprocess
import time

import requests

from module.logger import logger

# 设备内 atx-agent 监听的端口（adb forward 的远端）
ATX_DEVICE_PORT = 7912
# 单次探测超时（秒）
PROBE_TIMEOUT = 6
# 拉起服务后最多等多久（秒）。实测冷启动 3~10 秒
SERVICE_WAIT = 20
# atx-agent 重启命令，与监控脚本 oas_monitor.py 里的 ATX_RESTART_SH 保持一致
ATX_RESTART_SH = (
    "/data/local/tmp/atx-agent server --stop; sleep 1; "
    "/data/local/tmp/atx-agent server -d --addr 127.0.0.1:7912"
)

# 复用连接：每次 requests.get() 都新建 Session 会带一条 TCP 握手（约 0.3 秒），
# 而且 urllib3 的连接池对象会缓慢累积。长期挂机这个函数每 3 分钟调一次，
# 用共享 Session 后单次探测降到几十毫秒，且内存稳定。
_session = None


def _sess():
    global _session
    if _session is None:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=2, pool_maxsize=4, max_retries=1,
        )
        s.mount('http://', adapter)
        _session = s
    return _session


def _drop_session():
    """连接出问题时丢掉共享 Session，下次重建。"""
    global _session
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
        _session = None


def adb_forward_port(adb_binary, serial):
    """从 ``adb forward --list`` 里找 serial 对应的 atx 本地端口。

    端口是动态分配的（重启模拟器 / 重连设备都会变），所以每次现查，
    不能写死。
    """
    try:
        out = subprocess.run(
            [adb_binary, "forward", "--list"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10,
        ).stdout or ""
    except Exception as e:
        logger.warning(f"读取 adb forward 列表失败: {type(e).__name__}: {e}")
        return None

    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[0] != serial:
            continue
        local, remote = parts[1], parts[2]
        if not remote.endswith(f":{ATX_DEVICE_PORT}"):
            continue
        if not local.startswith("tcp:"):
            continue
        try:
            return int(local[4:])
        except ValueError:
            continue
    return None


def probe_u2_service(port):
    """u2 服务是否活着：拉一次 atx 的 ``/screenshot/0``，只看前 4KB。

    服务正常 -> 200 + PNG 头；服务死了 -> 500，响应体是
    ``screencap: exit status 1`` 这类纯文本。
    用 stream 读前几 KB 就断开，避免每次探测在内存里塞 1.4MB 整图。
    """
    try:
        with _sess().get(
            f"http://127.0.0.1:{port}/screenshot/0",
            timeout=PROBE_TIMEOUT, stream=True,
        ) as r:
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            head = b""
            for chunk in r.iter_content(1024):
                head += chunk
                if len(head) >= 4096:
                    break
            if head[:4] == b"\x89PNG":
                return True, "截图正常"
            text = head[:60].decode("utf-8", "ignore").replace("\n", " ").strip()
            return False, f"截图异常（{len(head)}B: {text}）"
    except Exception as e:
        _drop_session()
        return False, f"请求失败 {type(e).__name__}: {str(e)[:80]}"


def start_u2_service(port):
    """让 atx-agent 把 u2 服务拉起来，返回 atx 的响应文本（便于排查）。"""
    try:
        r = _sess().post(
            f"http://127.0.0.1:{port}/uiautomator", timeout=PROBE_TIMEOUT,
        )
        return (r.text or "").strip()[:80]
    except Exception as e:
        _drop_session()
        return f"请求失败 {type(e).__name__}: {str(e)[:80]}"


def restart_atx_agent(adb_binary, serial, timeout=SERVICE_WAIT + 20):
    """重启设备内的 atx-agent（兜底手段）。"""
    try:
        subprocess.run(
            [adb_binary, "-s", serial, "shell", ATX_RESTART_SH],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        return True
    except Exception as e:
        logger.error(f"重启 atx-agent 失败: {type(e).__name__}: {e}")
        return False


def wait_ready(port, wait_seconds):
    """轮询等 u2 服务可用。"""
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(1.5)
        ok, _ = probe_u2_service(port)
        if ok:
            return True
    return False


def ensure_u2_service(adb_binary, serial, wait_seconds=SERVICE_WAIT):
    """确保 u2 服务可用，返回是否可用。

    流程：探测 -> 不通就 POST /uiautomator 拉起 -> 还不行就重启 atx-agent。
    整个函数的耗时上限约 ``2 * wait_seconds + 30`` 秒，且只在故障时发生；
    正常情况一次探测（<1 秒）返回。
    """
    port = adb_forward_port(adb_binary, serial)
    if not port:
        logger.warning(f"查不到 {serial} 的 atx 端口映射，跳过 u2 服务体检")
        return False

    ok, detail = probe_u2_service(port)
    if ok:
        logger.info(f"u2 服务正常（atx:{port}，{detail}）")
        return True

    logger.warning(f"u2 服务无响应（atx:{port}，{detail}），尝试启动")
    reply = start_u2_service(port)
    logger.info(f"启动 u2 服务: {reply}")

    if wait_ready(port, wait_seconds):
        logger.info("u2 服务已恢复")
        return True

    logger.warning(f"启动 u2 服务无效，改为重启 atx-agent（{serial}）")
    if not restart_atx_agent(adb_binary, serial):
        return False
    if wait_ready(port, wait_seconds):
        logger.info("atx-agent 重启后 u2 服务已恢复")
        return True

    logger.error(f"u2 服务仍不可用，点击可能无效（{serial} atx:{port}）")
    return False
