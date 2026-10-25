# Windows 支持说明

Windows 10 / 11 已实测可用，且比 macOS 更简单：**不需要管理员权限，不需要修改微信客户端**。

---

## 快速验证（3 步）

前提：**Python 3.10+**、**微信 4.x 已登录并保持运行**。

```powershell
# 1. 环境检查
python install.py

# 2. 提取密钥（不需要管理员权限）
python install.py --auto

# 3. 试导一次
python wx_export.py --refresh --days 1 --out messages.json
```

第 3 步成功时会打印 `OUTPUT_FILE: <路径>`，并提示导出了多少条消息。

---

## 第 1 步应该看到什么

```
 ✓ 操作系统: Windows
 ✓ Python 版本: 3.1x.x
 ✓ 微信客户端: C:\Program Files\Tencent\Weixin\Weixin.exe  4.1.x.x
 ✓ 微信数据库: C:\Users\<你>\Documents\xwechat_files\wxid_xxx\db_storage
 ✓ 解密组件: ...\wcdb-key-tool
 ✓ 平台解密脚本: wcdb_key_tool_windows.py
 ✓ 运行权限: Windows 无需管理员权限、无需重签微信
 ✗ 数据库密钥: 尚未提取        ← 正常，第 2 步解决
```

重点看两行：

- **微信数据库**：必须能找到真实路径。找不到说明微信数据不在标准位置。
- **平台解密脚本**：必须是 `wcdb_key_tool_windows.py`。

---

## 排障对照表

| 现象 | 大概率原因 | 怎么办 |
|---|---|---|
| `微信没在运行` | 微信关着 | 打开微信并登录后重试 |
| 输出里出现 `Weixin.exe 未运行` | 微信进程名不是 `Weixin.exe` | 任务管理器里看微信进程的准确名字，反馈 issue |
| 密钥提取失败 + HMAC 校验不通过 | 扫到的候选密钥对不上数据库 | 确认微信版本，反馈完整输出 |
| `ModuleNotFoundError` | Python 版本太低 | 升到 3.10+ |
| 微信数据库未找到，但你确实装过微信 | 数据放在非默认盘（如 `D:\`） | 看 `%APPDATA%\Tencent\xwechat\config\*.ini` 里记录的路径 |
| 控制台中文乱码 | 终端编码不是 UTF-8 | 脚本已强制 UTF-8；若仍乱码，`chcp 65001` 后再试 |

---

## Windows 与 macOS 的差异

| | Windows | macOS |
|---|---|---|
| 管理员权限 | **不需要** | 需要（重签微信） |
| 修改微信客户端 | **不需要** | 需要重签 |
| 密钥提取方式 | 运行时只读扫描 | LLDB 断点 + PBKDF2 |
| 额外依赖 | 无 | `lldb`（Xcode CLT） |
| Python 版本 | 3.10+ | 3.8+ |

---

## 已知限制

1. **需要微信保持运行**：密钥要读微信进程内存，关掉就拿不到。
2. **微信大版本更新后**可能需要重新执行 `install.py --auto`。
3. **图片/语音不解析**：只记 `[image]`、`[emoji]` 等占位类型。
4. **本地只有本机消息**：手机上的完整历史需要先用微信「聊天记录迁移」同步到电脑。
