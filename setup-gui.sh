#!/bin/bash
# ============================================================
#  macOS 图形化初始化 —— 不需要用户打开终端
#
#  与 setup.sh 的区别：全程通过 macOS 系统弹窗收集管理员密码，
#  用户只需要点几下「好」、输一次密码，不用跟命令行打交道。
#  适合由 AI agent 调用。
#
#  已在 macOS + 微信 4.1.10 实测通过：关微信 → 弹密码框重签 → 重开微信 →
#  再弹密码框提密钥 → 31 个库中成功解出 30 个，全程无需碰命令行。
#
#  如果失败，请改用 setup.sh（在终端里执行）。
# ============================================================

set -o pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$DIR/wcdb-key-tool"
APP="/Applications/WeChat.app"
KEYS="$TOOL/all_keys.json"

say() { osascript -e "display dialog \"$1\" buttons {\"好\"} default button 1 with title \"微信聊天记录导出\"" >/dev/null 2>&1; }

# ---------- 0. 必须在图形界面里 ----------
if ! osascript -e 'return 1' >/dev/null 2>&1; then
  echo "[ERROR] 当前不在 macOS 图形界面会话中，无法弹窗。请改用 setup.sh（终端执行）。"
  exit 1
fi

# ---------- 0. 前置检查：SIP 与已有密钥 ----------
# 实测：SIP 开启时，以 root 运行的提密钥工具读不到微信容器目录（TCC 拦截），
# 报「未找到可解密的 .db 文件」。这里提前拦下来，别让用户白跑一遍关微信、重签。
HAS_PASS=0
[ -s "$HOME/.wcdb-key-tool/wechat-passphrase.json" ] && HAS_PASS=1
[ -s "$KEYS" ] && HAS_PASS=1
if [ "$HAS_PASS" = "0" ] && csrutil status 2>/dev/null | grep -q "enabled"; then
  echo "[ERROR] 首次提取密钥前必须先关闭 SIP。"
  echo "        SIP 开启时，提密钥工具以 root 运行会被系统拦截，读不到微信数据目录。"
  echo ""
  echo "        步骤："
  echo "          1. 重启并按住 ⌘R 进入恢复模式"
  echo "          2. 菜单「实用工具」→「终端」"
  echo "          3. 执行：csrutil disable"
  echo "          4. 重启后重新运行本脚本"
  echo ""
  echo "        提取成功后可以再把 SIP 开回来（csrutil enable），日常使用不受影响。"
  say "首次提取密钥需要先关闭 SIP。\n\n重启按住 ⌘R 进恢复模式 → 实用工具 → 终端 →\n输入 csrutil disable → 重启后重试。\n\n（提取成功后可以再把 SIP 开回来，不影响使用）"
  exit 1
fi
if [ "$HAS_PASS" = "1" ]; then
  echo "  （检测到已有密钥，跳过 SIP 检查——复用缓存口令不需要 root 读文件）"
fi

echo "【1/4】关闭微信"
# 用 pkill 直接结束进程，不用 osascript 控制微信。
# 原因：osascript 的 "quit app" 需要 macOS「自动化」隐私授权，
# 未授权时会失败并返回 -128（用户已取消），而 pkill 不需要任何授权。
pkill -f "MacOS/WeChat" >/dev/null 2>&1
for _ in 1 2 3 4 5 6 7 8 9 10; do
  pgrep -f "MacOS/WeChat" >/dev/null 2>&1 || break
  sleep 1
done
if pgrep -f "MacOS/WeChat" >/dev/null 2>&1; then
  say "微信没能自动退出，请手动 ⌘Q 退出微信后，重新运行本脚本。"
  echo "[ERROR] 微信仍在运行"
  exit 1
fi
echo "  ✓ 已退出"

# ---------- 2. 弹窗获取管理员授权，重签微信 ----------
echo "【2/4】请求授权并给微信重新签名（会弹出系统密码框）"
osascript <<'EOS'
do shell script "/usr/bin/codesign --force --deep --sign - /Applications/WeChat.app" with administrator privileges with prompt "需要给微信重新签名，才能读取它的数据库密钥（只需这一次）"
EOS
if [ $? -ne 0 ]; then
  say "重签失败或被取消。可以改用 setup.sh 在终端里执行。"
  echo "[ERROR] codesign 未成功"
  exit 1
fi
say "微信已重新签名完成。"
echo "  ✓ 重签完成"

# ---------- 3. 打开微信，等用户确认 ----------
echo "【3/4】打开微信"
open -a "$APP"
WXVER=$(defaults read "$APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null)
osascript <<EOS
display dialog "微信已重新打开（版本 $WXVER）。

请等它加载完、确认能看到聊天列表。

如果你的微信是 4.1 及以上，还需要在微信里「设置 → 退出登录 → 重新扫码登录」一次（新版只在登录那一刻计算密钥）。

完成后点「继续」。" buttons {"继续"} default button 1 with title "微信聊天记录导出"
EOS
if [ $? -ne 0 ]; then echo "[INFO] 用户取消"; exit 1; fi

# ---------- 4. 弹窗获取授权，提取密钥 ----------
echo "【4/4】再次请求授权，提取数据库密钥（会弹出系统密码框，可能需要等 1~3 分钟）"
DBDIR=$(python3 - "$DIR" <<'PY'
import sys, glob, os
base = os.path.expanduser("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
cands = []
for d in glob.glob(os.path.join(base, "*", "db_storage")):
    msg = os.path.join(d, "message")
    if os.path.isdir(msg) and glob.glob(os.path.join(msg, "message_*.db")):
        cands.append(d)
print(cands[0] if cands else "")
PY
)
if [ -z "$DBDIR" ]; then
  say "没找到微信数据库。请先登录微信、随便收发几条消息后再试。"
  exit 1
fi

osascript <<EOS
do shell script "cd '$TOOL' && /usr/bin/python3 wcdb_key_tool_macos.py extract --db-dir '$DBDIR' --output '$KEYS' --timeout 300" with administrator privileges with prompt "需要读取微信进程内存来提取数据库密钥（只读取，不修改微信）"
EOS
RC=$?

if [ -f "$KEYS" ] && [ -s "$KEYS" ]; then
  N=$(python3 -c "import json;d=json.load(open('$KEYS'));print(len([k for k in d if not k.startswith('_')]))" 2>/dev/null)
  say "✅ 初始化完成：已获得 $N 个数据库的密钥。

之后就可以正常导出聊天记录了。"
  echo "  ✓ 密钥已保存（$N 个库）"
  exit 0
else
  say "密钥提取没有成功（退出码 $RC）。

可以改用 setup.sh 在终端里重试，或把这次的输出发给 AI 助手诊断。"
  echo "[ERROR] 密钥提取失败，退出码 $RC"
  exit 1
fi
