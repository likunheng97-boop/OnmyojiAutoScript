# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
from pydantic import BaseModel
from module.config.utils import convert_to_underscore

from module.logger import logger
from module.server.main_manager import mm
from module.server.script_process import ScriptProcess, ScriptState

from tasks.Component.config_base import TimeDelta


script_app = APIRouter()


@script_app.get('/test')
async def script_test():
    return 'success'

@script_app.get('/script_menu')
async def script_menu():
    return mm.config_cache('template').gui_menu_list
# ----------------------------------   配置文件管理   ----------------------------------
@script_app.get('/config_list')
async def config_list():
    return mm.all_script_files()

@script_app.post('/config_copy')
async def config_copy(file: str, template: str = 'template'):
    mm.copy(file, template)
    return mm.all_script_files()

@script_app.get('/config_new_name')
async def config_new_name():
    return mm.generate_script_name()

@script_app.get('/config_all')
async def config_all():
    return mm.all_json_file()


@script_app.put('/config')
async def config_rename(old_name: str = '', new_name: str = ''):
    """
    update config name
    :param old_name: old config name
    :param new_name: new config name
    :return: True or False
    """
    if old_name == new_name or new_name == '':
        return False
    if old_name in mm.script_process:
        if mm.script_process[old_name].state != ScriptState.INACTIVE:
            mm.script_process[old_name].stop()
        del mm.script_process[old_name]
    if not mm.rename(old_name, new_name):
        raise HTTPException(status_code=400, detail='Rename failed')
    return True


@script_app.delete('/config')
async def config_delete(name: str = ''):
    """
    delete config file
    :param name: config name
    :return: True or False
    """
    if name == '' or name == 'template':
        raise HTTPException(status_code=400, detail='Delete failed')
    if name in mm.script_process:
        if mm.script_process[name].state != ScriptState.INACTIVE:
            mm.script_process[name].stop()
        del mm.script_process[name]
    if not mm.delete(name):
        raise HTTPException(status_code=400, detail='Delete failed')
    return True


@script_app.put('/config/task/copy')
async def task_copy(task_name: str, dest_config_name: str, source_config_name: str):
    if dest_config_name not in mm.script_process or source_config_name not in mm.script_process:
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_script_task(task_name, source_task)


@script_app.put('/config/task/group/copy')
async def task_group_copy(task_name: str, group_name: str, dest_config_name: str, source_config_name: str):
    if dest_config_name not in mm.script_process or source_config_name not in mm.script_process:
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_task_group(task_name, group_name, source_task)


# ---------------------------------   脚本实例管理   ----------------------------------
@script_app.get('/{script_name}/start')
async def script_start(script_name: str):
    if script_name not in mm.script_process:
        mm.script_process[script_name] = ScriptProcess(script_name)
    mm.script_process[script_name].start()
    return

@script_app.get('/{script_name}/stop')
async def script_stop(script_name: str):
    if script_name not in mm.script_process:
        logger.warning(f'[{script_name}] script process does not exist')
        return
    mm.script_process[script_name].stop()
    return

@script_app.get('/{script_name}/{task}/args')
async def script_task(script_name: str, task: str):
    return mm.config_cache(script_name).model.script_task(task)

@script_app.put('/{script_name}/{task}/{group}/{argument}/value')
async def script_task(script_name: str, task: str, group: str, argument: str, types: str, value):
    try:
        match types:
            case 'integer':
                value = int(value)
            case 'number':
                value = float(value)
            case 'boolean':
                if isinstance(value, str):
                    logger.warning(f'[{script_name}] script argument {argument} value is string, try to convert to bool')
                    if value.lower() in ['true', '1']:
                        value = True
                    elif value.lower() in ['false', '0']:
                        value = False
                value = bool(value)
            case 'string':
                pass
            case 'date_time':
                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            case 'time_delta':
                # strptime 是个好东西，但是不能解析00的天数
                day = int(value[1])
                date_time = datetime.strptime(value[3:], '%H:%M:%S')
                value = TimeDelta(days=day, hours=date_time.hour, minutes=date_time.minute, seconds=date_time.second)
            case 'time':
                value = datetime.strptime(value, '%H:%M:%S').time()
            case _: pass
    except Exception as e:
        # 类型不正确
        raise HTTPException(status_code=400, detail=f'Argument type error: {e}')
    return mm.config_cache(script_name).model.script_set_arg(task, group, argument, value)


@script_app.put('/{script_name}/{task}/sync_next_run')
async def sync_next_run(script_name: str, task: str, target_dt: str):
    if script_name not in mm.script_process:
        return False
    config = mm.config_cache(script_name)
    target = datetime.strptime(target_dt, '%Y-%m-%d %H:%M:%S') if target_dt else None
    config.task_delay(task=task, success=True, target=target)
    script_process = mm.script_process[script_name]
    config.get_next()
    await script_process.broadcast_state({"schedule": config.get_schedule_data()})
    return True


# --------------------------------------  SSE  --------------------------------------
@script_app.get('/{script_name}/state')
async def script_task_state(script_name: str):
    async def state_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: Hello, SSE!\n\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(state_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

@script_app.get('/{script_name}/log')
async def script_task_log(script_name: str):
    async def log_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: log\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(log_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

# -------------------------------   快捷操作（本地定制）   -------------------------------
# oasx 顶部工具条的「一键全停 / 全部启动 / 任务预设」用到。
# 全部是新增路由，不改动上面的既有逻辑；预设的读写都走 ConfigModel，
# 与 GUI 改参数共用同一套 pydantic 校验。
PRESET_EXCLUDED_FIELDS = {'script', 'restart', 'global_game'}


class PresetBody(BaseModel):
    # 任务参数快照 {task_name: {group: {arg: value}}}，只覆盖这里出现的任务
    tasks: Optional[Dict[str, dict]] = None
    # 要启用的任务（下划线名）；不在这里的菜单任务会被关掉
    enable: Optional[List[str]] = None
    # 落盘后是否启动调度器
    start: bool = True


def preset_task_fields(config) -> List[str]:
    """该配置里所有「带调度器的任务」字段名（已排除 script/restart/global_game）"""
    names = []
    for name in type(config.model).model_fields.keys():
        if name in PRESET_EXCLUDED_FIELDS:
            continue
        task = getattr(config.model, name, None)
        if task is None or getattr(task, 'scheduler', None) is None:
            continue
        names.append(name)
    return names


def preset_menu_tasks() -> set:
    """GUI 菜单里能看到的任务（下划线名）。隐藏任务（如 orochi_moans）不在其中，
    预设不会去关它们，避免把八岐大蛇流程依赖的隐藏任务误关掉。"""
    result = set()
    for tasks in mm.config_cache('template').gui_menu_list.values():
        for task in tasks:
            result.add(convert_to_underscore(task))
    return result


@script_app.get('/{script_name}/preset')
async def preset_snapshot(script_name: str):
    """导出当前配置的任务参数快照 + 已启用任务，供 oasx「存为预设」使用"""
    if script_name not in mm.script_process:
        raise HTTPException(status_code=404, detail='config not found')
    config = mm.config_cache(script_name)
    data = config.model.model_dump(mode='json')
    tasks, enable = {}, []
    for name in preset_task_fields(config):
        item = dict(data.get(name) or {})
        scheduler = item.pop('scheduler', None) or {}
        tasks[name] = item
        if scheduler.get('enable'):
            enable.append(name)
    return {'config': script_name, 'tasks': tasks, 'enable': enable}


@script_app.post('/{script_name}/preset')
async def preset_apply(script_name: str, body: PresetBody):
    """按预设覆盖任务参数与启用状态，然后（可选）重启调度器。

    顺序很重要：先停掉旧进程 → 改内存 → 一次落盘 → 再启动，
    避免子进程读到「零个任务」的中间态，也避免 ScriptProcess.start()
    里漏 await 的 stop 导致同一配置跑出两个调度器。
    """
    if script_name not in mm.script_process:
        raise HTTPException(status_code=404, detail='config not found')
    config = mm.config_cache(script_name)
    model = config.model
    known = set(preset_task_fields(config))
    menu_tasks = preset_menu_tasks()
    wanted = {convert_to_underscore(t) for t in (body.enable or [])} & known
    now = datetime.now().replace(microsecond=0)

    # 1. 覆盖任务参数（只处理快照里带来的任务，失败的任务保持原样并如实返回）
    applied, failed = [], []
    for task_name, params in (body.tasks or {}).items():
        task_name = convert_to_underscore(task_name)
        if task_name not in known or not isinstance(params, dict):
            continue
        task_obj = getattr(model, task_name)
        scheduler = getattr(task_obj, 'scheduler', None)
        raw = {k: v for k, v in params.items() if k != 'scheduler'}
        try:
            new_task = type(task_obj).model_validate(raw)
        except Exception as e:
            logger.warning(f'[{script_name}] preset skip task {task_name}: {e}')
            failed.append(task_name)
            continue
        if scheduler is not None:
            new_task.scheduler = scheduler
        try:
            # 用 object.__setattr__ 绕过 ConfigModel.__setattr__ 的「每次赋值就整份写盘」，
            # 否则 50+ 个任务会把配置反复落盘，运行中的子进程还可能读到半新半旧的中间态。
            object.__setattr__(model, task_name, new_task)
            applied.append(task_name)
        except Exception as e:
            logger.warning(f'[{script_name}] preset apply task {task_name} failed: {e}')
            failed.append(task_name)

    # 2. 启用/关闭任务
    for name in known:
        scheduler = getattr(getattr(model, name), 'scheduler', None)
        if scheduler is None:
            continue
        if name in wanted:
            scheduler.enable = True
            scheduler.next_run = now
        elif name in menu_tasks:
            scheduler.enable = False

    # 3. 一次落盘
    config.save()
    logger.info(f'[{script_name}] preset applied: enable={sorted(wanted)} params={len(applied)}')

    # 4. 重启调度器
    sp = mm.script_process[script_name]
    if sp._process is not None:
        await sp.stop()
    if body.start and wanted:
        await sp.start()
    return {'config': script_name, 'enable': sorted(wanted), 'params': sorted(applied),
            'failed': sorted(failed), 'state': int(sp.state)}


@script_app.post('/stop_all')
async def stop_all():
    """停掉所有实例的调度器（硬杀子进程，模拟器与游戏不受影响）"""
    result = {}
    for name, script_process in list(mm.script_process.items()):
        try:
            if script_process._process is not None or script_process.state != ScriptState.INACTIVE:
                await script_process.stop()
        except Exception as e:
            logger.exception(f'[{name}] stop_all failed: {e}')
        result[name] = int(script_process.state)
    return result


@script_app.post('/start_all')
async def start_all():
    """启动所有实例的调度器，任务编排保持当前配置不变。

    没有启用任何任务的实例会被跳过：Config.get_next() 在零任务时会抛
    RequestHumanTakeover，直接 start 会让子进程崩掉。
    """
    result = {}
    for name, script_process in list(mm.script_process.items()):
        try:
            config = mm.config_cache(name)
            enabled = []
            for n in preset_task_fields(config):
                scheduler = getattr(getattr(config.model, n), 'scheduler', None)
                if scheduler is not None and scheduler.enable:
                    enabled.append(n)
            if not enabled:
                result[name] = {'state': int(script_process.state), 'skipped': 'no task enabled'}
                continue
            if script_process._process is not None and script_process._process.is_alive():
                result[name] = {'state': int(script_process.state), 'skipped': 'already running'}
                continue
            await script_process.start()
            result[name] = {'state': int(script_process.state)}
        except Exception as e:
            logger.exception(f'[{name}] start_all failed: {e}')
            result[name] = {'state': int(script_process.state), 'error': str(e)}
    return result


# -------------------------------------- websocket --------------------------------------

@script_app.websocket("/ws/{script_name}")
async def websocket_endpoint(websocket: WebSocket, script_name: str):
    if script_name not in mm.script_process:
        mm.script_process[script_name] = ScriptProcess(script_name)
    script_process = mm.script_process[script_name]
    await script_process.connect(websocket)

    try:
        await script_process.send_json(websocket, {"state": script_process.state})
        config = mm.config_cache(script_name)
        config.get_next()
        await script_process.send_json(websocket, {"schedule": config.get_schedule_data()})

        while True:
            # 初次进入，广播state schedule
            data = await websocket.receive_text()
            if data == 'get_state':
                await script_process.broadcast_state({"state": script_process.state})
            elif data == 'get_schedule':
                config = mm.config_cache(script_name)
                config.get_next()
                await script_process.broadcast_state({"schedule": config.get_schedule_data()})
            elif data == 'start':
                await script_process.start()
            elif data == 'stop':
                await script_process.stop()

    except WebSocketDisconnect:
        logger.warning(f'[{script_name}] websocket disconnect')
        await script_process.disconnect(websocket)
    except Exception as e:
        logger.exception(f'[{script_name}] websocket error: {e}')
        await script_process.disconnect(websocket)
