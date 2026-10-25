# WeChat Chat History Collector

English | [简体中文](README.md)

Export your own WeChat private and group chat messages into clean, structured JSON — ready to be consumed by any AI agent, analysis script, or knowledge base.

Runs entirely on your machine: **no network calls, no uploads, no third-party accounts**. Decryption and export both happen locally.

> This is collector #1 of the **Financial-data-Collector** series.
> See the [full series](https://github.com/ether09988/Financial-data-Collectors) for more (QQ chat history, Tonghuashun watchlist/positions, and others).

---

## What it exports

| Exported | Not exported |
|---|---|
| Text messages from private and group chats (with sender, time, chat name) | Official account posts, system notifications (filtered by default, can be enabled) |
| **Titles** of link / file / quoted messages | The file contents themselves |
| Images / emoji / voice / video: recorded as placeholder types like `[image]`, `[emoji]` | Actual image or audio content |

### Platform support

| Platform | Status | Initialization |
|---|---|---|
| macOS 11+ | ✅ Tested | Requires re-signing WeChat once (admin password needed) |
| Windows 10/11 | ✅ Tested | **No admin rights, no WeChat modification** — one command extracts keys |
| Linux | ❌ Not adapted | The decryption component supports it; this project does not |

---

## Quick start

### 1. Prerequisites

**Both platforms**

- WeChat desktop 4.x, **logged in and running** (the key lives in its process memory)
- `zstandard` recommended, otherwise link/file messages only yield placeholders
  - macOS: `pip3 install zstandard --break-system-packages`
  - Windows: `pip install zstandard`

**macOS only**

- Python 3.8+
- Xcode Command Line Tools (provides `lldb`): `xcode-select --install`

**Windows only**

- **Python 3.10+** (the decryption component uses 3.10 syntax)
- No `lldb`, no admin rights

### 2. Initialize (once)

**Windows**

```powershell
python install.py          # environment check
python install.py --auto   # extract keys automatically (WeChat must stay logged in)
```

**macOS**

```bash
python3 install.py         # environment check
bash setup.sh              # extract keys (asks for your admin password once)
```

> Why re-sign WeChat on macOS: macOS forbids one process from reading another process's memory
> (Hardened Runtime). Re-signing only removes that restriction; it does not modify any behaviour.
> To restore the official signature, simply reinstall WeChat.
>
> On WeChat 4.1+, you also need to log out and log back in once — the new version only
> derives the key at login time.

### 3. Export

```bash
# macOS
python3 wx_export.py --refresh --days 7 --out messages.json

# Windows
python wx_export.py --refresh --days 7 --out messages.json
```

On success it prints:

```
OUTPUT_FILE: /absolute/path/messages.json
exported 3574 messages across 135 chats
```

---

## Output format

A JSON array; each element is one message:

```json
[
  {
    "id": "wxmsg-3f2a1b8c9d0e4f5a",
    "data": {
      "chat_id": "53782458966@chatroom",
      "chat_name": "Some group name",
      "chat_type": "group",
      "msg_id": "53782458966@chatroom:12345",
      "time": "2026-10-18T09:15:03+08:00",
      "ts": 1792289703,
      "sender": "Alice",
      "type": "text",
      "text": "Message body, up to 800 chars"
    }
  }
]
```

| Field | Description |
|---|---|
| `chat_id` | Unique chat ID (`xxx@chatroom` for groups, wxid or custom ID for private chats) |
| `chat_name` | Display name (remark first, then nickname) |
| `chat_type` | `group` / `private` / `official` |
| `msg_id` | Unique message ID — use it for incremental deduplication |
| `time` | RFC3339 with timezone |
| `sender` | Sender display name |
| `type` | `text` / `image` / `emoji` / `video` / `app` / `system` … |
| `text` | Body; placeholder or extracted title for non-text messages |

---

## CLI options

```
python wx_export.py [options]

  --refresh            Refresh the decrypted snapshot first (recommended)
  --days N             Export the last N days (default 7)
  --since TS           Start from a Unix timestamp (overrides --days)
  --out FILE           Output path (defaults to messages.json in the temp dir)
  --emit-events        Emit an [{id,data}] array and print OUTPUT_FILE
  --max-per-chat N     Max messages per chat (default 300)
  --include-official   Include official accounts and system notifications
  --decrypted DIR      Use a specific decrypted database directory
  --stat               Count only, write nothing
```

---

## Wiring it into an AI agent

The output is plain JSON — anything that can read a file can use it.

**One-off**

```bash
python wx_export.py --refresh --days 1 --out today.json
# hand today.json to your agent as context
```

**Recurring data source**

Schedule the command:

```bash
python wx_export.py --refresh --days 1 --emit-events --out events.json
```

The tool prints `OUTPUT_FILE: <path>`; read that line to locate the file.
Each record has a stable `msg_id`, so you can process only messages newer than your last run.

**Installation instructions for agents**

[`AGENT-INSTALL.md`](AGENT-INSTALL.md) is written for AI agents: it spells out decision points,
failure handling, and hard rules (never type the user's password, never fake success).
Hand that file to your agent and let it do the setup.

---

## Project layout

```
WeChat-Chat-Collector/
├── README.md               Chinese readme
├── README.en.md            This file
├── AGENT-INSTALL.md        Setup playbook for AI agents
├── WINDOWS-TEST.md         Windows notes and troubleshooting
├── install.py              Environment check + key extraction (automatic on Windows)
├── setup.sh                macOS only: initialization
├── wx_export.py            Core: decrypt → parse → export JSON
├── LICENSE                 MIT
├── NOTICE                  Third-party component notice
└── wcdb-key-tool/          Third-party decryption component (see NOTICE)
    ├── wcdb_key_tool_macos.py
    ├── wcdb_key_tool_windows.py
    ├── wcdb_key_tool.py
    └── LICENSE
```

Two private files are generated locally (already excluded via `.gitignore` — **never commit them**):

- `wcdb-key-tool/all_keys.json` — database keys
- `~/.wcdb-key-tool/wechat-passphrase.json` — cached login passphrase (mode 600)

---

## Privacy and security

- **Fully local**: no network calls, no uploads, no servers. You can verify with `grep`.
- **Transient snapshots**: decrypted files go to the system temp directory and are overwritten each run.
- **Read-only**: never modifies the WeChat database, never sends messages, never touches network protocols.
- **Keys are sensitive**: `all_keys.json` and `wechat-passphrase.json` unlock your entire chat history.
  Do not commit, share, or sync them.

---

## FAQ

**Does it send my data anywhere?**
No. There is no networking code at all.

**Will it survive WeChat updates?**
You may need to re-run the initialization. On macOS, updating WeChat restores its original
signature — re-run `setup.sh`.

**Why does macOS need to re-sign WeChat?**
macOS blocks one process from reading another's memory. Re-signing removes Hardened Runtime,
which is the lighter of the two options (disabling SIP is more invasive and not recommended).

**Why are images empty?**
WeChat stores images as encrypted `.dat` files. This tool records `[image]` placeholders only.

**Why are some messages missing?**
WeChat only keeps messages sent or received on this machine. Use WeChat's
"Migrate chat history" feature to bring messages from your phone.

**Can this get my account restricted?**
The tool only reads local databases and process memory; it does not modify WeChat or touch its
network traffic. On macOS, however, re-signing modifies a third-party application, and Tencent's
detection behaviour cannot be guaranteed. Evaluate the risk yourself.

---

## Other collectors in the series

| Collector | Status |
|---|---|
| WeChat chat history (this repo) | ✅ Available |
| QQ chat history | 🚧 Planned |
| Tonghuashun watchlist / positions | 🚧 Planned |
| Broker trade records | 🚧 Planned |

See [Financial-data-Collectors](https://github.com/ether09988/Financial-data-Collectors) for the full index.

---

## License

Original work in this project (`wx_export.py`, `install.py`, `setup.sh`, documentation) is released
under the **MIT License**, Copyright © 2026 ether09988.

`wcdb-key-tool/` is a third-party open-source component under its own MIT License, with copyright
held by its original authors. See [`NOTICE`](NOTICE) and `wcdb-key-tool/LICENSE`.

## Disclaimer

This tool is intended solely for exporting chat history from **your own account on your own device**,
for personal backup and analysis.

- Do not use it to obtain other people's messages
- Comply with the laws of your jurisdiction and WeChat's terms of service
- You are responsible for any consequences of use

This project contains no protocol reverse-engineering and bypasses no server-side restrictions;
it only reads data already present on your machine.
