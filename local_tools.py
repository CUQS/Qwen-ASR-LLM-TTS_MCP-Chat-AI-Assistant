from mcp.server.fastmcp import FastMCP
import os
import subprocess
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
        devices = _switch.DEVICES_LIST.get('devices', []) or []
    if not devices:
        devices = _switch.list_devices(headers)

    # 解析 names 参数
    if names is None:
        names_list = None
    elif isinstance(names, list):
        names_list = names
    elif isinstance(names, str):
        if ',' in names:
            names_list = [n.strip() for n in names.split(',') if n.strip()]
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
        devices = _switch.DEVICES_LIST.get('devices', []) or []
    if not devices:
        devices = _switch.list_devices(headers)

    # 筛选 Hub 设备
    hubs = [d for d in devices if 'Hub' in d.get('deviceType', '')]

    # 解析 names 参数
    if names is None:
        names_list = None
    elif isinstance(names, list):
        names_list = names
    elif isinstance(names, str):
        if ',' in names:
            names_list = [n.strip() for n in names.split(',') if n.strip()]
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
        name = h.get('deviceName', '')
        # 过滤
        if names_list:
            matched = False
            for n in names_list:
                if n == name or (isinstance(name, str) and n in name):
                    matched = True
                    break
            if not matched:
                continue
        device_id = h.get('deviceId')
        try:
            status = _switch.get_device_status(device_id, headers)
        except Exception as e:
            status = {"error": str(e)}

        # 只在 status['body'] 是 dict 时安全地修改并添加光照描述
        if isinstance(status, dict) and isinstance(status.get("body"), dict):
            body = status["body"]
            body.pop("version", None)
            body.pop("deviceId", None)
            body.pop("hubDeviceId", None)

            # 尝试识别并注释光照等级（1-15）
            candidate_keys = ["light", "illuminance", "lux", "illuminanceLux", "lightLevel", "brightness", "illuminanceLv", "ambientLight"]
            found = False
            for k in candidate_keys:
                if k in body:
                    val = body.get(k)
                    try:
                        lv = int(val)
                    except Exception:
                        # 有些 key 可能是 lux 等较大数值，跳过非 1-15 的
                        continue
                    if 1 <= lv <= 15:
                        desc = describe_light_level(lv)
                        body["light_level"] = desc["level"]
                        body["light_description"] = desc["description"]
                        body["light_scale"] = desc["scale"]
                        body["light_key"] = k
                        found = True
                        break
            # 如果未找到 1-15 之间的等级，可以尝试将 lux 映射到 1-15（可选）
            # 这里不做 lux 到等级的自动映射，保持原状

        results.append({"device": name, "status": status})

    if not results:
        return {"message": "No Hub devices found matching filter", "hubs_found": len(hubs)}
    return results

@mcp.tool(
    name="get_switchbot_outdoor_sensor",
    description="查询室外防水温湿度计（防水温湿度計 0E）的状态，包括温度、湿度、电量等。",
)
def get_switchbot_outdoor_sensor(name: str = "防水温湿度計 0E"):
    """Query an outdoor WoIO temperature/humidity sensor by name.

    Default name is the local sensor: '防水温湿度計 0E'. Returns raw device status and
    a small parsed summary (temperature, humidity, battery, etc.)."""
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
    """返回当前时间的信息。

    参数:
      - tz: 可选的时区字符串（IANA 时区，例如 'Asia/Tokyo'）。如果未提供则使用本地时区。

    返回:
      dict: {"iso": str, "readable": str, "timestamp": int} 或 {"error": str}
    """
    from datetime import datetime
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
    """在默认浏览器中打开 URL。

    参数：
      - url: 要打开的 URL（必须以 http:// 或 https:// 开头）
      - open_in_new: 是否在新标签/窗口中打开（默认为 True）

    返回：
      dict，格式例如 {"url":str, "opened":bool, "message":str} 或 {"error":str}
    """
    from urllib.parse import urlparse
    import webbrowser

    if not url:
        return {"error": "No URL provided"}
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"error": f"Invalid URL or unsupported scheme: {url}"}

    try:
        new = 2 if open_in_new else 0
        success = webbrowser.open(url, new=new)
        return {"url": url, "opened": bool(success), "message": "Opened in browser" if success else "Browser call returned False"}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(
    name="clear_chat",
    description="清空 AI 助手的当前聊天记录（当模型主动调用此工具时）",
)
def clear_chat(confirm: bool = True):
    """请求清空当前聊天。

    参数：
      - confirm: 布尔，是否确认清空（默认为 True）。

    返回：
      dict，例如 {"cleared": True, "message": "Chat cleared"} 或 {"error": str}
    """
    if not confirm:
        return {"cleared": False, "message": "Confirmation required"}
    # 该工具仅返回结果；实际的 GUI/助手进程会在收到该工具调用结果后执行清空操作。
    return {"cleared": True, "message": "Chat cleared"}

if __name__ == "__main__":
    mcp.run()