# Troubleshooting

## PowerShell Blocks `.ps1`

Check:

```powershell
Get-ExecutionPolicy -List
```

Set current user policy:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
```

If a downloaded file is blocked:

```powershell
Unblock-File -LiteralPath "<script.ps1>"
```

## iCloud Sync Is Not Enabled

Check the local non-synced config. Do not print secrets in chat.

Required fields:

```json
"enabled": true,
"apple_id": "...",
"app_specific_password": "...",
"calendar_name": "..."
```

Run:

```powershell
.\日程管理系统\90-脚本\03-检查iCloud日历连接.ps1
```

Success lists available calendars and marks the configured calendar with `*`.

## File Appears To Do Nothing

The listener may have already processed and moved it. Check:

```text
05-已处理传票
02-识别文本
03-待确认日程
07-同步日志
06-识别失败
08-同步失败
```

Read the newest confirmation JSON and sync log.

## Listener Status Is Confusing

Run:

```powershell
.\日程管理系统\90-脚本\07-查看监听状态.ps1
```

If the scheduled task is `Ready`, it is registered but not currently running. Start it:

```powershell
Start-ScheduledTask -TaskName "IntelFlowCalendarListener"
```

If a foreground black PowerShell window appears, re-register with a script that uses `-WindowStyle Hidden` in the scheduled task action.

## OCR Does Not Work

Check commands:

```powershell
python --version
Get-Command pdftotext,pdftoppm,tesseract -ErrorAction SilentlyContinue
```

For scanned PDFs and images, `pdftoppm` and `tesseract` must be available. Chinese OCR should have `chi_sim` installed.

## Network Or CalDAV Failure

If sandboxed execution reports socket or network permission errors, rerun the iCloud check with normal local permissions. If the network is available but authentication fails, verify:

- Apple ID is correct;
- App-specific password is correct;
- the user did not use the Apple ID login password;
- `base_url` is `https://caldav.icloud.com`;
- the target `calendar_name` exactly matches one listed by the check script.
