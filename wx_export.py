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
    ap.add_argument("--emit-events", action="store_true",
                    help="输出 [{id,data}] 事件数组，并在结束时打印 OUTPUT_FILE 路径")
    ap.add_argument("--since", type=int, default=0, help="起始 unix 时间戳（覆盖 --days）")
    ap.add_argument("--contacts", action="store_true",
                    help="导出通讯录（联系人/群/公众号），而不是聊天消息")
    ap.add_argument("--contacts-scope", default="addressbook", choices=["addressbook", "all"],
                    help="通讯录范围：addressbook=好友+群+企业微信（默认）；all=全部（含公众号/非好友/系统号）")
    args = ap.parse_args()

    if args.refresh:
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
            if args.emit_events:
                args.out = os.path.join(tempfile.gettempdir(), "wechat_messages.json")
            else:
                print("[ERROR] 需要 --out 或 --stat", file=sys.stderr)
                sys.exit(2)
        if not args.emit_events:
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
            if out_fh:
                out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            elif args.emit_events:
                eid = "wxmsg-" + hashlib.md5(
                    f"{username}:{local_id}".encode()).hexdigest()[:20]
                events.append({"id": eid, "data": rec})
        per_chat.append((chat_name, n))

    if out_fh:
        out_fh.close()
    if args.emit_events:
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
