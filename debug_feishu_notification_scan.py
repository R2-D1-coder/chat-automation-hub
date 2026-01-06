"""
调试脚本：扫描当前桌面上的小窗口，尝试解析“飞书通知弹窗/Windows Toast”的文本。

用法：
  1) 先运行：python debug_feishu_notification_scan.py
  2) 看到提示后，在 20 秒内触发一条飞书桌面通知（右下角弹窗）
  3) 脚本会打印匹配到的窗口信息与解析到的 texts，便于定位为何监听没命中
"""

import time
import ctypes
from ctypes import wintypes

from src.core.config import load_config
from src.adapters.feishu_monitor import HAS_UIAUTOMATION, auto, check_if_notification_window

user32 = ctypes.windll.user32


def enum_windows() -> list[int]:
    hwnds: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return hwnds


def get_rect(hwnd: int):
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return rect


def main():
    if not HAS_UIAUTOMATION:
        raise SystemExit("uiautomation 未安装：pip install uiautomation")

    cfg = load_config().get("feishu_monitor", {}) or {}
    monitor_groups = cfg.get("monitor_groups")
    print("请在 20 秒内触发一条飞书桌面通知（右下角弹窗）...")
    print(f"monitor_groups={monitor_groups}")

    deadline = time.time() + 20
    seen = set()

    with auto.UIAutomationInitializerInThread():
        while time.time() < deadline:
            for hwnd in enum_windows():
                if hwnd in seen:
                    continue
                if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
                    continue
                rect = get_rect(hwnd)
                if not rect:
                    continue
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 0 or height <= 0 or width >= 900 or height >= 450:
                    continue

                info = check_if_notification_window(wintypes.HWND(hwnd), monitor_groups)
                if not info:
                    continue

                seen.add(hwnd)
                print("==== MATCH ====")
                print(f"hwnd={hwnd}")
                print(f"class={info.get('class_name')}")
                print(f"name={info.get('name')}")
                print(f"size={info.get('size')}")
                print("texts=")
                for t in info.get("texts", []):
                    print(f"  - {t}")
                print("===============")

            time.sleep(0.2)

    print("扫描结束：未匹配到窗口（可能通知弹窗不可被 UIAutomation 访问，或弹窗不是小窗口）。")


if __name__ == "__main__":
    main()

