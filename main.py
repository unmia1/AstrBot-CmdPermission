"""指令权限拦截插件（Cmd Permission）

无需改动任何现有插件源码，即可在可视化配置界面里指定哪些插件的
指令（/ 开头）只允许管理员使用。

项目地址：https://github.com/unmia1/AstrBot-CmdPermission
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.star import star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)
from astrbot.core.star.filter.permission import PermissionType, PermissionTypeFilter
from astrbot.core.star.filter.command import CommandFilter


def _norm(s: Any) -> str:
    """把任意值规整成小写、去空白后的字符串，用于模糊匹配。"""
    return str(s or "").strip().lower()


def _to_set(value: Any) -> set[str]:
    """把配置里的 list / 逗号分隔字符串统一转成小写字符串集合。"""
    if value is None:
        return set()
    if isinstance(value, str):
        parts = [p for p in value.replace("，", ",").split(",") if p.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = []
    return {_norm(p) for p in parts if _norm(p)}


class CmdPermissionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        # config 允许为 None：当插件目录缺失 _conf_schema.json（例如从
        # GitHub 导入时漏传）时，AstrBot 会以单参数实例化，这里兜底。
        if config is not None:
            self.cfg: AstrBotConfig = config
        else:
            try:
                from astrbot.api.star import StarTools

                data_dir = StarTools.get_data_dir()
            except Exception:  # noqa: BLE001
                data_dir = None
            if data_dir:
                from pathlib import Path

                fallback = Path(data_dir) / "astrbot_plugin_cmd_permission_fallback.json"
            else:
                import tempfile
                import os

                fallback = os.path.join(
                    tempfile.gettempdir(), "astrbot_plugin_cmd_permission_fallback.json"
                )
            self.cfg = AstrBotConfig(config_path=str(fallback), schema={})

        self._applied: set[str] = set()  # 已经插入过过滤器的 handler_full_name

    # ---------------------------------------------------------------- 配置

    @property
    def target_plugins(self) -> set[str]:
        return _to_set(self.cfg.get("target_plugins", []))

    @property
    def target_commands(self) -> set[str]:
        return _to_set(self.cfg.get("target_commands", []))

    @property
    def permission_type(self) -> str:
        return _norm(self.cfg.get("permission_type", "admin")) or "admin"

    @property
    def reply_no_permission(self) -> bool:
        return bool(self.cfg.get("reply_no_permission", True))

    def _resolve_perm(self) -> PermissionType:
        return (
            PermissionType.GROUP_ADMIN
            if self.permission_type == "group_admin"
            else PermissionType.ADMIN
        )

    # ---------------------------------------------------------------- 匹配

    def _plugin_names_of(self, handler: StarHandlerMetadata) -> set[str]:
        """返回该 handler 所属插件的全部候选名（name / display_name / 目录名）。"""
        meta = star_map.get(handler.handler_module_path)
        names: set[str] = set()
        if meta is not None:
            names.add(_norm(meta.name))
            names.add(_norm(meta.display_name))
            names.add(_norm(meta.root_dir_name))
        # 兜底：从模块路径最后一段推断目录名
        if handler.handler_module_path:
            names.add(_norm(handler.handler_module_path.rsplit(".", 1)[-1]))
        return {n for n in names if n}

    def _command_names_of(self, handler: StarHandlerMetadata) -> set[str]:
        """返回该 handler 所有指令名（含别名、父指令组合）的小写集合。"""
        names: set[str] = set()
        for f in handler.event_filters:
            if isinstance(f, CommandFilter):
                for full in f.get_complete_command_names():
                    names.add(_norm(full))
                    # 也把首段（去掉父指令前缀）加进去，方便精确匹配
                    names.add(_norm(full.split(" ", 1)[0]))
        return {n for n in names if n}

    def _should_restrict(self, handler: StarHandlerMetadata) -> bool:
        """判断某个指令 handler 是否应被限制。"""
        plugin_names = self._plugin_names_of(handler)
        if self.target_plugins & plugin_names:
            return True
        if self.target_commands:
            cmd_names = self._command_names_of(handler)
            if self.target_commands & cmd_names:
                return True
        return False

    # ---------------------------------------------------------------- 应用

    def _apply(self) -> None:
        target_plugins = self.target_plugins
        target_commands = self.target_commands
        if not target_plugins and not target_commands:
            logger.info(
                "[cmd_permission] 未配置目标插件/指令，跳过拦截。"
                "请在 WebUI 插件配置里填写 target_plugins 或 target_commands。"
            )
            return

        perm = self._resolve_perm()
        applied_count = 0
        for handler in star_handlers_registry:
            # 只处理「适配器消息事件」且确实是指令（带 CommandFilter）的 handler
            if handler.event_type != EventType.AdapterMessageEvent:
                continue
            if not any(isinstance(f, CommandFilter) for f in handler.event_filters):
                continue
            # 不要拦截本插件自己（虽然本插件没有指令，双保险）
            if handler.handler_module_path == self.__class__.__module__:
                continue
            if not self._should_restrict(handler):
                continue

            # 若已经插过同级别过滤器，跳过，避免重复
            if handler.handler_full_name in self._applied:
                continue
            if any(
                isinstance(f, PermissionTypeFilter) and f.permission_type == perm
                for f in handler.event_filters
            ):
                self._applied.add(handler.handler_full_name)
                continue

            handler.event_filters.insert(
                0,
                PermissionTypeFilter(perm, raise_error=self.reply_no_permission),
            )
            self._applied.add(handler.handler_full_name)
            applied_count += 1
            logger.info(
                f"[cmd_permission] 已限制指令：{handler.handler_full_name}"
                f"（插件 {handler.handler_module_path}，级别 {self.permission_type}）"
            )

        logger.info(f"[cmd_permission] 本次共限制 {applied_count} 个指令。")

    # ---------------------------------------------------------------- 钩子

    async def initialize(self) -> None:
        """插件每次加载/激活时都会调用（含运行中重启）。

        由于插件是按目录名顺序逐个加载的，本插件（astrbot_plugin_cmd_permission）
        通常排在其他业务插件（如 astrbot_plugin_wusound_tts）之前，此时那些插件的
        指令还没注册到 star_handlers_registry。因此这里创建后台任务，稍作延迟、
        让出事件循环，等所有插件加载完成后再注入，避免漏匹配。
        """
        self._schedule_apply(delay=1.0)

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self) -> None:
        """AstrBot 冷启动完成时的兜底（此时所有插件都已加载）。"""
        self._schedule_apply(delay=0.0)

    def _schedule_apply(self, delay: float) -> None:
        """幂等地调度一次注入（不阻塞加载流程）。"""

        async def _run() -> None:
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                self._apply()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"[cmd_permission] 注入权限过滤器失败：{exc!r}", exc_info=True
                )

        try:
            loop = asyncio.get_event_loop()
            loop.create_task(_run())
        except Exception:  # noqa: BLE001
            try:
                asyncio.create_task(_run())
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[cmd_permission] 无法调度注入任务：{exc!r}")

    async def terminate(self) -> None:
        """卸载时移除本插件插入的过滤器，恢复原状。"""
        perm = self._resolve_perm()
        removed = 0
        for handler in star_handlers_registry:
            to_remove = [
                f
                for f in handler.event_filters
                if isinstance(f, PermissionTypeFilter) and f.permission_type == perm
            ]
            # 只移除本插件插入的（记录在 _applied 里）
            if handler.handler_full_name not in self._applied:
                continue
            for f in to_remove:
                if f in handler.event_filters:
                    handler.event_filters.remove(f)
                    removed += 1
        self._applied.clear()
        if removed:
            logger.info(f"[cmd_permission] 已移除 {removed} 个权限过滤器。")
