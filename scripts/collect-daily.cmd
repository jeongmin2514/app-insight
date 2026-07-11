@echo off
rem app-insight daily auto collect (Windows Task Scheduler)
cd /d C:\Users\T\Desktop\my-multilink
call claude -p "Read C:\Users\T\Desktop\portfolio\app-insight\scripts\collect-prompt.md and follow its instructions exactly." --add-dir C:\Users\T\Desktop\portfolio\app-insight --allowedTools "Read,Write,Edit,Glob,Grep,Bash,ToolSearch,mcp__apps-in-toss-console__workspace_list,mcp__apps-in-toss-console__dashboard_dau,mcp__apps-in-toss-console__dashboard_retention" >> C:\Users\T\Desktop\portfolio\app-insight\collect.log 2>&1
if errorlevel 1 (
  msg %USERNAME% "app-insight collect FAILED - check collect.log / claude /mcp reauth"
)
