---
name: uv venv
description: 在 Windows PowerShell 中一行激活位于 D:\uv_venv 下的虚拟环境并提供列举与帮助命令。
tags: [powershell, venv, utility]
---

# uv venv — Agent Skill

## 概要
本 Skill 提供关于 `uv.ps1` 的说明和交互示例，便于代理（或用户）以一致方式列出并激活位于 `D:\uv_venv` 下的 Python 虚拟环境。

## 能力（Capabilities）
- 列出所有位于 `D:\uv_venv` 的虚拟环境。 ✅
- 指导用户在当前 PowerShell 会话中激活指定名称的虚拟环境（或在用户同意下，在终端执行激活命令）。 ✅
- 提供帮助与常见故障排查建议（如执行策略问题）。 ✅

## 用法（Usage）
- 列出环境：
  `./uv.ps1 -List`
- 激活环境：
  `./uv.ps1 <环境名>`  （例如：`./uv.ps1 myenv`）
- 帮助：
  `./uv.ps1 -Help`

> 注意：请在 PowerShell 中运行脚本。要在当前 PowerShell 会话内保留激活，建议使用 `.\uv.ps1 <环境名>` 或 `& .\uv.ps1 <环境名>`（由终端执行器决定）。

## 参数（Parameters）
- <环境名>：要激活的虚拟环境目录名称（位于 `D:\uv_venv\<环境名>`）。
- `-List`：列出 `D:\uv_venv` 下所有目录名。
- `-Help`：显示帮助信息。

## 示例对话（Examples）
- 用户："帮我激活名为 `dev` 的虚拟环境。"
  - Agent：检查 `D:\uv_venv\dev` 是否存在；若存在，提示用户在 PowerShell 中运行：
    `.\uv.ps1 dev`；或若用户允许，可在当前终端执行激活命令。

- 用户："列出可用的虚拟环境"
  - Agent：运行 `./uv.ps1 -List` 并返回列出的环境名称。

## 故障排查（Troubleshooting）
- 如果出现“脚本被禁止”错误：运行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force`。
- 如果找不到 `Activate.ps1`：请确认该环境是使用 `python -m venv` 或 `virtualenv` 创建，并存在 `Scripts\Activate.ps1`。

## 实现位置（Implementation）
脚本路径：`D:\mcp\uv.ps1`（仓库根目录下）。

## 代理行为建议（Agent Behavior）
1. 接到激活请求时，先询问或验证环境名称。若环境不存在，给出错误提示并列举可用环境。
2. 对于同意由代理在用户终端执行命令的情形，使用 PowerShell 终端在用户会话中运行 `& 'D:\mcp\uv.ps1' <环境名>`（注意：在某些终端中，外部进程无法改变父 PowerShell 会话的环境，代理应在运行前说明此限制）。
3. 在不能在当前会话内激活时，明确告知用户如何手动运行命令以获得持久激活。

---

如需，我可以把示例对话转换为自动化测试或为 agent 编写交互式提示模板。