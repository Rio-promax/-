$ErrorActionPreference = 'Stop'

$browserOpened = $false

function Normalize-DshUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate
    )

    $url = $Candidate.Trim().TrimEnd([char[]]@('.', ',', ';', ':', ')', ']', '}'))
    if ($url -match '^https?://0\.0\.0\.0(?=[:/]|$)') {
        $scheme = if ($url.StartsWith('https://')) { 'https' } else { 'http' }
        $url = $url -replace '^https?://0\.0\.0\.0', "${scheme}://localhost"
    }
    return $url
}

function Open-DshUrlFromLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Line
    )

    if ($script:browserOpened -or $Line -match '^npm\s+(notice|err)') {
        return
    }

    $localUrl = $null
    $fallbackUrl = $null
    $urlMatches = [regex]::Matches($Line, 'https?://[^\s<>"''`]+')

    foreach ($match in $urlMatches) {
        $candidate = Normalize-DshUrl -Candidate $match.Value
        if ($candidate -match '^https?://(localhost|127\.0\.0\.1)(:\d+)?(/|$)') {
            $localUrl = $candidate
            break
        }

        if ($null -eq $fallbackUrl) {
            $fallbackUrl = $candidate
        }
    }

    $urlToOpen = if ($null -ne $localUrl) { $localUrl } else { $fallbackUrl }
    if ($null -eq $urlToOpen) {
        return
    }

    Write-Host "检测到网站：$urlToOpen"
    Start-Process $urlToOpen
    $script:browserOpened = $true
}

Write-Host '正在启动 DeepSeek DSH Web...'
Write-Host '执行命令：npx @deepseek-ai/dsh web'
Write-Host ''

try {
    if ($null -eq (Get-Command npx -ErrorAction SilentlyContinue)) {
        throw '未找到 npx。请先安装 Node.js，并确认 npx 已加入 PATH。'
    }

    & npx @deepseek-ai/dsh web 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        Open-DshUrlFromLine -Line $line
    }

    if (-not $browserOpened) {
        Write-Warning '命令结束前没有检测到有效网站地址。'
    }
}
catch {
    Write-Error $_.Exception.Message
}
finally {
    Write-Host ''
    Read-Host '按 Enter 关闭终端（服务运行时请勿关闭）' | Out-Null
}
