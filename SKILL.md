---
name: calendar-summons-sync
description: Set up, migrate, validate, and troubleshoot a local court summons recognition workflow that watches a folder, extracts hearing details from PDF/images/txt, and syncs events to iCloud Calendar through CalDAV. Use when a user wants to install this system on another computer, create or check iCloud calendar configuration, register a Windows logon listener, process summons files, diagnose missing events, hidden/visible PowerShell windows, OCR/toolchain issues, or safely share the workflow without leaking Apple credentials or case materials.
---

# Calendar Summons Sync

## Purpose

Use this skill to deploy or maintain a local "summons to calendar" system:

```text
PDF / image / txt summons
-> watched inbox folder
-> text extraction or OCR
-> hearing date, court, case number, location
-> JSON confirmation record
-> iCloud Calendar event through CalDAV
```

Never copy or expose `icloud-calendar.json`, Apple ID passwords, App-specific passwords, processed summons, recognition logs, or client materials when sharing the skill or system template.

## Resource Map

- `assets/calendar-system/90-脚本/`: reusable system scripts copied from the working implementation.
- `scripts/install_calendar_system.ps1`: installs the template into a chosen workspace and creates the required folders.
- `references/troubleshooting.md`: read when debugging setup, watcher, OCR, CalDAV, or scheduled task issues.

## Install Workflow

1. Ask the user for a target workspace if it is not obvious. On Windows, prefer a local synced work folder such as `C:\...\IntelFlow` or another folder the user owns.
2. Run `scripts/install_calendar_system.ps1 -TargetRoot "<target workspace>"` from this skill folder.
3. Confirm the installed structure exists:

```text
日程管理系统/
  01-待识别传票/
  02-识别文本/
  03-待确认日程/
  04-日历导出/
  05-已处理传票/
  06-识别失败/
  07-同步日志/
  08-同步失败/
  90-脚本/
```

4. Check the local toolchain. Prefer an existing device-local docflow setup. On Windows, common paths are:

```text
C:\Codex-Local-Tools-NoSync\docflow\codex-docflow-env.ps1
E:\Codex-Local-Tools-NoSync\docflow\codex-docflow-env.ps1
```

5. Ensure Python is available. For PDF/image support, also check `pdftotext`, `pdftoppm`, and `tesseract`.
6. Create the iCloud config template by running the installed `90-脚本\04-创建iCloud配置模板.ps1`, or create a local non-synced config manually.
7. Have the user fill Apple ID and Apple App-specific password locally. Do not ask the user to paste the password into chat.
8. Run `90-脚本\03-检查iCloud日历连接.ps1`. Success should list calendars and mark the target calendar with `*`.
9. Run `90-脚本\05-注册开机自动监听.ps1`.
10. Run `90-脚本\07-查看监听状态.ps1`; if needed, start the scheduled task or run `90-脚本\02-启动监听.ps1`.

## iCloud Config Rules

The config must live outside the synced work folder, for example:

```text
C:\Codex-Local-Tools-NoSync\calendar-sync\icloud-calendar.json
E:\Codex-Local-Tools-NoSync\calendar-sync\icloud-calendar.json
```

Template:

```json
{
  "enabled": true,
  "apple_id": "user@example.com",
  "app_specific_password": "xxxx-xxxx-xxxx-xxxx",
  "calendar_name": "私活",
  "base_url": "https://caldav.icloud.com"
}
```

Use an Apple App-specific password, not the Apple ID login password.

## Verification

After setup, place one test summons file into `01-待识别传票`. A successful run should:

- move the original file to `05-已处理传票`;
- write extracted text to `02-识别文本`;
- write a confirmation JSON to `03-待确认日程`;
- write an iCloud sync log to `07-同步日志`;
- show `calendar_sync.status` as `synced`.

If the inbox becomes empty and the user thinks "nothing happened", check the latest files in these output folders before assuming failure.

## Sharing Boundary

When packaging for another person, include only:

- this skill folder;
- generic scripts under `assets/calendar-system`;
- generic references.

Exclude:

- `icloud-calendar.json`;
- Apple credentials;
- `01-待识别传票`, `02-识别文本`, `03-待确认日程`, `05-已处理传票`, `06-识别失败`, `07-同步日志`, `08-同步失败` contents;
- any real summons, case files, or client data.
