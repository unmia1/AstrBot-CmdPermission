# AstrBot-CmdPermission

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.0-blue)](https://github.com/AstrBotDevs/AstrBot)
[![version](https://img.shields.io/badge/version-1.0.0-green)](https://github.com/unmia1/AstrBot-Wusound/releases)
[![license](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

一个指令权限拦截插件 —— 无需改动任何现有插件源码，即可在可视化配置界面里指定哪些插件的指令（`/` 开头）只允许管理员使用。

## 功能

- 在 WebUI「插件配置」页面里填写插件名，即可让该插件的所有指令只允许管理员（或群管理员）触发
- 也可额外指定具体指令名做精确限制
- 非管理员触发受限指令会被自动拦截（可选择是否回复「无权限」提示）
- 完全复用 AstrBot 内置的权限过滤器，不侵入其他插件，卸载即恢复原状

## 安装

把本仓库导入 AstrBot 插件市场，或直接把 `main.py`、`metadata.yaml`、`_conf_schema.json` 放到插件目录即可。

## 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `target_plugins` | 列表 | 要限制的插件名列表，填插件的 `name` 或 `display_name`（例如悟声插件填 `astrbot_plugin_wusound_tts` 或 `悟声语音合成`）。留空则不按插件限制 |
| `target_commands` | 列表 | 额外要限制的具体指令名（精确匹配，不含 `/` 前缀，例如 `点歌`）。留空则只按插件名限制 |
| `permission_type` | 下拉 | `admin`（仅 AstrBot 管理员）/ `group_admin`（群管理员也可用） |
| `reply_no_permission` | 开关 | 被拦截时是否回复「无权限」提示 |

## 使用步骤

1. 安装并启用本插件
2. 打开 WebUI → 插件 → 本插件 → 配置
3. 在 `target_plugins` 里填入要限制的插件名（多个用逗号/逐个添加）
4. 保存并重启本插件
5. 之后非管理员发对应指令会被拦截，管理员（WebUI「管理员 ID」列表里的 QQ 号）正常使用

## 原理

AstrBot 所有插件指令最终都会注册到全局 `star_handlers_registry`，每个指令 handler 带一个 `event_filters` 过滤器链。本插件在 AstrBot 加载完成后遍历这些 handler，对命中的指令在最前面插入 `PermissionTypeFilter(ADMIN)`，该过滤器复用 AstrBot 内置的 `event.is_admin()` 判断。

## License

[MIT](LICENSE) © unmia1
