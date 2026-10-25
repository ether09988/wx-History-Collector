# WeChat Chat History Collector

English | [简体中文](README.md)

Export your own WeChat private and group chat messages into clean, structured JSON — ready to be consumed by any AI agent, analysis script, or knowledge base.

Runs entirely on your machine: **no network calls, no uploads, no third-party accounts**. Decryption and export both happen locally.

> This is collector #1 of the **Financial-data-Collector** series.
> **Are you an AI agent?** Read [`AGENT.md`](AGENT.md) — it contains the capability list,
> task mapping and full parameter reference. You can do everything for the user; they never
> need to open a terminal.
>
> Collector #1 of the [**Financial-data-Collectors**](https://github.com/ether09988/Financial-data-Collectors) series.

---

## What the project is made of

This is not one monolithic script — it's three parts with clearly separated jobs:

| Component | Responsibility | Origin |
|---|---|---|
| `wx_export.py` (927 lines) | **Translate decrypted databases into readable chats / contacts** | Original work |
| `wcdb-key-tool/` (2907 lines) | **Extract the key from WeChat's memory** and **decrypt the encrypted DBs into plain SQLite** | Third-party (MIT, see `NOTICE`) |
| `install.py` + `setup*.sh` (561 lines) | First-time setup: environment check, quit WeChat, re-sign, extract keys | Original work |

### What wx_export.py does on top

The decrypted databases are "queryable but unreadable":

| What you see | What it means | Handled by |
|---|---|---|
| Table `Msg_d9225e13...` | md5 of the contact's WeChat ID | wx_export.py |
| Field `real_sender_id: 12` | Who is #12 — look it up in `name2id` | wx_export.py |
| `local_type: 49` | Link / file / quoted message | wx_export.py |
| Body starts with `28 b5 2f fd` | zstd-compressed; decompress then extract XML titles | wx_export.py |

**In one line**: `wcdb-key-tool` gets the data out of the box; `wx_export.py` turns it into
something usable. Without either, you get nothing readable.

> `wcdb-key-tool` is a mature community implementation. This project **only calls it, never
> modifies it**, and keeps the original attribution as required by its MIT license
> (see `NOTICE` and `wcdb-key-tool/LICENSE`).

---

## What it exports

| Exported | Not exported |
|---|---|
| Text messages from private and group chats (with sender, time, chat name) | Official account posts, system notifications (filtered by default, can be enabled) |
| **Titles** of link / file / quoted messages | The file contents themselves |
| **Full contact list**: friends, groups, official accounts (including people you never chatted with) | — |
| Images / emoji / voice / video: recorded as placeholder types like `[image]`, `[emoji]` | Actual image or audio content |

### Platform support

| Platform | Status | Initialization |
|---|---|---|
| macOS 11+ | ✅ Tested | Requires re-signing WeChat once (admin password needed) |
| Windows 10/11 | ✅ Tested | **No admin rights, no WeChat modification** — one command extracts keys |
| Linux | ❌ Not adapted | The decryption component supports it; this project does not |

> **About SIP (System Integrity Protection) — measured result**
>
> **SIP must be disabled when extracting keys for the first time.** On macOS this is a hard
> prerequisite, not optional.
>
> Measured: with SIP enabled, the key-extraction tool running as root **cannot read WeChat's
> container directory** (macOS TCC blocks root from accessing user data directories while SIP is
> on), and fails with "no decryptable .db files found". With SIP disabled, the same machine and
> the same WeChat version succeed.
>
> Note: what gets blocked is not "reading WeChat's process memory" but "root accessing your user
> directory". Some guides correctly state that SIP only protects system processes and not WeChat —
> but our implementation needs root to read files, so this gate still applies.
>
> **After extraction you should turn SIP back on.** Daily decryption only uses the cached
> passphrase — no root, no file reads as root, no process memory access. Verified: exporting works
> fine with SIP enabled.
>
> ```
> 1. Disable SIP (Recovery Mode → csrutil disable → reboot)   ← only once
> 2. Run setup-gui.sh or setup.sh to extract keys
> 3. Re-enable SIP (recommended: csrutil enable → reboot)
> 4. Use normally from then on, even with SIP on
> ```
>
> Windows is unaffected: no admin rights and no system security changes needed.
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
bash setup-gui.sh          # graphical setup: uses system dialogs, no terminal needed
# or: bash setup.sh        # terminal version (equivalent)
```

> Both scripts do the same thing; they only differ in how the admin password is collected:
> `setup-gui.sh` uses native macOS dialogs (verified on macOS — the user never touches a
> terminal), `setup.sh` prompts in the terminal.

> Why re-sign WeChat on macOS: macOS forbids one process from reading another process's memory
> (Hardened Runtime). Re-signing only removes that restriction; it does not modify any behaviour.
> To restore the official signature, simply reinstall WeChat.
>
> On WeChat 4.1+, you also need to log out and log back in once — the new version only
> derives the key at login time.

**macOS permission requirements (all three must hold, otherwise it fails)**

1. **Run `setup.sh` in the built-in Terminal app on the machine itself.**
   Do not run it over SSH — remote sessions cannot obtain the macOS TCC authorization for
   debugging, and `task_for_pid` will be rejected.
2. **Terminal needs Full Disk Access**, otherwise re-signing fails with `Operation not permitted`.
   Go to System Settings → Privacy & Security → Full Disk Access → add Terminal, then
   **fully quit and reopen Terminal**.
3. **Verify the re-sign actually took effect.** After running `setup.sh`:

   ```bash
   codesign -dv --verbose=2 /Applications/WeChat.app 2>&1 | grep flags
   ```

   It should print `flags=0x2(adhoc)`. If it still shows `flags=0x10000(runtime)`, the re-sign
   did not apply — check requirement #2.

> See the SIP section near the top of this file for the full explanation.

### 3. Export

```bash
# macOS
python3 wx_export.py --refresh --days 7 --out messages.json

# Windows
python wx_export.py --refresh --days 7 --out messages.json
```

On success it prints two lines like this:

```
OUTPUT_FILE: /absolute/path/messages.json
exported 1287 messages across 73 chats
```

> **The message and chat counts above are examples — yours will differ.** They depend on how much
> you chat, the `--days` window, whether any chat hits the `--max-per-chat` cap, and whether you
> included official accounts.
> There is exactly one success criterion: **the `OUTPUT_FILE` line appears and the count is > 0.**
> A bigger or smaller number says nothing about success.

### Troubleshoot first

```bash
python3 wx_export.py --doctor
```

It checks every prerequisite and tells you exactly which one to fix.

### Export private and group chats separately

```bash
python3 wx_export.py --refresh --days 7 --split --out messages.json
```

Produces two files and prints both paths:

```
OUTPUT_FILE: /abs/path/messages_private.json
OUTPUT_FILE: /abs/path/messages_group.json
```

Handy when feeding an agent: you can load only the category you need.

### 4 (optional): export contacts

Want just the address book, not the chat history:

```bash
python3 wx_export.py --contacts --refresh --out contacts.json
```

By default the output **matches the counts shown in WeChat's own
Settings → Contacts Management page**:

| `type` | WeChat label |
|---|---|
| `friend` | Contacts |
| `group` | Group chats (saved to contacts) |
| `wecom` | WeCom contacts |
| `official` | Official accounts |
| `service` | Service accounts |
| `enterprise` | My enterprise |

Add `--contacts-scope all` to additionally export: groups not saved to contacts, official
accounts you followed historically but which are no longer in contacts, the non-friend cache
(group members, pending requests) and system accounts — an order of magnitude larger.

Each record contains:

| Field | Description |
|---|---|
| `wxid` | Unique account ID |
| `name` | Display name (remark > nickname > custom alias > wxid) |
| `remark` | The remark you set |
| `nickname` | Their own WeChat nickname |
| `alias` | Their custom WeChat ID (may be empty) |
| `type` | `friend` / `group` / `official` / `openim` / `stranger` / `system` |
| `deleted` | Whether the contact was deleted |

> ⚠️ Like chat history, this stays on your machine. **The file maps out your entire social
> graph — never commit or upload it.**

---

## Output format

A JSON array; each element is one message:

```json
[
  {
    "id": "wxmsg-3f2a1b8c9d0e4f5a",
    "data": {
      "chat_id": "12345678@chatroom",
      "chat_name": "Some group name",
      "chat_type": "group",
      "msg_id": "12345678@chatroom:12345",
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

  --jsonl              JSONL output (one record per line, for very large exports);
                       default is a JSON array
  --split              Write private and group chats to two separate files
  --doctor             Self-check: WeChat signature / keys / cache / process, with fixes

  # contacts
  --contacts           Export the contact list instead of messages
  --contacts-scope     addressbook (default: friends+groups+WeCom) or
                       all (also official accounts, non-friend cache, system accounts)
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

**For AI agents**

[`AGENT.md`](AGENT.md) is the capability manual: what it can do, which command maps to which
user request, how to read the output, how to self-diagnose failures, and the hard rules
(never type the user's password, never fake success, no message sending).
Hand that file to your agent.

---

## Project layout

```
WeChat-Chat-Collector/
├── README.md               Chinese readme
├── README.en.md            This file
├── AGENT.md                Capability manual for AI agents (setup + usage + troubleshooting)
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

**Do I need to disable SIP?**
**Yes — for the first key extraction.** You can re-enable it afterwards. See the SIP section at
the top of this file.

Measured: with SIP enabled the extractor (running as root) cannot read WeChat's container
directory and fails with "no decryptable .db files found"; with SIP disabled the same environment
succeeds. Once keys are extracted, decryption uses the cached passphrase and works with SIP on.
**Why does macOS need to re-sign WeChat?**
macOS blocks one process from reading another's memory (Hardened Runtime). Re-signing is the
lowest-cost way to remove that flag. To restore the official signature, reinstall WeChat.

**`codesign` fails with `Operation not permitted` — what now?**
Terminal lacks Full Disk Access, so it cannot modify app bundles under `/Applications`.
Add Terminal under System Settings → Privacy & Security → Full Disk Access, fully quit and
reopen Terminal, then re-run `setup.sh`.

**Can I run `setup.sh` over SSH?**
**No.** macOS ties debugging authorization (TCC) to a local GUI terminal. An SSH session's parent
is sshd, which cannot obtain it, so `task_for_pid` always fails. Run it in Terminal on the machine.

**How do I confirm the re-sign worked?**
`codesign -dv --verbose=2 /Applications/WeChat.app 2>&1 | grep flags` should show
`flags=0x2(adhoc)`; `flags=0x10000(runtime)` means it did not apply.

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

See [**Financial-data-Collectors**](https://github.com/ether09988/Financial-data-Collectors) for the full index.

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
