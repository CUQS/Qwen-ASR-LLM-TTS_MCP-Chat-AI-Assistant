from datetime import datetime
import os
import subprocess
from urllib.parse import urlparse
import webbrowser

from mcp.server.fastmcp import FastMCP

from ai_assist_memo import memo_store
from get_weather.get_weather import get_yahoo_weather
from switchbot import api as _switch

mcp = FastMCP("MyLocalHelper")


@mcp.tool(
    name="read_directory",
    description="获取所给路径的文件列表",
)
def read_directory(path: str = "."):
    return os.listdir(path)


@mcp.tool(
    name="run_command",
    description="执行本地终端命令，一定要获取到用户的明确许可才使用此工具。",
)
def run_command(command: str):
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return {"stdout": result.stdout, "stderr": result.stderr}


@mcp.tool(
    name="yahoo_weather",
    description="获取东京都东久留米市（Higashikurume）的雅虎天气预报。",
)
def yahoo_weather():
    return get_yahoo_weather()


@mcp.tool(
    name="control_switchbot_devices",
    description="""
    使用 SwitchBot 控制客厅设备（灯、空调等）。

    参数:
      - action: 'on'|'off'|'brightnessUp'|'brightnessDown'|'setBrightness'
        其中 brightnessUp / brightnessDown / setBrightness 仅适用于灯
      - names: 设备名称字符串（逗号分隔）或列表，例如 '客厅1,客厅2,空调1' 或 ['客厅1','客厅2']
        目前客厅有两个灯（客厅1、客厅2）和一个空调（空调1），传 None 则默认控制客厅1和客厅2
      - brightness: 整数 0-100，仅在 'setBrightness' 时需要

    返回 API 响应或错误信息字典。
    """,
)
def control_switchbot_devices(action: str, names=None, brightness: int | None = None):
    try:
        token, secret = _switch.load_token_secret()
    except Exception as e:
        return {"error": f"Missing SWITCHBOT_TOKEN/SECRET; failed to load from token.json: {e}"}

    headers = _switch.make_headers(token, secret)

    # 使用本地设备清单（如果可用），否则从 API 获取
    devices = []
    if isinstance(_switch.DEVICES_LIST, dict):
        devices = _switch.DEVICES_LIST.get("devices", []) or []
    if not devices:
        devices = _switch.list_devices(headers)

    # 解析 names 参数
    if names is None:
        names_list = None
    elif isinstance(names, list):
        names_list = names
    elif isinstance(names, str):
        if "," in names:
            names_list = [n.strip() for n in names.split(",") if n.strip()]
        else:
            names_list = [names]
    else:
        return {"error": "Invalid names type; must be None, str or list"}

    try:
        results = _switch.control_devices_by_name(action, headers, devices, names_list, brightness)
    except Exception as e:
        return {"error": str(e)}
    return results


@mcp.tool(
    name="get_switchbot_hub2_info",
    description="获取客厅的 SwitchBot Hub 的信息，包括设备名，客厅的温度，湿度，光照。",
)
def get_switchbot_hub2_info(names=None):
    try:
        token, secret = _switch.load_token_secret()
    except Exception as e:
        return {"error": f"Missing SWITCHBOT_TOKEN/SECRET; failed to load from token.json: {e}"}

    headers = _switch.make_headers(token, secret)

    # 使用本地设备清单（如果可用），否则从 API 获取
    devices = []
    if isinstance(_switch.DEVICES_LIST, dict):
        devices = _switch.DEVICES_LIST.get("devices", []) or []
    if not devices:
        devices = _switch.list_devices(headers)

    hubs = [d for d in devices if "Hub" in d.get("deviceType", "")]

    # 解析 names 参数
    if names is None:
        names_list = None
    elif isinstance(names, list):
        names_list = names
    elif isinstance(names, str):
        if "," in names:
            names_list = [n.strip() for n in names.split(",") if n.strip()]
        else:
            names_list = [names]
    else:
        return {"error": "Invalid names type; must be None, str or list"}

    def describe_light_level(level: int):
        """将 1-15 的光照等级映射到 5 个等级的中文描述。"""
        try:
            lv = int(level)
        except Exception:
            return {"level": None, "description": "未知"}
        if lv < 1 or lv > 15:
            return {"level": lv, "description": "超出范围（非 1-15）"}
        if lv <= 3:
            desc = "极暗"
        elif lv <= 6:
            desc = "暗"
        elif lv <= 9:
            desc = "适中"
        elif lv <= 12:
            desc = "明亮"
        else:
            desc = "非常明亮"
        return {"level": lv, "description": desc, "scale": "1-15"}

    results = []
    for h in hubs:
        name = h.get("deviceName", "")
        if names_list:
            matched = False
            for n in names_list:
                if n == name or (isinstance(name, str) and n in name):
                    matched = True
                    break
            if not matched:
                continue

        device_id = h.get("deviceId")
        try:
            status = _switch.get_device_status(device_id, headers)
        except Exception as e:
            status = {"error": str(e)}

        if isinstance(status, dict) and isinstance(status.get("body"), dict):
            body = status["body"]
            body.pop("version", None)
            body.pop("deviceId", None)
            body.pop("hubDeviceId", None)

            candidate_keys = [
                "light",
                "illuminance",
                "lux",
                "illuminanceLux",
                "lightLevel",
                "brightness",
                "illuminanceLv",
                "ambientLight",
            ]
            for k in candidate_keys:
                if k not in body:
                    continue
                val = body.get(k)
                try:
                    lv = int(val)
                except Exception:
                    continue
                if 1 <= lv <= 15:
                    desc = describe_light_level(lv)
                    body["light_level"] = desc["level"]
                    body["light_description"] = desc["description"]
                    body["light_scale"] = desc["scale"]
                    body["light_key"] = k
                    break

        results.append({"device": name, "status": status})

    if not results:
        return {"message": "No Hub devices found matching filter", "hubs_found": len(hubs)}
    return results


@mcp.tool(
    name="get_switchbot_outdoor_sensor",
    description="查询室外防水温湿度计（防水温湿度計 0E）的状态，包括温度、湿度、电量等。",
)
def get_switchbot_outdoor_sensor(name: str = "防水温湿度計 0E"):
    try:
        token, secret = _switch.load_token_secret()
    except Exception as e:
        return {"error": f"Missing SWITCHBOT_TOKEN/SECRET; failed to load from token.json: {e}"}

    headers = _switch.make_headers(token, secret)

    try:
        res = _switch.get_wiosensor_status_by_name(name, headers)
    except Exception as e:
        return {"error": str(e)}

    return res


@mcp.tool(
    name="get_current_time",
    description="返回当前时间，包含 ISO 格式、本地可读格式与 Unix 时间戳。可选参数 tz（例如 'Asia/Tokyo'）来指定时区。",
)
def get_current_time(tz: str = None):
    try:
        if tz:
            try:
                from zoneinfo import ZoneInfo

                dt = datetime.now(ZoneInfo(tz))
            except Exception as e:
                return {"error": f"Invalid timezone '{tz}': {e}"}
        else:
            dt = datetime.now().astimezone()

        iso = dt.isoformat()
        readable = dt.strftime("%Y-%m-%d %H:%M:%S %Z%z")
        ts = int(dt.timestamp())
        return {"iso": iso, "readable": readable, "timestamp": ts}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(
    name="open_website",
    description="在默认浏览器中打开给定网址（仅支持 http/https），返回操作结果。",
)
def open_website(url: str, open_in_new: bool = True):
    if not url:
        return {"error": "No URL provided"}

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"error": f"Invalid URL or unsupported scheme: {url}"}

    try:
        new = 2 if open_in_new else 0
        success = webbrowser.open(url, new=new)
        return {
            "url": url,
            "opened": bool(success),
            "message": "Opened in browser" if success else "Browser call returned False",
        }
    except Exception as e:
        return {"error": str(e)}


def _memo_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(
    name="memo_create",
    description="新建备忘录，保存到 ai_assist_memo/data/YYYY/MM。content 为正文，title 和 timestamp 可选。",
)
def memo_create(content: str, title: str = "", timestamp: str = ""):
    ts = timestamp.strip() or None
    return _memo_call(memo_store.create_memo, content=content, title=title, timestamp=ts)


@mcp.tool(
    name="memo_list",
    description="列出备忘录文件，支持 year/month 过滤。include_todo=true 时包含 todo.md。",
)
def memo_list(year: int | None = None, month: int | None = None, limit: int = 100, include_todo: bool = False):
    return _memo_call(
        memo_store.list_memos,
        year=year,
        month=month,
        limit=limit,
        include_todo=include_todo,
    )


@mcp.tool(
    name="memo_read",
    description="读取备忘录内容。path 使用相对路径，例如 2026/02/20260212_093000.md 或 todo.md。",
)
def memo_read(path: str):
    return _memo_call(memo_store.read_memo, path=path)


@mcp.tool(
    name="memo_update",
    description="更新指定备忘录。mode 仅支持 replace(覆盖)、append(追加)、prepend(前插)。需要直接调用工具，不要把调用参数当普通文本回复。",
)
def memo_update(path: str, content: str, mode: str = "replace"):
    return _memo_call(memo_store.update_memo, path=path, content=content, mode=mode)


@mcp.tool(
    name="memo_delete",
    description="删除指定备忘录。必须传 confirm=true 才会执行删除。",
)
def memo_delete(path: str, confirm: bool = False):
    if not confirm:
        return {"deleted": False, "message": "Set confirm=true to delete memo."}
    return _memo_call(memo_store.delete_memo, path=path)


@mcp.tool(
    name="memo_update_todo",
    description="更新待办文件 ai_assist_memo/data/todo.md。mode 仅支持 replace、append、prepend。用户说“更新 to do/待办”时优先调用此工具。",
)
def memo_update_todo(content: str, mode: str = "append"):
    return _memo_call(memo_store.update_todo, content=content, mode=mode)


@mcp.tool(
    name="clear_chat",
    description="清空 AI 助手的当前聊天记录（当模型主动调用此工具时）",
)
def clear_chat(confirm: bool = True):
    if not confirm:
        return {"cleared": False, "message": "Confirmation required"}
    return {"cleared": True, "message": "Chat cleared"}


if __name__ == "__main__":
    mcp.run()
