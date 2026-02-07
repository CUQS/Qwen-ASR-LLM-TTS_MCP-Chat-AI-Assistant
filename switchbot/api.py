"""hub2_info.py

Usage:
  - Reads credentials from D:\\mcp\\switchbot\\token.json with keys SWITCHBOT_TOKEN and SWITCHBOT_SECRET (falls back to env vars or prompt if missing).
  - Run: python hub2_info.py

What it does:
  - Lists devices in your SwitchBot account.
  - Finds devices whose deviceType contains "Hub" (including "Hub 2").
  - Fetches and prints status for each Hub found.

Dependencies: requests (optional). The script falls back to urllib if requests isn't available.
"""

import os
import time
import uuid
import hmac
import hashlib
import base64
import json
import sys

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

BASE_URL = "https://api.switch-bot.com/v1.1"
with open('D:\\mcp\\switchbot\\devices_list.json', 'r', encoding='utf-8') as f:
    DEVICES_LIST = json.load(f)

# 检查并在必要时更新 devices_list.json 的 updated_at（在模块导入时执行，安全且不抛出异常）
try:
    from datetime import datetime
    DEVICES_JSON_PATH = os.path.join(os.path.dirname(__file__), 'devices_list.json')
    # 如果基于模块路径的文件不存在，回退到绝对路径（与原先读取路径一致）
    if not os.path.exists(DEVICES_JSON_PATH):
        DEVICES_JSON_PATH = r'D:\\mcp\\switchbot\\devices_list.json'
    today = datetime.now().strftime('%Y%m%d')
    existing = DEVICES_LIST.get('updated_at', '')
    if existing != today:
        DEVICES_LIST['updated_at'] = today
        try:
            with open(DEVICES_JSON_PATH, 'w', encoding='utf-8') as wf:
                json.dump(DEVICES_LIST, wf, ensure_ascii=False, indent=4)
            print(f"Updated {DEVICES_JSON_PATH}: updated_at {existing!r} -> {today!r}", file=sys.stderr)
        except Exception as e:
            print(f"Failed to write {DEVICES_JSON_PATH}: {e}", file=sys.stderr)
    else:
        print(f"{DEVICES_JSON_PATH} is up-to-date ({today})", file=sys.stderr)
except Exception as e:
    print(f"Error checking/updating devices_list.json: {e}", file=sys.stderr)

def make_headers(token: str, secret: str, nonce: str | None = None, t: int | None = None) -> dict:
    nonce = nonce or str(uuid.uuid4())
    t = t or int(round(time.time() * 1000))
    string_to_sign = f"{token}{t}{nonce}".encode('utf-8')
    secret_bytes = secret.encode('utf-8')
    sign = base64.b64encode(hmac.new(secret_bytes, msg=string_to_sign, digestmod=hashlib.sha256).digest()).decode('utf-8')

    headers = {
        'Authorization': token,
        'sign': sign,
        't': str(t),
        'nonce': nonce,
        'Content-Type': 'application/json; charset=utf8',
    }
    return headers


def http_get(path: str, headers: dict) -> tuple[int, dict]:
    url = BASE_URL + path
    if HAS_REQUESTS:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.status_code, resp.json() if resp.text else {}
    else:
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read()
                text = body.decode('utf-8') if body else ''
                return r.getcode(), json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode('utf-8'))
            except Exception:
                return e.code, {'message': str(e)}
        except Exception as e:
            return 0, {'message': str(e)}


def list_devices(headers: dict) -> list:
    """Return a combined list of physical devices and infrared remote devices.

    The SwitchBot `/devices` response includes `body.deviceList` and `body.infraredRemoteList`.
    This function merges both lists so callers can find virtual IR devices by name.
    """
    status, data = http_get('/devices', headers)
    if status != 100 and status not in (200,):
        # API uses statusCode inside JSON, fallback to HTTP status code
        if isinstance(data, dict) and data.get('statusCode'):
            # SwitchBot returns 100 in their body for success
            if data['statusCode'] == 100:
                body = data.get('body', {})
                devices = body.get('deviceList', []) or []
                remotes = body.get('infraredRemoteList', []) or []
                return devices + remotes
        print(f"Failed to get devices: HTTP {status} - {data.get('message', data)}", file=sys.stderr)
        return []

    # Normal response handling
    # Some endpoints return HTTP 200 with JSON body containing statusCode and body
    if isinstance(data, dict) and data.get('statusCode') == 100:
        body = data.get('body', {})
        devices = body.get('deviceList', []) or []
        remotes = body.get('infraredRemoteList', []) or []
        return devices + remotes

    # If requests returned body directly, try both keys
    if isinstance(data, dict):
        devices = data.get('deviceList', []) or []
        remotes = data.get('infraredRemoteList', []) or []
        return devices + remotes

    return []


def get_device_status(device_id: str, headers: dict) -> dict:
    status, data = http_get(f'/devices/{device_id}/status', headers)
    if status not in (200,):
        # include body message when available
        return {'error': f'HTTP {status}', 'body': data}
    return data


def pretty_print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def http_post(path: str, headers: dict, body: dict) -> tuple[int, dict]:
    url = BASE_URL + path
    data = json.dumps(body).encode('utf-8')
    headers = headers.copy()
    headers.setdefault('Content-Type', 'application/json; charset=utf8')
    if HAS_REQUESTS:
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        return resp.status_code, resp.json() if resp.text else {}
    else:
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read()
                text = body.decode('utf-8') if body else ''
                return r.getcode(), json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode('utf-8'))
            except Exception:
                return e.code, {'message': str(e)}
        except Exception as e:
            return 0, {'message': str(e)}


def send_command(device_id: str, headers: dict, command: str, parameter: str = "", command_type: str = "command") -> dict:
    body = {"command": command, "parameter": parameter, "commandType": command_type}
    status, data = http_post(f'/devices/{device_id}/commands', headers, body)
    if status not in (200,):
        return {'error': f'HTTP {status}', 'body': data}
    return data


def find_device_by_name(devices: list, name: str) -> dict | None:
    for d in devices:
        if d.get('deviceName') == name:
            return d
    return None


def control_living_room_lights(action: str, headers: dict, devices: list, names: list | None = None, brightness: int | None = None) -> dict:
    """
    Control named lights. If `names` is None, defaults to ['客厅1', '客厅2'].
    `names` should be a list of device names (exact match or substring match).

    Supported actions:
      - 'on' / 'off' : turn on/off
      - 'brightnessUp' / 'brightnessDown' : step brightness up/down (no parameter)
      - 'setBrightness' : set absolute brightness (requires `brightness` int 0-100)
    """
    allowed = {'on', 'off', 'brightnessUp', 'brightnessDown', 'setBrightness'}
    if action not in allowed:
        raise ValueError("action must be one of: 'on','off','brightnessUp','brightnessDown','setBrightness'")

    if names is None:
        names = ['客厅1', '客厅2']
    results = {}

    # validate brightness when needed
    if action == 'setBrightness':
        if brightness is None:
            raise ValueError('setBrightness requires a brightness int argument (0-100)')
        if not isinstance(brightness, int) or not (0 <= brightness <= 100):
            raise ValueError('brightness must be integer between 0 and 100')
        param_str = str(brightness)

    # mapping for simple commands
    mapping = {
        'on': 'turnOn',
        'off': 'turnOff',
        'brightnessUp': 'brightnessUp',
        'brightnessDown': 'brightnessDown',
    }

    for name in names:
        # try exact match first, then substring match for convenience
        dev = find_device_by_name(devices, name)
        if not dev:
            for d in devices:
                if name in d.get('deviceName', ''):
                    dev = d
                    break
        if not dev:
            results[name] = {'error': 'not found'}
            continue

        device_id = dev.get('deviceId')
        try:
            if action == 'setBrightness':
                results[name] = send_command(device_id, headers, 'setBrightness', param_str)
            else:
                cmd = mapping[action]
                results[name] = send_command(device_id, headers, cmd)
        except Exception as e:
            results[name] = {'error': str(e)}
    return results


def load_token_secret(path: str = r'D:\\mcp\\switchbot\\token.json'):
    try:
        with open(path, 'r', encoding='utf-8') as tf:
            td = json.load(tf)
        token = td.get('SWITCHBOT_TOKEN') or td.get('SWITCH_BOT_TOKEN')
        secret = td.get('SWITCHBOT_SECRET') or td.get('SWITCH_BOT_SECRET')
        if token and secret:
            return token, secret
        raise ValueError('Missing keys in token file')
    except Exception as e:
        print(f"Failed to read token file {path}: {e}", file=sys.stderr)
        token = os.environ.get('SWITCHBOT_TOKEN') or os.environ.get('SWITCH_BOT_TOKEN') or input('Enter your SWITCHBOT_TOKEN: ').strip()
        secret = os.environ.get('SWITCHBOT_SECRET') or os.environ.get('SWITCH_BOT_SECRET') or input('Enter your SWITCHBOT_SECRET: ').strip()
        return token, secret


def main():
    # Read token/secret from local token.json, fall back to env vars or prompt
    token, secret = load_token_secret()

    headers = make_headers(token, secret)

    # Prefer local devices list loaded at module import; fall back to API if empty
    devices = []
    if isinstance(DEVICES_LIST, dict):
        devices = DEVICES_LIST.get('devices', []) or []
    if not devices:
        print('Local devices list empty, fetching from SwitchBot API...', file=sys.stderr)
        devices = list_devices(headers)
        if not devices:
            print('No devices found or failed to retrieve devices.', file=sys.stderr)
            sys.exit(1)
        else:
            print('Fetched devices from SwitchBot API.', file=sys.stderr)

    # Simple CLI: python api.py on|off|brightnessUp|brightnessDown|setBrightness [args]
    if len(sys.argv) > 1 and sys.argv[1] in ('on', 'off', 'brightnessUp', 'brightnessDown', 'setBrightness'):
        action = sys.argv[1]
        names = None
        brightness = None
        # parse optional arguments
        if len(sys.argv) > 2:
            args = sys.argv[2:]
            # single comma-separated names
            if len(args) == 1 and ',' in args[0] and not args[0].strip().isdigit():
                names = [n.strip() for n in args[0].split(',') if n.strip()]
            else:
                # If setBrightness, try to find a numeric brightness value
                if action == 'setBrightness':
                    # try first arg as brightness
                    try:
                        brightness = int(args[0])
                        names = args[1:] or None
                    except Exception:
                        # try last arg as brightness
                        try:
                            brightness = int(args[-1])
                            names = args[:-1] or None
                        except Exception:
                            # if no numeric arg, assume entire args are names -> error later
                            names = args
                    # if names is single comma-separated string, split it
                    if names and len(names) == 1 and ',' in names[0]:
                        names = [n.strip() for n in names[0].split(',') if n.strip()]
                else:
                    names = args
        print('Using local devices list.' if isinstance(DEVICES_LIST, dict) and DEVICES_LIST.get('devices') else 'Using fetched devices list.')
        if action == 'setBrightness':
            results = control_living_room_lights(action, headers, devices, names, brightness)
        else:
            results = control_living_room_lights(action, headers, devices, names)
        pretty_print(results)
        return

    hubs = [d for d in devices if 'Hub' in d.get('deviceType', '')]
    if not hubs:
        print('No Hub devices found in your account.')
        print('Device list (first 10):')
        pretty_print(devices[:10])
        return

    print(f'Found {len(hubs)} Hub device(s).')
    for hub in hubs:
        print('\n---')
        print(f"DeviceName: {hub.get('deviceName')}")
        print(f"DeviceType: {hub.get('deviceType')}")
        print(f"DeviceId: {hub.get('deviceId')}")
        print('Fetching hub status...')
        status = get_device_status(hub.get('deviceId'), headers)
        pretty_print(status)


# Example usage: python d:\mcp\switchbot\hub2_info.py
# Test control examples:
#   python api.py on 客厅1 客厅2        # turns on '客厅1' and '客厅2'
#   python api.py off 客厅1 客厅2       # turns off '客厅1' and '客厅2'
# Or use a single comma-separated argument:
#   python api.py on 客厅1,客厅2
if __name__ == '__main__':
    main()
