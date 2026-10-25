# AGENT.md —— 给 AI Agent 的能力手册

> **这份文件是写给 AI agent 的。** 用户会把仓库地址或本文件丢给你，说一句"帮我把微信聊天记录导出来"。
> 你按这里的说明，可以**替用户完成全部操作**——用户不需要打开终端、不需要记命令。

---

## 一句话定位

把本机微信的**聊天记录**和**通讯录**导出成 JSON 文件，供你（agent）读取、分析、建索引。

全程本地运行：不联网、不上传。你读到的就是用户自己的数据。

---

## 一、你能替用户做什么

| 用户说 | 你执行 | 产出文件 |
|---|---|---|
| "导出我的微信聊天记录" | `--refresh --days 7 --out messages.json` | 一个 JSON 数组 |
| "私聊和群聊分开给我" | 加 `--split` | `messages_private.json` + `messages_group.json` |
| "只要群里聊的" | `--split` 后只读 `_group.json` | — |
| "导出通讯录 / 好友列表" | `--contacts` | `contacts.json` |
| "最近 N 天聊了什么" | `--days N` | — |
| "只看某个时间段" | `--since <unix 时间戳>` | — |
| "帮我看看为什么用不了" | `--doctor` | 诊断报告（不是文件） |
| "这个群最近在聊什么" | 先导出，再按 `chat_name` 过滤 | — |

**所有命令都不需要用户参与**（除了下面说的首次设置）。

---

## 二、首次设置（只有一次）

### 先检查环境，不要直接开干

```bash
python3 install.py          # Windows: python install.py
```

它会告诉你：微信有没有装、数据库能不能找到、密钥提没提取、缺什么。

### 如果提示"数据库密钥未提取"

这是唯一需要**分平台处理**的地方：

| 平台 | 你能否自己做 | 怎么做 |
|---|---|---|
| **Windows** | ✅ 完全自动，不需要管理员权限 | `python install.py --auto` |
| **macOS** | ⚠️ 能代跑，但需要用户输一次密码 | **优先** `bash setup-gui.sh` —— 全程用系统弹窗收密码，用户不用碰命令行；失败再回退 `bash setup.sh`（终端） |

**macOS 优先用 `setup-gui.sh`**：它会依次弹出系统对话框（关微信 → 要密码 → 开微信 → 再要密码 → 完成），
用户只需要点「好」和输密码。你不需要把终端界面暴露给用户。

**macOS 上你必须先跟用户讲清楚三件事**（这是风险告知）：

1. 脚本会**关闭微信 → 重签名 → 重新打开**（为了能读微信进程内存里的密钥）
2. 需要输入一次 **Mac 登录密码**（输入时不显示字符，正常）
3. 如果微信是 **4.1 及以上**，还要在微信里**退出登录 → 重新扫码登录一次**

另外主动提醒：想恢复微信官方签名，重新安装一次微信即可。

**不要做的事**：不要让用户关闭 SIP（`csrutil disable`）。本项目不要求这个。

> ⚠️ `setup-gui.sh` 的密码弹窗流程尚未在真机上完整验证。如果它中途失败，
> 直接回退到 `bash setup.sh`（让用户开终端执行），不要在弹窗环节反复重试。

### 设置完成后自检

```bash
python3 wx_export.py --doctor
```

六项全是 `✓` 就可以开始导出了。任何一项 `✗`，按它给的 `→` 提示处理。

---

## 三、日常导出（你可以全自动完成）

**标准导出**
```bash
python3 "<仓库目录>/wx_export.py" --refresh --days 7 --out messages.json
```

`--refresh` 会先解密数据库（约 1 分钟），然后导出。

**私聊/群聊分开**
```bash
python3 "<仓库目录>/wx_export.py" --refresh --days 7 --split --out messages.json
```

打印两行路径：
```
OUTPUT_FILE: .../messages_private.json
OUTPUT_FILE: .../messages_group.json
```

**导出通讯录**
```bash
python3 "<仓库目录>/wx_export.py" --contacts --refresh --out contacts.json
```

**只统计不写文件**（想先看看有多少数据）
```bash
python3 "<仓库目录>/wx_export.py" --refresh --days 30 --stat
```

### 怎么读命令结果

成功时会打印：
```
OUTPUT_FILE: <文件的绝对路径>
导出 N 条记录，涉及 M 个会话
```

**成功判据只有两条**：
1. 出现了 `OUTPUT_FILE:` 这一行
2. 条数 **> 0**

不要拿条数对照任何"预期值"——数据量取决于用户自己的聊天量和 `--days` 窗口。

---

## 四、输出怎么用

### 聊天记录（默认格式：JSON 数组）

```json
[
  {
    "id": "wxmsg-abc123...",
    "data": {
      "chat_id": "12345678@chatroom",
      "chat_name": "某个群名",
      "chat_type": "group",
      "msg_id": "12345678@chatroom:12345",
      "time": "2026-10-18T09:15:03+08:00",
      "ts": 1792289703,
      "sender": "张三",
      "type": "text",
      "text": "消息正文"
    }
  }
]
```

| 字段 | 用途 |
|---|---|
| `id` | 稳定唯一 ID，**用它做增量去重**（只处理上次之后的新消息） |
| `chat_type` | `group` 群聊 / `private` 私聊 / `official` 公众号 |
| `chat_name` | 按会话筛选时用这个字段 |
| `sender` | 发送人显示名 |
| `type` | `text`/`image`/`emoji`/`video`/`app`/`system` |
| `text` | 正文；非文本消息是占位符或提取到的标题（如链接标题） |

### 通讯录（默认只含微信「通讯录管理」里能看到的）

`type` 取值：`friend` 联系人 / `group` 群聊 / `wecom` 企业微信 / `official` 公众号 / `service` 服务号 / `enterprise` 我的企业。

**数量与用户微信 App 里显示的一致**，可以据此向用户确认"导出对了"。

---

## 五、出错怎么办

**任何失败，先跑自检，不要猜：**

```bash
python3 "<仓库目录>/wx_export.py" --doctor
```

它会把问题定位到具体一项，并给出修复命令。

常见情况：

| 现象 | 原因 | 你该做什么 |
|---|---|---|
| `还没提取数据库密钥` | 首次没初始化 | macOS 让用户跑 `setup.sh`；Windows 你跑 `install.py --auto` |
| `微信签名状态: 仍是官方签名` | 微信升级还原了签名 | 让用户重跑 `setup.sh` |
| `contact 表缺少字段` | 微信换版本、表结构变了 | 如实告诉用户不兼容，附上这行让他提 issue |
| `已经有一路采集在运行` | 并发保护生效 | 正常现象，等它结束即可 |
| `导出 0 条` | 该时段真没消息 | 换个 `--days` 再试，**不要伪造** |

---

## 六、红线

1. **绝不代用户输密码**。macOS 的 `setup.sh` 必须用户亲手执行。
2. **绝不伪造结果**。没看到 `OUTPUT_FILE` 和真实条数，不许说"导出成功"。
3. **绝不上传**导出内容。这些数据只能留在用户本机。
4. **不要外传密钥文件**：`wcdb-key-tool/all_keys.json`、`~/.wcdb-key-tool/wechat-passphrase.json`。
5. **不能发消息**。本工具只读，没有发送能力——用户如果问"能不能帮我回消息"，明确说不能。

---

## 七、完整参数表

```
python wx_export.py [选项]

  --refresh            先刷新解密库（推荐，能拿到最新消息）
  --days N             导出最近 N 天（默认 7）
  --since TS           从 Unix 时间戳开始（覆盖 --days）
  --out FILE           输出文件路径
  --split              私聊/群聊分开写两个文件
  --jsonl              输出 JSONL（每行一条，超大文件用）
  --stat               只统计不写文件
  --max-per-chat N     单会话最多条数（默认 300）
  --include-official   包含公众号与系统通知
  --doctor             自检并给出修复建议
  --emit-events        输出 [{id,data}] 并打印 OUTPUT_FILE

  # 通讯录
  --contacts           导出通讯录
  --contacts-scope     addressbook（默认，与微信 App 一致）/ all（全量）
```
