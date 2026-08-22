# claude-deepseek — convenience alias: a Claude Code session on DeepSeek (provider preset "deepseek").
# Thin delegator so the logic lives once in claude-oss.ps1.
& "$PSScriptRoot\claude-oss.ps1" deepseek @args
exit $LASTEXITCODE
