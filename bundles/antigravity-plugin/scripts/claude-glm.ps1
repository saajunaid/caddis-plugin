# claude-glm — convenience alias: a Claude Code session on GLM (provider preset "glm").
# Thin delegator so the logic lives once in claude-oss.ps1.
& "$PSScriptRoot\claude-oss.ps1" glm @args
exit $LASTEXITCODE
