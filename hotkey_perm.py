"""macOS「输入监控」权限：检测 + 一键申请 / 跳转设置（剪贴板监听 + 全局 hotkey 都需要）。"""
from __future__ import annotations

import subprocess


def input_monitor_granted() -> bool:
    """addGlobalMonitor 非 None 即表示已授权。"""
    try:
        import AppKit

        mon = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskKeyDown,
            lambda _e: None,
        )
        if mon is None:
            return False
        AppKit.NSEvent.removeMonitor_(mon)
        return True
    except Exception:
        return False


def input_monitor_status() -> dict:
    granted = input_monitor_granted()
    return {
        "ok": True,
        "granted": granted,
        "hint_app": "Skillless",
    }


def open_input_monitoring_settings() -> dict:
    """尽量深链到「隐私与安全性 → 输入监控」。"""
    urls = [
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ListenEvent",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    ]
    for url in urls:
        try:
            r = subprocess.run(["open", url], capture_output=True, timeout=8)
            if r.returncode == 0:
                return {"ok": True, "url": url}
        except Exception:
            continue
    try:
        subprocess.run(
            ["open", "-b", "com.apple.systempreferences", "/System/Library/PreferencePanes/Security.prefPane"],
            check=False,
            timeout=8,
        )
        return {"ok": True, "url": "Security.prefPane"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def request_input_monitor_access() -> dict:
    """一键申请：先弹系统授权，再打开输入监控设置页。

    说明：macOS 不允许 App 自动勾选，用户需在设置里打开开关；
    本函数负责把用户送到正确页面并触发系统提示。
    """
    try:
        from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess

        if CGPreflightListenEventAccess():
            return {"ok": True, "granted": True, "action": "already"}

        # 可能弹出系统提示，或把 Skillless 加入待授权列表
        CGRequestListenEventAccess()
        if CGPreflightListenEventAccess():
            return {"ok": True, "granted": True, "action": "requested"}

        opened = open_input_monitoring_settings()
        return {
            "ok": True,
            "granted": False,
            "action": "opened_settings",
            "settings": opened,
            "message": "请在列表里打开 Skillless 开关",
        }
    except Exception as e:
        opened = open_input_monitoring_settings()
        return {
            "ok": True,
            "granted": False,
            "action": "fallback_settings",
            "settings": opened,
            "error": str(e)[:120],
            "message": "请在列表里打开 Skillless 开关",
        }
