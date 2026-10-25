#!/bin/bash
# ============================================================
#  微信聊天记录采集器 · 一键安装向导（macOS）
#  作用：给微信重签名 → 从微信内存提取数据库密钥 → 修正权限
#  说明：全程只在你自己电脑上进行，不联网、不上传任何数据
#  用法：在「终端」里执行
#     bash "/你的路径/wechat-messages/setup.sh"
# ============================================================

set -o pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="$DIR/wcdb-key-tool"
OUTKEYS="$TOOL/all_keys.json"
APP="/Applications/WeChat.app"

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

echo "=============================================="
echo " 微信聊天记录采集器 · 安装向导"
echo "=============================================="
echo

# ---------- 0. 环境检查 ----------
echo "【0/5】检查环境"
command -v python3 >/dev/null || { echo "  ✗ 缺少 python3"; exit 1; }
[ -d "$TOOL" ] || { echo "  ✗ 缺少 wcdb-key-tool 目录"; exit 1; }
[ -d "$APP" ] || { echo "  ✗ 未找到微信（$APP）"; exit 1; }
command -v lldb >/dev/null || echo "  ! 未检测到 lldb，微信 4.1+ 需要它：xcode-select --install"
python3 -c "import zstandard" 2>/dev/null || echo "  ! 未安装 zstandard（可选，装了才能读压缩的链接/文件标题）：pip3 install zstandard"
DBDIR=$(python3 - "$DIR" <<'PY'
import sys, glob, os
base = os.path.expanduser("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
cands = []
for d in glob.glob(os.path.join(base, "*", "db_storage")):
    msg = os.path.join(d, "message")
    if not os.path.isdir(msg):
        continue
    dbs = glob.glob(os.path.join(msg, "message_*.db"))
    if dbs:
        cands.append((max(os.path.getmtime(f) for f in dbs), d))
cands.sort(reverse=True)
print(cands[0][1] if cands else "")
PY
)
if [ -z "$DBDIR" ]; then
  echo "  ✗ 没找到微信数据库目录。请先安装并登录微信，随便收发几条消息后再试"
  exit 1
fi
echo "  ✓ 微信数据库：$DBDIR"
WXVER=$(defaults read "$APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null)
echo "  ✓ 微信版本：$WXVER"
echo

# ---------- 1. 关闭微信 ----------
echo "【1/5】关闭微信"
osascript -e 'quit app "WeChat"' >/dev/null 2>&1
sleep 2
pkill -f "MacOS/WeChat" >/dev/null 2>&1
sleep 2
if pgrep -f "MacOS/WeChat" >/dev/null 2>&1; then
  echo "  ✗ 微信仍在运行，请手动 ⌘Q 退出后重新执行"; exit 1
fi
echo "  ✓ 已退出"
echo

# ---------- 2. 重签名 ----------
echo "【2/5】给微信重新签名（去掉内存读取限制）"
echo "  下面会要求输入 Mac 登录密码，输入时不显示字符，属正常"
sudo codesign --force --deep --sign - "$APP" || { echo "  ✗ 重签失败"; exit 1; }
sudo xattr -dr com.apple.quarantine "$APP" >/dev/null 2>&1
echo "  ✓ 重签完成"
echo "  提示：想恢复微信官方签名，重新安装一次微信即可"
echo

# ---------- 3. 重新打开微信 ----------
echo "【3/5】重新打开微信"
open -a "$APP"
echo "  请等微信完全打开，确认能看到聊天列表"
echo "  如果你的微信是 4.1 及以上版本，稍后还需要【退出登录 → 重新扫码登录】一次"
echo
read -r -p "  准备好后按回车继续..." _
echo

# ---------- 4. 提取密钥 ----------
echo "【4/5】从微信内存提取数据库密钥"
cd "$TOOL" || exit 1
PID=$(pgrep -f "MacOS/WeChat$" | head -1)
[ -z "$PID" ] && { echo "  ✗ 没检测到微信进程"; exit 1; }
echo "  微信进程 PID = $PID"
sudo env HOME="$HOME" python3 wcdb_key_tool_macos.py extract \
  --db-dir "$DBDIR" --output "$OUTKEYS" --timeout 300
RC=$?
echo

# ---------- 5. 修正权限 ----------
echo "【5/5】修正权限（让采集器日后无需 sudo 即可运行）"
sudo chown -R "$(whoami)" "$HOME/.wcdb-key-tool" 2>/dev/null
sudo chown -R "$(whoami)" "$TOOL" 2>/dev/null
chmod 600 "$HOME/.wcdb-key-tool/wechat-passphrase.json" 2>/dev/null
echo "  ✓ 完成"
echo

echo "=============================================="
if [ -f "$OUTKEYS" ]; then
  N=$(python3 -c "import json;d=json.load(open('$OUTKEYS'));print(len([k for k in d if not k.startswith('_')]))" 2>/dev/null)
  echo "✅ 成功：拿到 $N 个数据库的密钥"
  echo
  echo "下一步，直接导出一次看看能不能拿到数据："
  echo "  python3 \"$DIR/wx_export.py\" --refresh --days 1 --out messages.json"
  echo "能打印出 OUTPUT_FILE 就说明整条链路通了。"
else
  echo "❌ 没拿到密钥（退出码 $RC）"
  echo "请把上面的完整输出一并反馈，便于定位问题。"
fi
echo "=============================================="
