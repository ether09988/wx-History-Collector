#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信个人聊天记录导出器
把本机微信加密数据库中的私聊/群聊消息导出为标准 JSON 事件数组，
供任意 AI agent、分析脚本或知识库工具读取。
从已解密的微信 4.x 数据库中导出指定时间范围内的聊天消息为 JSONL。

用法：
  python3 wx_export.py --days 7 --out /path/chat.jsonl       # 导出最近 7 天
  python3 wx_export.py --days 7 --stat                        # 只统计不导出
  python3 wx_export.py --days 7 --out x.jsonl --include-official  # 含公众号
"""
import argparse
import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta

# Windows 控制台默认 GBK，打印中文会抛 UnicodeEncodeError；统一成 UTF-8
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

try:
    import zstandard as _zstd
except Exception:
    _zstd = None

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def decompress(raw, ct):
    """微信 4.x 的 message_content 可能被 zstd 压缩（WCDB_CT=4）。"""
    if raw is None:
        return ""
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw)
    raw = bytes(raw)
    need = (ct == 4) or raw[:4] == ZSTD_MAGIC
    if need and _zstd is not None:
        try:
            return _zstd.ZstdDecompressor().decompress(
                raw, max_output_size=4 << 20).decode("utf-8", "ignore")
        except Exception:
            return ""
    return raw.decode("utf-8", "ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
DECRYPTED = os.path.join(HERE, "out", "decrypted")
WXTOOL = os.path.join(HERE, "wcdb-key-tool")
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

MAC_BASE = os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
)


def _win_xwechat_base():
    """Windows: 从 %APPDATA%\\Tencent\\xwechat\\config\\*.ini 读出数据根目录。"""
    import glob
    appdata = os.environ.get("APPDATA", "")
    cfg = os.path.join(appdata, "Tencent", "xwechat", "config")
    roots = []
    if os.path.isdir(cfg):
        for ini in glob.glob(os.path.join(cfg, "*.ini")):
            content = None
            for enc in ("utf-8", "gbk", "utf-16"):
                try:
                    with open(ini, encoding=enc) as f:
                        content = f.read(1024).strip()
                    break
                except (UnicodeDecodeError, UnicodeError, OSError):
                    continue
            if content and os.path.isdir(content):
                roots.append(content)
    for r in roots:
        cand = os.path.join(r, "xwechat_files")
        if os.path.isdir(cand):
            return cand
    for cand in (os.path.expanduser("~/Documents/xwechat_files"),
                 os.path.expanduser("~/Documents/WeChat Files")):
        if os.path.isdir(cand):
            return cand
    return ""


XWECHAT_BASE = _win_xwechat_base() if IS_WIN else MAC_BASE


def find_db_dir():
    """自动定位当前微信账号的 db_storage（多个账号时取消息库最新的那个）。"""
    import glob
    if not XWECHAT_BASE:
        return None
    cands = []
    for d in glob.glob(os.path.join(XWECHAT_BASE, "*", "db_storage")):
        msg = os.path.join(d, "message")
        if not os.path.isdir(msg):
            continue
        dbs = glob.glob(os.path.join(msg, "message_*.db"))
        if not dbs:
            continue
        cands.append((max(os.path.getmtime(f) for f in dbs), d))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]
TMP_DECRYPTED = os.path.join(tempfile.gettempdir(), "wechat_export_cache")
KEYS_PATH = os.path.join(WXTOOL, "all_keys.json")
CST = timezone(timedelta(hours=8))

TYPE_NAMES = {
    1: "text", 3: "image", 34: "voice", 37: "friend", 42: "card", 43: "video",
    47: "emoji", 48: "location", 49: "app", 50: "call", 10000: "system",
    10002: "system", 10003: "system",
}


def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def open_db(path):
    if not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except Exception:
        return None


def load_names(ddir):
    """username -> 显示名"""
    names = {}
    con = open_db(os.path.join(ddir, "contact", "contact.db"))
    if con:
        try:
            for username, nick, remark in con.execute(
                "select username, nick_name, remark from contact"
            ):
                if not username:
                    continue
                names[username] = (remark or "").strip() or (nick or "").strip() or username
        except Exception:
            pass
        con.close()
    return names


def load_sessions(ddir):
    """返回 [(username, last_timestamp, summary)]"""
    out = []
    con = open_db(os.path.join(ddir, "session", "session.db"))
    if con:
        try:
            for row in con.execute(
                "select username, last_timestamp, summary from SessionTable"
            ):
                if row[0]:
                    out.append((row[0], int(row[1] or 0), row[2] or ""))
        except Exception:
            pass
        con.close()
    return out


def index_msg_tables(ddir):
    """表名 -> (db 路径, 是否 biz)"""
    idx = {}
    mdir = os.path.join(ddir, "message")
    if not os.path.isdir(mdir):
        return idx
    for fn in sorted(os.listdir(mdir)):
        if not fn.endswith(".db") or not re.match(r"^(message|biz_message)_\d+\.db$", fn):
            continue
        path = os.path.join(mdir, fn)
        con = open_db(path)
        if not con:
            continue
        try:
            for (t,) in con.execute(
                "select name from sqlite_master where type='table' and name like 'Msg_%'"
            ):
                idx[t] = path
        except Exception:
            pass
        con.close()
    return idx


def classify(username: str):
    if username.endswith("@chatroom"):
        return "group"
    if username.startswith("gh_") or username in ("brandsessionholder", "floatbottle", "medianote") or username.endswith("@placeholder_foldgroup"):
        return "official"
    return "private"


LOCK_FILE = os.path.join(tempfile.gettempdir(), "wechat_export.lock")
LOCK_STALE_SECONDS = 1800     # 超过 30 分钟视为残留锁
LOCK_WAIT_SECONDS = 300       # 等待其他采集结束，最多 5 分钟


def acquire_lock(wait_seconds: int = LOCK_WAIT_SECONDS):
    """采集互斥锁。

    同一台机器上可能同时有「手动触发」和「定时任务」两路采集在跑，
    它们共用同一个解密目录和输出文件，会互相删掉对方的中间产物。
    这里用 O_EXCL 建锁文件做互斥：后来的等待，等到就继续，等不到就报错退出。
    """
    deadline = time.time() + wait_seconds
    waited = False
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            if waited:
                print("[lock] 上一次采集已结束，本次继续", file=sys.stderr)
            return True
        except FileExistsError:
            # 残留锁（进程崩溃/被 kill）自动清理
            try:
                age = time.time() - os.path.getmtime(LOCK_FILE)
                if age > LOCK_STALE_SECONDS:
                    print(f"[lock] 清理残留锁（{int(age)}s 未释放）", file=sys.stderr)
                    os.unlink(LOCK_FILE)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                print("[lock] 另一路采集仍在运行，等待超时。请稍后重试；"
                      "若是残留锁，可删除 " + LOCK_FILE, file=sys.stderr)
                return False
            if not waited:
                print("[lock] 检测到另一路采集正在运行，排队等待…", file=sys.stderr)
                waited = True
            time.sleep(3)


def release_lock():
    try:
        os.unlink(LOCK_FILE)
    except OSError:
        pass


def refresh_decrypted(out_dir: str) -> bool:
    """先刷新解密库到临时目录（无需 sudo，口令已缓存在用户目录）。"""
    import shutil
    try:
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        print(f"[refresh] 准备目录失败: {e}", file=sys.stderr)
        return False
    db_dir = find_db_dir()
    if not db_dir:
        print("[refresh] 没找到微信数据库目录，请确认微信已安装并登录过", file=sys.stderr)
        return False
    tool_name = "wcdb_key_tool_windows.py" if IS_WIN else "wcdb_key_tool_macos.py"
    script = os.path.join(WXTOOL, tool_name)
    keys = os.path.join(WXTOOL, "all_keys.json")
    if not os.path.exists(script):
        print(f"[refresh] 找不到解密脚本: {script}", file=sys.stderr)
        return False
    if not os.path.exists(keys):
        print(f"[refresh] 找不到密钥文件: {keys}", file=sys.stderr)
        return False
    try:
        r = subprocess.run(
            [sys.executable, script, "decrypt", "--db-dir", db_dir,
             "--keys", keys, "--output", out_dir],
            cwd=WXTOOL, capture_output=True, text=True, timeout=900,
        )
    except Exception as e:
        print(f"[refresh] 执行解密失败: {e}", file=sys.stderr)
        return False
    tail = ((r.stdout or "") + (r.stderr or ""))[-500:].strip()
    print(f"[refresh] rc={r.returncode} {tail}", file=sys.stderr)
    ok = os.path.isdir(os.path.join(out_dir, "message"))
    if not ok:
        print("[refresh] 解密未产出 message 目录", file=sys.stderr)
    return ok


# 微信内置的系统号 / 服务号，不属于「联系人」
SYSTEM_ACCOUNTS = {
    "filehelper", "medianote", "floatbottle", "weixin", "weibo", "qqmail", "qqsafe",
    "fmessage", "notifymessage", "qmessage", "tmessage", "brandsessionholder",
    "officialaccounts", "mphelper", "weixinreminder", "notification_messages",
    "newsapp", "appbrandcustomerservicemsg", "weixinpay", "weixinclear",
    "exmail_tool", "shake", "qqfriend", "linkedin", "tmessage", "voip",
}


CONTACT_TYPE_ORDER = {"friend": 0, "group": 1, "wecom": 2, "official": 3,
                       "service": 4, "enterprise": 5, "official_other": 6,
                       "group_unsaved": 7, "stranger": 8, "openim_other": 9,
                       "other": 10, "system": 11}

# 微信「通讯录」里实际会显示的类别（对齐 App 内「通讯录管理」页面）
ADDRESSBOOK_TYPES = {"friend", "group", "wecom", "official", "service", "enterprise"}


def export_contacts(ddir: str, scope: str = "addressbook"):
    """导出通讯录。

    scope:
      addressbook（默认）—— 与微信「通讯录管理」页面一致：
                            联系人 + 群聊 + 企业微信 + 公众号/服务号/我的企业
      all                —— 全部记录：再加未保存到通讯录的群、陌生人缓存、系统号
    """
    con = open_db(os.path.join(ddir, "contact", "contact.db"))
    if con is None:
        print("[ERROR] 找不到 contact.db，无法导出通讯录", file=sys.stderr)
        return None, None
    try:
        # biz_info.type 用来区分 公众号(0) / 服务号(1) / 我的企业(2) / 其他(3)
        rows = con.execute(
            "select c.username, c.nick_name, c.remark, c.alias, c.local_type, "
            "       c.delete_flag, b.type "
            "from contact c left join biz_info b on c.username = b.username"
        ).fetchall()
    except Exception as e:
        print(f"[ERROR] 读取通讯录失败: {e}", file=sys.stderr)
        con.close()
        return None, None
    con.close()

    stats = {}
    events = []
    for username, nick, remark, alias, lt, deleted, biz_type in rows:
        if not username:
            continue
        ctype = classify_contact(username, int(lt or 0),
                                 int(biz_type) if biz_type is not None else None)
        stats[ctype] = stats.get(ctype, 0) + 1
        if scope != "all" and ctype not in ADDRESSBOOK_TYPES:
            continue
        remark = (remark or "").strip()
        nick = (nick or "").strip()
        alias = (alias or "").strip()
        name = remark or nick or alias or username
        events.append({
            "id": "wxcontact-" + hashlib.md5(username.encode()).hexdigest()[:20],
            "data": {
                "wxid": username,
                "name": name,
                "remark": remark,
                "nickname": nick,
                "alias": alias,
                "type": ctype,
                "deleted": bool(deleted),
            },
        })
    events.sort(key=lambda e: (CONTACT_TYPE_ORDER.get(e["data"]["type"], 9), e["data"]["name"]))
    return events, stats


def classify_contact(username: str, local_type: int, biz_type: int = None) -> str:
    """把一条 contact 记录归类。

    判据全部来自实测比对微信「通讯录管理」页面：
      - 群聊 283  ⇔  local_type=1 且 username 以 @chatroom 结尾（未保存的群 local_type 不是 1）
      - 我的企业 3 ⇔  local_type=1 且 biz_info.type=2
      - 企业微信 25 ⇔  local_type=5
      - 公众号/服务号 ⇔ biz_info.type 为 0 / 1
    注意：[不可用] local_type=0 判断公众号——那个值里混着上千个真人账号。
    """
    u = (username or "").lower()
    if not u:
        return "other"

    # 群：保存到通讯录的群 local_type=1；其余（未保存）是别的值
    if u.endswith("@chatroom") or u.endswith("@im.chatroom"):
        return "group" if local_type == 1 else "group_unsaved"

    if u.endswith("@openim"):
        return "wecom" if local_type == 5 else "openim_other"

    if u.endswith("@placeholder_foldgroup") or u.endswith("@placeholder_stickyfooter"):
        return "system"
    if u in SYSTEM_ACCOUNTS:
        return "system"

    # 公众号类：只有 local_type=1 的才在「通讯录」里；
    # 其余是历史上关注过/浏览过、已不在通讯录的公众号
    if u.startswith("gh_"):
        if local_type != 1:
            return "official_other"
        if biz_type == 0:
            return "official"     # 公众号（订阅号）
        if biz_type == 1:
            return "service"      # 服务号
        if biz_type == 2:
            return "enterprise"   # 我的企业
        return "official_other"

    if local_type == 1:
        return "friend"
    if local_type in (0, 3):
        return "stranger"         # 非好友：群成员、加过未通过、已删好友
    return "other"


def _wechat_running() -> bool:
    try:
        if IS_WIN:
            for exe in ("Weixin.exe", "WeChat.exe"):
                r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}",
                                    "/FO", "CSV", "/NH"],
                                   capture_output=True, text=True, timeout=10)
                if exe.lower() in (r.stdout or "").lower():
                    return True
            return False
        r = subprocess.run(["pgrep", "-f", "MacOS/WeChat"], capture_output=True, text=True)
        return bool(r.stdout.strip())
    except Exception:
        return False


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def wechat_signature_state():
    """返回 (状态, 说明)。状态：adhoc / runtime / missing / unknown"""
    if not IS_WIN and not os.path.exists("/Applications/WeChat.app"):
        return "missing", "未找到 /Applications/WeChat.app"
    if IS_WIN:
        return "n/a", "Windows 不使用代码签名方案"
    r = _run(["codesign", "-dv", "--verbose=2", "/Applications/WeChat.app"])
    out = ((r.stderr or "") + (r.stdout or "")) if r else ""
    if "flags=0x2(adhoc)" in out:
        return "adhoc", "已重签为 ad-hoc（可读进程内存）"
    if "runtime" in out:
        return "runtime", "仍是官方签名（带 Hardened Runtime，需要重签）"
    return "unknown", "无法判断签名状态"


def sip_state():
    if IS_WIN:
        return "n/a", "Windows 无 SIP"
    r = _run(["csrutil", "status"])
    out = ((r.stdout or "") + (r.stderr or "")).strip() if r else ""
    if "enabled" in out and "disabled" not in out:
        return "enabled", "SIP 已开启（正常状态）"
    if "disabled" in out:
        return "disabled", "SIP 已关闭（不影响本工具，但会降低系统安全性）"
    return "unknown", out or "无法读取 SIP 状态"


def doctor(ddir=None):
    """自检：逐项检查前置条件，并在失败时给出可执行的修复建议。"""
    ok_all = True
    print("=" * 56)
    print(" 微信聊天记录导出 · 自检")
    print("=" * 56)

    def line(passed, name, detail, fix=""):
        nonlocal ok_all
        mark = "✓" if passed else "✗"
        print(f" {mark} {name}: {detail}")
        if not passed:
            ok_all = False
            if fix:
                for ln in fix.strip().split("\n"):
                    print(f"     → {ln}")

    # 1. 平台
    line(IS_MAC or IS_WIN, "操作系统", platform.system(),
         "目前只支持 macOS 和 Windows" if not (IS_MAC or IS_WIN) else "")

    # 2. 微信是否在运行
    running = _wechat_running()
    line(running, "微信进程", "运行中" if running else "未检测到",
         "打开微信并登录后重试（取密钥需要读它的进程内存）")

    # 3. 微信签名（仅 macOS，这是最常见的失败原因）
    if IS_MAC:
        state, desc = wechat_signature_state()
        line(state == "adhoc", "微信签名状态", desc,
             "微信升级会还原官方签名，导致无法读取密钥。重新执行一次：\n"
             "  bash setup.sh\n"
             "（如果一直报 Operation not permitted，先给「终端」授予\n"
             "  系统设置 → 隐私与安全性 → 完全磁盘访问 权限，再完全退出终端重开）")

    # 4. SIP（信息性，不作为失败判据）
    sip, sip_desc = sip_state()
    print(f" ℹ SIP: {sip_desc}")
    if sip == "enabled":
        print("     （本工具不需要关闭 SIP；若首次取密钥失败，见文末排查顺序）")

    # 5. 数据库目录
    db = find_db_dir()
    line(bool(db), "微信数据库", db or "未找到",
         "先登录微信并收发几条消息，再重试")

    # 6. 密钥文件
    keys_ok = os.path.exists(KEYS_PATH) and os.path.getsize(KEYS_PATH) > 10
    line(keys_ok, "数据库密钥", "已提取" if keys_ok else "未提取",
         "首次使用需要提取一次密钥：\n"
         "  macOS  ：bash setup.sh\n"
         "  Windows：python install.py --auto")

    # 7. 解密库
    if ddir is None:
        ddir = TMP_DECRYPTED if os.path.isdir(TMP_DECRYPTED) else None
    dec_ok = bool(ddir and os.path.isdir(os.path.join(ddir, "message")))
    line(dec_ok, "解密库", ddir or "尚未生成",
         "加上 --refresh 参数会自动解密：\n"
         "  python wx_export.py --refresh --days 7 --out messages.json")

    print("-" * 56)
    if ok_all:
        print(" ✅ 全部就绪，可以导出")
    else:
        print(" ⚠️ 有项目未通过，按上面的 → 提示处理")
        print()
        print(" 【仍然失败时的排查顺序】")
        print("   1. 确认微信已登录且没有退出（取密钥要读进程内存）")
        print("   2. macOS：确认微信签名已是 adhoc（见上）")
        print("   3. macOS：把「终端」加入 完全磁盘访问，并完全退出终端重开")
        print("   4. 重跑一次 setup.sh / install.py --auto")
        print("   5. 若仍失败，提 issue 并附上本文输出（不含聊天内容）")
    print("=" * 56)
    return 0 if ok_all else 1


def base_type(local_type: int) -> int:
    """微信 4.x 的 local_type 是 64 位：低 32 位是消息类型，高位是子类型。"""
    return int(local_type) & 0xFFFFFFFF


def extract_text(local_type: int, content):
    if content is None:
        return ""
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8", "ignore")
        except Exception:
            return "[二进制内容]"
    content = str(content)
    local_type = base_type(local_type)
    if local_type == 1:
        return content
    # 49 = app 消息（链接/文件/引用/小程序…），从 XML 里抠标题
    if local_type == 49:
        t = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", content, re.S) or \
            re.search(r"<title>(.*?)</title>", content, re.S)
        f = re.search(r'title="(.*?)"', content)
        d = re.search(r"<des><!\[CDATA\[(.*?)\]\]></des>", content, re.S)
        parts = []
        if t:
            parts.append(t.group(1).strip())
        if f and (not t or f.group(1).strip() not in parts):
            parts.append(f.group(1).strip())
        if d:
            parts.append(d.group(1).strip()[:200])
        if parts:
            return " | ".join(parts)
    name = TYPE_NAMES.get(local_type)
    if name and name != "text":
        return f"[{name}]"
    return f"[type={local_type}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="导出最近 N 天（默认 7）")
    ap.add_argument("--out", help="输出 JSONL 路径")
    ap.add_argument("--stat", action="store_true", help="只统计，不写文件")
    ap.add_argument("--include-official", action="store_true", help="包含公众号/系统会话")
    ap.add_argument("--max-per-chat", type=int, default=300, help="每个会话最多导出条数")
    ap.add_argument("--decrypted", default=DECRYPTED, help="解密库目录")
    ap.add_argument("--refresh", action="store_true",
                    help="先自动刷新解密库（输出到系统临时目录，无需 sudo）")
    ap.add_argument("--doctor", action="store_true",
                    help="自检：检查微信签名/密钥/解密库/进程，并给出修复建议")
    ap.add_argument("--split", action="store_true",
                    help="把私聊与群聊分别写入两个文件（<out>_private.json / <out>_group.json）")
    ap.add_argument("--emit-events", action="store_true",
                    help="输出 [{id,data}] 事件数组，并在结束时打印 OUTPUT_FILE 路径")
    ap.add_argument("--since", type=int, default=0, help="起始 unix 时间戳（覆盖 --days）")
    ap.add_argument("--contacts", action="store_true",
                    help="导出通讯录（联系人/群/公众号），而不是聊天消息")
    ap.add_argument("--contacts-scope", default="addressbook", choices=["addressbook", "all"],
                    help="通讯录范围：addressbook=好友+群+企业微信（默认）；all=全部（含公众号/非好友/系统号）")
    args = ap.parse_args()

    if args.doctor:
        sys.exit(doctor(None if args.decrypted == DECRYPTED else args.decrypted))

    if args.refresh:
        # 互斥：防止「手动触发」与「定时任务」同时跑，互相删掉对方的中间产物
        if not acquire_lock():
            sys.exit(4)
        import atexit
        atexit.register(release_lock)
        if not refresh_decrypted(TMP_DECRYPTED):
            print("[ERROR] 解密库刷新失败", file=sys.stderr)
            sys.exit(3)
        args.decrypted = TMP_DECRYPTED

    if args.contacts:
        ddir = args.decrypted
        if not os.path.isdir(os.path.join(ddir, "contact")):
            print(f"[ERROR] 找不到解密后的 contact 目录: {ddir}/contact", file=sys.stderr)
            print("        首次使用请加上 --refresh 参数（会先自动解密）", file=sys.stderr)
            sys.exit(2)
        out_path = args.out or os.path.join(tempfile.gettempdir(), "wechat_contacts.json")
        events, stats = export_contacts(ddir, args.contacts_scope)
        if events is None:
            sys.exit(2)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False)
        print(f"OUTPUT_FILE: {os.path.abspath(out_path)}")
        brief = ", ".join(f"{k}={v}" for k, v in sorted(stats.items(), key=lambda x: -x[1]))
        print(f"导出 {len(events)} 个联系人条目（库内合计: {brief}）", file=sys.stderr)
        return

    ddir = args.decrypted
    if not os.path.isdir(os.path.join(ddir, "message")):
        print(f"[ERROR] 找不到解密后的数据库目录: {ddir}", file=sys.stderr)
        print("        首次使用请加上 --refresh 参数（会先自动解密）：", file=sys.stderr)
        print("          python3 wx_export.py --refresh --days 7 --out messages.json",
              file=sys.stderr)
        print("        若还没提取过密钥，请先运行 install.py 或 setup.sh", file=sys.stderr)
        sys.exit(2)

    cutoff = args.since if args.since else int(time.time()) - args.days * 86400

    names = load_names(ddir)
    sessions = load_sessions(ddir)
    tindex = index_msg_tables(ddir)

    total = 0
    chats_hit = 0
    per_chat = []
    out_fh = None
    events = []
    if not args.stat:
        if not args.out:
            if args.emit_events or args.split:
                args.out = os.path.join(
                    tempfile.gettempdir(), f"wechat_messages_{os.getpid()}.json")
            else:
                print("[ERROR] 需要 --out 或 --stat", file=sys.stderr)
                sys.exit(2)
        if not (args.emit_events or args.split):
            out_fh = open(args.out, "w", encoding="utf-8")

    for username, last_ts, summary in sessions:
        ts_sec = last_ts / 1000 if last_ts > 10 ** 11 else last_ts
        if ts_sec < cutoff:
            continue
        kind = classify(username)
        if kind == "official" and not args.include_official:
            continue
        tname = "Msg_" + md5_hex(username)
        db_path = tindex.get(tname)
        if not db_path:
            continue

        con = open_db(db_path)
        if not con:
            continue
        # sender 映射
        id2wx = {}
        try:
            for rid, uname, _s in con.execute("select rowid, user_name, is_session from name2id"):
                id2wx[rid] = uname
        except Exception:
            pass

        try:
            rows = con.execute(
                f"select local_id, real_sender_id, create_time, local_type, "
                f"message_content, WCDB_CT_message_content "
                f"from {tname} where create_time >= ? order by create_time desc limit ?",
                (cutoff, args.max_per_chat),
            ).fetchall()
        except Exception:
            con.close()
            continue
        con.close()

        if not rows:
            continue
        chats_hit += 1
        chat_name = names.get(username) or username
        n = 0
        for row in rows:
            local_id, sender_id, ctime, ltype, content, ct = (list(row) + [0] * 6)[:6]
            content = decompress(content, ct)
            ctime = int(ctime or 0)
            if ctime <= 0:
                continue
            sender_wxid = id2wx.get(sender_id, "")
            sender = names.get(sender_wxid) or sender_wxid or ("我" if not sender_id else "未知")
            text = extract_text(int(ltype or 0), content)
            bt = base_type(int(ltype or 0))
            if not text:
                text = "[空]"
            text = text.replace("\n", " ").strip()[:800]
            rec = {
                "chat_id": username,
                "chat_name": chat_name,
                "chat_type": kind,
                "msg_id": f"{username}:{local_id}",
                "time": datetime.fromtimestamp(ctime, CST).isoformat(),
                "ts": ctime,
                "sender": sender,
                "type": TYPE_NAMES.get(bt, str(bt)),
                "text": text,
            }
            total += 1
            n += 1
            eid = "wxmsg-" + hashlib.md5(
                f"{username}:{local_id}".encode()).hexdigest()[:20]
            item = {"id": eid, "data": rec}
            if out_fh:
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            else:
                events.append(item)
        per_chat.append((chat_name, n))

    if out_fh:
        out_fh.close()
    if args.split:
        # 私聊与群聊分开写两个文件，方便 agent 分别调用
        base, ext = os.path.splitext(args.out)
        ext = ext or ".json"
        buckets = {"private": [], "group": []}
        for e in events:
            ct = e["data"].get("chat_type")
            buckets["group" if ct == "group" else "private"].append(e)
        for tag in ("private", "group"):
            path = f"{base}_{tag}{ext}"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(buckets[tag], f, ensure_ascii=False)
            print(f"OUTPUT_FILE: {os.path.abspath(path)}")
        print(f"导出 私聊 {len(buckets['private'])} 条 / 群聊 {len(buckets['group'])} 条，"
              f"涉及 {chats_hit} 个会话", file=sys.stderr)
    elif args.emit_events:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False)
        print(f"OUTPUT_FILE: {os.path.abspath(args.out)}")
        print(f"导出 {len(events)} 条事件，涉及 {chats_hit} 个会话", file=sys.stderr)
    per_chat.sort(key=lambda x: -x[1])
    print(json.dumps({
        "cutoff": datetime.fromtimestamp(cutoff, CST).isoformat(),
        "days": args.days,
        "chats": chats_hit,
        "messages": total,
        "out": args.out,
        "top_chats": [{"chat": c, "n": n} for c, n in per_chat[:8]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
