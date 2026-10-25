#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信个人聊天记录导出工具 · 安装助手（macOS / Windows）

作用：
  1. 检查环境（微信、Python、依赖、数据库目录）
  2. 判断密钥是否已提取，指导完成初始化
  3. 打印可直接使用的导出命令

用法：
  python install.py                # 检查环境（推荐先跑这个）
  python install.py --auto         # 检查 + 自动提取密钥（仅 Windows，无需管理员权限）
  python install.py --check        # 只检查
  python install.py --json         # 机器可读输出（给 AI agent 解析）

Windows 上把 python 换成实际解释器名即可；macOS 通常是 python3。
"""
import glob
import json
import os
import platform
import shutil
import subprocess
import sys

# Windows 控制台默认 GBK，打印中文会抛 UnicodeEncodeError；统一成 UTF-8
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "wcdb-key-tool")
KEYS = os.path.join(TOOL, "all_keys.json")
EXPORTER = os.path.join(HERE, "wx_export.py")

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

sys.path.insert(0, HERE)
try:
    from wx_export import find_db_dir, XWECHAT_BASE  # noqa: E402,F401
except Exception:  # pragma: no cover
    XWECHAT_BASE = ""

    def find_db_dir():
        if not XWECHAT_BASE:
            return None
        for d in glob.glob(os.path.join(XWECHAT_BASE, "*", "db_storage")):
            msg = os.path.join(d, "message")
            if os.path.isdir(msg) and glob.glob(os.path.join(msg, "message_*.db")):
                return d
        return None


DECRYPT_TOOL = "wcdb_key_tool_windows.py" if IS_WIN else "wcdb_key_tool_macos.py"


def wechat_install_path():
    """返回微信可执行文件 / 应用路径（找不到返回空串）。"""
    if IS_WIN:
        for c in (
            r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            r"C:\Program Files\Tencent\WeChat\WeChat.exe",
            r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
            r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
        ):
            if os.path.exists(c):
                return c
        try:
            import winreg
            for key in (r"Software\Tencent\Weixin", r"Software\Tencent\WeChat"):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                        base, _ = winreg.QueryValueEx(k, "InstallPath")
                        for exe in ("Weixin.exe", "WeChat.exe"):
                            full = os.path.join(base, exe)
                            if os.path.exists(full):
                                return full
                except OSError:
                    continue
        except ImportError:
            pass
        return ""
    if IS_MAC:
        p = "/Applications/WeChat.app"
        return p if os.path.exists(p) else ""
    return ""


def wechat_version():
    if IS_MAC:
        try:
            out = subprocess.run(
                ["defaults", "read", "/Applications/WeChat.app/Contents/Info.plist",
                 "CFBundleShortVersionString"],
                capture_output=True, text=True, timeout=10)
            return (out.stdout or "").strip()
        except Exception:
            return ""
    if IS_WIN:
        exe = wechat_install_path()
        if not exe:
            return ""
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Item '{exe}').VersionInfo.FileVersion"],
                capture_output=True, text=True, timeout=15)
            return (out.stdout or "").strip()
        except Exception:
            return ""
    return ""


def wechat_running():
    try:
        if IS_WIN:
            for exe in ("Weixin.exe", "WeChat.exe"):
                r = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=10)
                if exe.lower() in (r.stdout or "").lower():
                    return True
            return False
        r = subprocess.run(["pgrep", "-f", "MacOS/WeChat"], capture_output=True, text=True)
        return bool(r.stdout.strip())
    except Exception:
        return False


def has_lldb():
    return shutil.which("lldb") is not None


def has_zstd():
    try:
        import zstandard  # noqa: F401
        return True
    except Exception:
        return False


def keys_ready():
    return os.path.exists(KEYS) and os.path.getsize(KEYS) > 10


def check():
    items = []
    ok = True

    def add(name, passed, detail, fix=""):
        nonlocal ok
        items.append({"check": name, "pass": bool(passed), "detail": detail, "fix": fix})
        if not passed:
            ok = False

    supported = IS_MAC or IS_WIN
    add("操作系统", supported, platform.system(),
        "" if supported else "目前只支持 macOS 和 Windows")

    need = (3, 10) if IS_WIN else (3, 8)
    py_ok = sys.version_info >= need
    add("Python 版本", py_ok, platform.python_version(),
        "" if py_ok else f"需要 {need[0]}.{need[1]} 及以上")

    exe = wechat_install_path()
    ver = wechat_version()
    add("微信客户端", bool(exe), (exe + ("  " + ver if ver else "")) if exe else "未检测到",
        "请先安装并登录微信桌面版")

    db = find_db_dir()
    add("微信数据库", bool(db), db or "未找到",
        "请先登录微信并收发几条消息，再重试")

    add("解密组件", os.path.isdir(TOOL), TOOL if os.path.isdir(TOOL) else "缺失",
        "目录不完整，请重新下载仓库")
    add("平台解密脚本", os.path.exists(os.path.join(TOOL, DECRYPT_TOOL)), DECRYPT_TOOL,
        "缺少当前平台的脚本，请重新下载仓库")

    if IS_MAC:
        add("lldb", has_lldb(), "已安装" if has_lldb() else "未安装",
            "微信 4.1+ 需要它：xcode-select --install")
    else:
        add("运行权限", True, "Windows 无需管理员权限、无需重签微信")

    add("zstandard", has_zstd(), "已安装" if has_zstd() else "未安装",
        "可选。不装的话链接/文件消息只有占位符：pip install zstandard")

    add("数据库密钥", keys_ready(), "已提取" if keys_ready() else "尚未提取",
        "" if keys_ready() else ("执行 --auto 自动提取（无需管理员权限）" if IS_WIN
                                 else "运行一次 setup.sh（需要管理员密码）"))

    return {
        "ok": ok,
        "platform": platform.system(),
        "ready": keys_ready() and bool(db),
        "need_setup": not keys_ready(),
        "auto_setup_available": bool(IS_WIN),
        "wechat_running": wechat_running(),
        "db_dir": db,
        "install_dir": HERE,
        "exporter": EXPORTER,
        "checks": items,
    }


def auto_extract_keys():
    """仅 Windows：直接提取密钥（不需要管理员权限）。"""
    if not IS_WIN:
        return {"ok": False,
                "message": "自动提取仅在 Windows 上可用；macOS 请运行 setup.sh（需要管理员密码）"}
    db = find_db_dir()
    if not db:
        return {"ok": False, "message": "没找到微信数据库，请先登录微信"}
    if not wechat_running():
        return {"ok": False, "message": "微信没在运行，请先打开并登录微信再执行"}
    cmd = [sys.executable, os.path.join(TOOL, DECRYPT_TOOL),
           "extract", "--db-dir", db, "--output", KEYS]
    try:
        r = subprocess.run(cmd, cwd=TOOL, capture_output=True, text=True, timeout=600)
    except Exception as e:
        return {"ok": False, "message": f"执行失败：{e}"}
    tail = ((r.stdout or "") + (r.stderr or ""))[-600:]
    ok = keys_ready()
    return {"ok": ok, "returncode": r.returncode, "output": tail,
            "message": "密钥提取成功" if ok else "密钥提取失败，请把 output 一并反馈"}


def main():
    args = sys.argv[1:]
    want_json = "--json" in args
    do_auto = "--auto" in args

    auto_result = auto_extract_keys() if do_auto else None
    report = check()
    if auto_result is not None:
        report["auto_extract"] = auto_result
        report = check()

    py = "python" if IS_WIN else "python3"
    export_cmd = f'{py} "{EXPORTER}" --refresh --days 7 --out messages.json'

    if want_json:
        report["export_command"] = export_cmd
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 1

    print("=" * 54)
    print(" 微信个人聊天记录导出工具 · 环境检查")
    print("=" * 54)
    for it in report["checks"]:
        print(f" {'✓' if it['pass'] else '✗'} {it['check']}: {it['detail']}")
        if not it["pass"] and it["fix"]:
            print(f"     → {it['fix']}")
    print()

    if auto_result is not None:
        print(("✅ " if auto_result["ok"] else "❌ ") + auto_result["message"])
        if not auto_result["ok"] and auto_result.get("output"):
            print("   输出尾部：", auto_result["output"][-300:])
        print()

    if report["ready"]:
        print("✅ 环境就绪，可以开始导出：")
        print(f"   {export_cmd}")
        print()
        print("   参数说明：")
        print("     --days N            导出最近 N 天（默认 7）")
        print("     --out FILE          输出文件（默认写到系统临时目录 messages.json）")
        print("     --since TS          从指定 Unix 时间戳开始")
        print("     --include-official  连公众号/系统通知一起导出")
        print("     --max-per-chat N    单个会话最多导出条数（默认 300）")
    elif report["need_setup"]:
        if IS_WIN:
            print("⚠️  还差一步：提取数据库密钥（Windows 不需要管理员权限）")
            print(f'   {py} "{os.path.join(HERE, "install.py")}" --auto')
        else:
            print("⚠️  还差一步：提取数据库密钥（需要管理员密码，请在终端手动执行）")
            print(f'   bash "{os.path.join(HERE, "setup.sh")}"')
    else:
        print("⚠️  环境未就绪，请按上面的提示逐项处理")
    print("=" * 54)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
