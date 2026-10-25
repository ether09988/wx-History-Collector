# 微信聊天记录采集器（WeChat Chat History Collector）

[English](README.en.md) | 简体中文

把你自己微信里的**私聊和群聊文字消息**导出成干净、结构化的 JSON，供任何 AI agent、分析脚本或知识库工具读取。

纯本地运行：**不联网、不上传、不需要登录任何第三方服务**。所有解密和导出都在你自己的机器上完成。

> **你是 AI agent？** 直接读 [`AGENT.md`](AGENT.md) —— 那里有完整的能力清单、
> 任务映射和参数表，你可以替用户完成全部操作，用户不需要打开终端。
>
> 这是 [**Financial-data-Collectors**](https://github.com/ether09988/Financial-data-Collectors) 系列的第 1 个采集器。
> 系列索引里有全部采集器的清单。

---

## 能导出什么

| 会导出 | 不会导出 |
|---|---|
| 私聊、群聊的文字消息（含发送人、时间、会话名） | 公众号推送、系统通知（默认过滤，可开） |
| 链接、文件、引用消息的**标题** | 文件正文本身 |
| **完整通讯录**：好友、群、公众号（含从没聊过天的人） | — |
| 图片/表情/语音/视频：记 `[image]`、`[emoji]` 等占位类型 | 图片、语音的实际内容 |

### 平台支持

| 平台 | 状态 | 初始化方式 |
|---|---|---|
| macOS 11+ | ✅ 已实测 | 需要给微信重签名一次（要管理员密码） |
| Windows 10/11 | ✅ 已实测 | **不需要管理员权限、不需要改微信**，一条命令自动提取 |
| Linux | ❌ 未适配 | 解密组件理论支持，本项目未做适配 |

> **关于 SIP（系统完整性保护）—— 实测结论**
>
> **首次提取密钥时必须关闭 SIP。** 这是 macOS 上的硬性前提，不是可选项。
>
> 实测过程：SIP 开启状态下，提密钥工具以 root 身份运行时**读不到微信的容器目录**
> （macOS 的 TCC 会在 SIP 开启时拦截 root 访问用户数据目录），报错
> 「未找到可解密的 .db 文件」。关闭 SIP 后，同一台机器、同一版本微信，提取成功。
>
> 注意：被拦的不是「读微信进程内存」，而是「root 访问你的用户目录」。
> 某些教程说「SIP 只保护系统进程，与微信无关」，理论上没错，但我们的实现需要 root 读文件，
> 所以实际还是绕不过这一关。
>
> **提取完成后，建议把 SIP 重新开启。** 日常解密只用缓存的口令，
> 不以 root 身份读文件、也不碰进程内存 —— 实测 SIP 开启状态下导出完全正常。
>
> 完整流程：
>
> ```
> ① 关闭 SIP（重启进恢复模式 → csrutil disable → 重启）   ← 只有这一次
> ② 运行 setup-gui.sh 或 setup.sh 提取密钥
> ③ 重新开启 SIP（可选但建议：csrutil enable → 重启）
> ④ 之后一直正常使用，SIP 开着也不影响
> ```
>
> Windows 用户不受影响：那边不需要管理员权限，也不需要动任何系统安全设置。
---

## 快速开始

### 第一步：准备

**通用要求**

- 微信桌面版 4.x，**已登录并保持运行**（要读它的进程内存）
- 建议装 `zstandard`，否则链接/文件消息只能拿到占位符
  - macOS：`pip3 install zstandard --break-system-packages`
  - Windows：`pip install zstandard`

**macOS 额外要求**

- Python 3.8+
- Xcode 命令行工具（提供 `lldb`）：`xcode-select --install`

**Windows 额外要求**

- **Python 3.10+**（解密组件用到 3.10 语法）
- 无需 `lldb`、无需管理员权限

### 第二步：初始化（只需一次）

**Windows**

```powershell
python install.py          # 先看环境检查
python install.py --auto   # 自动提取密钥（微信保持登录状态）
```

**macOS**

```bash
python3 install.py         # 先看环境检查
bash setup-gui.sh          # 图形化初始化：全程系统弹窗，不用碰命令行
# 或用 bash setup.sh        # 终端版（等价）
```

> 两个脚本做同一件事，区别只是收密码的方式：
> `setup-gui.sh` 用 macOS 系统弹窗（已实测通过，全程不用碰命令行），
> `setup.sh` 在终端里提示。

> macOS 为什么需要重签微信：macOS 不允许普通程序读其他进程内存（Hardened Runtime），
> 重签只是去掉这个限制，读完密钥就结束。想恢复官方签名，**重新安装一次微信**即可。
>
> 微信 4.1+ 在这条路径上还需要你在微信里「退出登录 → 重新登录」一次——
> 新版微信只在登录那一刻计算密钥。

**macOS 权限要求（三个必须满足的条件，否则会失败）**

1. **必须在本机「终端」App 里运行** `setup.sh`。
   不要在 SSH 远程会话里跑——远程会话拿不到 macOS 的 TCC 授权，`task_for_pid` 会被拒绝。
2. **终端需要有「完全磁盘访问」权限**，否则重签会报 `Operation not permitted`。
   路径：系统设置 → 隐私与安全性 → 完全磁盘访问 → 添加「终端」并勾选，然后**重启终端**。
3. **重签必须真的生效**。跑完 `setup.sh` 后可以自己验证：

   ```bash
   codesign -dv --verbose=2 /Applications/WeChat.app 2>&1 | grep flags
   ```

   应显示 `flags=0x2(adhoc)`。如果还是 `flags=0x10000(runtime)`，说明重签没成功，
   回去检查第 2 条的完全磁盘访问权限。

> 关于 SIP 的完整说明见本文开头「平台支持」下方。

### 第三步：导出

```bash
# macOS
python3 wx_export.py --refresh --days 7 --out messages.json

# Windows
python wx_export.py --refresh --days 7 --out messages.json
```

成功会打印类似这样的两行：

```
OUTPUT_FILE: /绝对路径/messages.json
导出 1287 条消息，涉及 73 个会话
```

> **上面的条数和会话数是示例，每个人都不一样。** 它取决于你的聊天量、`--days` 取多少天、
> 单个会话是否触到 `--max-per-chat` 上限、以及是否包含公众号。
> 判断成功的标准只有一个：**打印出了 `OUTPUT_FILE` 那一行，且条数大于 0**。
> 数字大小不代表成功或失败。

### 出问题先跑自检

```bash
python3 wx_export.py --doctor
```

它会逐项检查并告诉你该修哪一项：

```
 ✓ 微信进程: 运行中
 ✓ 微信签名状态: 已重签为 ad-hoc（可读进程内存）
 ℹ SIP: 已开启（正常状态）
 ✓ 微信数据库: /Users/xxx/.../db_storage
 ✓ 数据库密钥: 已提取
 ✓ 解密库: /var/folders/.../wechat_export_cache
```

失败时会给出具体的修复命令和排查顺序，不用猜。

### 私聊和群聊分开导出

```bash
python3 wx_export.py --refresh --days 7 --split --out messages.json
```

会生成两个文件，并分别打印路径：

```
OUTPUT_FILE: /绝对路径/messages_private.json     ← 私聊
OUTPUT_FILE: /绝对路径/messages_group.json       ← 群聊
```

如果你要喂给 agent，分开调用更省 token——只处理关心的那一类。

### 第四步（可选）：导出通讯录

不想导聊天记录，只想拿到联系人名单：

```bash
python3 wx_export.py --contacts --refresh --out contacts.json
```

默认导出的范围**与微信「我 → 设置 → 通讯录管理」页面显示的数量一致**：

| 本工具 `type` | 微信里的名称 |
|---|---|
| `friend` | 联系人 |
| `group` | 群聊（已保存到通讯录的） |
| `wecom` | 企业微信联系人 |
| `official` | 公众号 |
| `service` | 服务号 |
| `enterprise` | 我的企业 |

加 `--contacts-scope all` 会额外导出：未保存到通讯录的群、历史关注过但已不在通讯录的公众号、
非好友缓存（群成员、加过没通过的人）、系统号 —— 数量会大一个量级。

每条记录包含：

| 字段 | 说明 |
|---|---|
| `wxid` | 账号唯一 ID |
| `name` | 显示名（备注 > 昵称 > 自定义微信号 > wxid） |
| `remark` | 你给他设的备注 |
| `nickname` | 他自己的微信昵称 |
| `alias` | 自定义微信号（他设置的那个，可能为空） |
| `type` | 见上表；`all` 模式下还会出现 `group_unsaved`（未保存的群）/ `official_other`（历史公众号）/ `stranger`（非好友）/ `system`（系统号） |
| `deleted` | 是否已删除 |

> ⚠️ 通讯录和聊天记录一样，只写在本机。**这份文件包含你全部社交关系，不要提交、不要上传。**

---

## 输出格式

输出是一个 JSON 数组，每个元素一条消息：

```json
[
  {
    "id": "wxmsg-3f2a1b8c9d0e4f5a",
    "data": {
      "chat_id": "12345678@chatroom",
      "chat_name": "某个群名",
      "chat_type": "group",
      "msg_id": "12345678@chatroom:12345",
      "time": "2026-10-18T09:15:03+08:00",
      "ts": 1792289703,
      "sender": "张三",
      "type": "text",
      "text": "消息正文，最长 800 字"
    }
  }
]
```

| 字段 | 说明 |
|---|---|
| `chat_id` | 会话唯一 ID（群是 `xxx@chatroom`，私聊是 wxid 或自定义号） |
| `chat_name` | 会话显示名（备注优先，其次昵称） |
| `chat_type` | `group` 群聊 / `private` 私聊 / `official` 公众号 |
| `msg_id` | 消息唯一 ID，可用于增量去重 |
| `time` | RFC3339 带时区 |
| `sender` | 发送人显示名 |
| `type` | `text` / `image` / `emoji` / `video` / `app` / `system` 等 |
| `text` | 正文；非文本消息为占位符或提取到的标题 |

---

## 命令行参数

```
python wx_export.py [选项]

  --refresh            先刷新解密库（推荐，能拿到最新消息）
  --days N             导出最近 N 天（默认 7）
  --since TS           从指定 Unix 时间戳开始（覆盖 --days）
  --out FILE           输出文件路径（默认写到系统临时目录 messages.json）
  --emit-events        输出 [{id,data}] 事件数组格式 + 打印 OUTPUT_FILE
  --max-per-chat N     单个会话最多导出条数（默认 300）
  --include-official   包含公众号与系统通知
  --decrypted DIR      指定解密库目录（配合外部解密流程时用）
  --stat               只统计不写文件

  # 通讯录
  --jsonl              按 JSONL 输出（每行一条，适合超大文件）；默认是 JSON 数组
  --split              私聊与群聊分别写成两个文件（<out>_private.json / <out>_group.json）
  --doctor             自检：检查微信签名/密钥/解密库/进程并给出修复建议

  --contacts           导出通讯录（好友/群/公众号），而不是聊天消息
  --contacts-scope     addressbook（默认，与微信「通讯录管理」一致）
                       或 all（含未保存的群、历史公众号、非好友缓存、系统号）
```

---

## 接入 AI Agent

导出结果是纯 JSON，任何能读文件的东西都能用。两种常见接法：

**1. 一次性喂给 agent**

```bash
python wx_export.py --refresh --days 1 --out today.json
# 然后把 today.json 作为上下文交给 agent
```

**2. 作为周期性数据源**

在 agent 或调度器里配置一条定时任务，执行：

```bash
python wx_export.py --refresh --days 1 --emit-events --out events.json
```

工具会打印 `OUTPUT_FILE: <路径>`，你的程序读这一行拿到文件位置即可。
事件里的 `msg_id` 是稳定的，方便你做增量去重：只处理上次之后新出现的消息。

**给 AI agent 的说明**：仓库里的 [`AGENT.md`](AGENT.md) 是写给 agent 的能力手册——
能做什么、用户说什么该执行什么命令、输出字段怎么用、出错怎么自愈，
以及红线（不许替用户输密码、不许伪造成功、不能发消息）。
把那个文件丢给你的 agent 就够了。

---

## 项目结构

```
WeChat-Chat-Collector/
├── README.md               本说明（中文）
├── README.en.md            英文说明
├── AGENT.md                给 AI agent 的能力手册（安装+使用+排障）
├── WINDOWS-TEST.md         Windows 支持说明与排障
├── install.py              环境检查 + 密钥提取（Windows 自动）
├── setup.sh                仅 macOS：密钥提取初始化
├── wx_export.py            核心：解密 → 解析 → 导出 JSON
├── LICENSE                 本项目许可（MIT）
├── NOTICE                  第三方组件声明
└── wcdb-key-tool/          第三方解密组件（见 NOTICE）
    ├── wcdb_key_tool_macos.py
    ├── wcdb_key_tool_windows.py
    ├── wcdb_key_tool.py
    └── LICENSE
```

安装后会在本机生成这些私有文件（已在 `.gitignore` 中排除，**不要提交**）：

- `wcdb-key-tool/all_keys.json` —— 各数据库的密钥
- `~/.wcdb-key-tool/wechat-passphrase.json` —— 登录口令缓存（权限 600）

---

## 隐私与安全

- **全程本地**：不联网、不上传、不经过任何服务器。代码里没有任何网络请求，你可以自己 `grep` 验证。
- **解密快照是临时的**：写到系统临时目录，每次导出覆盖，不在文档目录长期留存。
- **只读**：不修改微信数据库，不发送消息，不碰网络协议。
- **密钥敏感**：`all_keys.json` 和 `wechat-passphrase.json` 等于你聊天记录的钥匙，
  不要提交、不要分享、不要传网盘。

---

## 常见问题

**Q：会把我的数据传到哪吗？**
A：不会。代码里没有任何网络请求。

**Q：微信升级后还能用吗？**
A：解密组件可能需要重跑一次初始化。macOS 上微信升级会还原签名，重跑 `setup.sh` 即可。

**Q：需要关闭 SIP 吗？**
**首次提取密钥时需要，之后可以开回来。** 详见本文开头「关于 SIP」一节。

实测：SIP 开启状态下，提密钥工具以 root 运行读不到微信容器目录（被 TCC 拦截），
报「未找到可解密的 .db 文件」；关闭 SIP 后同一环境提取成功。
提取完成后用缓存口令解密，SIP 开着也完全正常。
**Q：为什么 macOS 要重签微信？**
A：macOS 不允许普通进程读其他进程内存，这是系统级限制（Hardened Runtime）。重签去掉这个标志，
是代价最小的做法。想恢复官方签名，重新安装一次微信即可。

**Q：`codesign` 报 `Operation not permitted` 怎么办？**
A：终端没有「完全磁盘访问」权限，改不了 `/Applications` 下的 App。
去 系统设置 → 隐私与安全性 → 完全磁盘访问 → 添加「终端」，然后完全退出终端再重开，重跑 `setup.sh`。

**Q：可以在 SSH / 远程会话里跑 `setup.sh` 吗？**
A：**不行。** macOS 的调试授权（TCC）绑定在本机图形界面的终端应用上，SSH 会话的父进程是 sshd，
拿不到这个授权，`task_for_pid` 一定失败。请在本机打开「终端」执行。

**Q：怎么确认重签成功了？**
A：`codesign -dv --verbose=2 /Applications/WeChat.app 2>&1 | grep flags`
应显示 `flags=0x2(adhoc)`；显示 `flags=0x10000(runtime)` 就是没成功。

**Q：读出来的图片是空的？**
A：微信的图片是加密 `.dat` 文件，本工具只记 `[image]` 占位类型，不解析图片内容。

**Q：导出的消息不全？**
A：微信本地只保留它在你这台机器上收发的消息。手机上的完整历史需要先用微信的
「聊天记录迁移」功能同步到电脑。

**Q：会不会导致账号异常？**
A：工具只读取本地数据库和进程内存，不修改微信任何行为、不碰它的网络通信，
理论上不会。但 macOS 上重签微信属于修改第三方程序，腾讯是否判定为异常，
本项目无法保证，风险由使用者自行评估。

---

## 系列中的其他采集器

| 采集器 | 状态 |
|---|---|
| 微信聊天记录（本仓库） | ✅ 可用 |
| QQ 聊天记录 | 🚧 规划中 |
| 同花顺自选 / 持仓 | 🚧 规划中 |
| 券商交易记录 | 🚧 规划中 |

完整列表与说明见 [**Financial-data-Collectors**](https://github.com/ether09988/Financial-data-Collectors)。

---

## 许可

本项目原创部分（`wx_export.py`、`install.py`、`setup.sh`、文档）采用 **MIT License**，
版权归 © 2026 ether09988。

`wcdb-key-tool/` 为第三方开源组件，遵循其原有 MIT 许可，版权归原作者所有，
详见 [`NOTICE`](NOTICE) 与 `wcdb-key-tool/LICENSE`。

## 免责声明

本工具仅供**导出你自己设备上、你自己账号**的聊天记录，用于个人数据备份与分析。

- 请勿用于获取他人聊天记录
- 请遵守你所在地区的法律法规与微信服务条款
- 使用本工具产生的任何后果由使用者自行承担

本工具不含任何协议逆向、不绕过任何服务端限制，只读取你本机已有的数据。
