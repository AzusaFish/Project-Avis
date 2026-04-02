param(
    [string]$ContainerName = "gewe",
    [string]$ImageName = "gewe",
    [string]$TempDir = "D:\gewechat-temp",
    [int]$ApiPort = 2531,
    [int]$WsPort = 2532,
    [int]$WaitSeconds = 90,
    [switch]$PrintTokenOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Docker {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker command not found. Please install Docker Desktop and ensure docker is in PATH."
}

if (-not (Test-Path -LiteralPath $TempDir)) {
    New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
}

$names = Invoke-Docker -DockerArgs @("ps", "-a", "--format", "{{.Names}}")
$containerExists = $names -contains $ContainerName

if (-not $containerExists) {
    Write-Host "[Gewechat] Creating container: $ContainerName" -ForegroundColor Cyan
    Invoke-Docker -DockerArgs @(
        "run", "-itd",
        "-v", "${TempDir}:/root/temp",
        "-p", "${ApiPort}:2531",
        "-p", "${WsPort}:2532",
        "--privileged=true",
        "--name", $ContainerName,
        $ImageName,
        "/usr/sbin/init"
    ) | Out-Null
} else {
    $running = (Invoke-Docker -DockerArgs @("inspect", "-f", "{{.State.Running}}", $ContainerName)).Trim()
    if ($running -ne "true") {
        Write-Host "[Gewechat] Starting existing container: $ContainerName" -ForegroundColor Cyan
        Invoke-Docker -DockerArgs @("start", $ContainerName) | Out-Null
    }
}

Write-Host "[Gewechat] Bootstrapping redis/mysql/base/api inside container..." -ForegroundColor Cyan
$bootstrapScript = @'
set -e

if ! redis-cli ping >/dev/null 2>&1; then
  redis-server /etc/redis.conf >/tmp/redis-start.log 2>&1 &
fi

if ! netstat -lntp 2>/dev/null | grep -q ':3306'; then
  rm -f /var/lib/mysql/mysql.sock /var/lib/mysql/mysql.sock.lock
  mkdir -p /var/run/mysqld
  chown -R mysql:mysql /var/run/mysqld /var/lib/mysql
  nohup /usr/sbin/mysqld --user=mysql --skip-networking=0 --socket=/var/lib/mysql/mysql.sock --port=3306 >/tmp/mysqld-foreground.log 2>&1 </dev/null &
fi

cd /root/gewe/base
if ! pgrep -x long >/dev/null 2>&1; then
  nohup ./long >/tmp/long-run.log 2>&1 </dev/null &
fi
if ! pgrep -x pact >/dev/null 2>&1; then
  nohup ./pact >/tmp/pact-run.log 2>&1 </dev/null &
fi

if ! netstat -lntp 2>/dev/null | grep -q ':2531'; then
  nohup /root/gewe/api/xd java -jar /root/gewe/api/finder-admin.jar >/root/gewe/api/log/manual-api.log 2>&1 </dev/null &
fi
'@

Invoke-Docker -DockerArgs @("exec", $ContainerName, "sh", "-lc", $bootstrapScript) | Out-Null

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$token = $null
$api = "http://127.0.0.1:$ApiPort/v2/api/tools/getTokenId"

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-RestMethod -Method Post -Uri $api -ContentType "application/json" -Body "{}" -TimeoutSec 4
        if ($resp.ret -eq 200 -and $resp.data) {
            $token = [string]$resp.data
            break
        }
    } catch {
    }
    Start-Sleep -Seconds 2
}

if (-not $token) {
    Write-Host "[Gewechat] API is not ready yet. Run diagnostics:" -ForegroundColor Yellow
    Write-Host ("  docker exec {0} sh -lc netstat -lntp" -f $ContainerName)
    Write-Host ("  docker exec {0} sh -lc tail -n 120 /root/gewe/api/log/sys-info.log" -f $ContainerName)
    Write-Host ("  docker exec {0} sh -lc tail -n 120 /root/gewe/base/pact.log" -f $ContainerName)
    throw "Failed to obtain GEWECHAT token within $WaitSeconds seconds."
}

if ($PrintTokenOnly) {
    Write-Output $token
    exit 0
}

$pactAlive = (Invoke-Docker -DockerArgs @("exec", $ContainerName, "sh", "-lc", "pgrep -f '/root/gewe/base/pact' >/dev/null 2>&1 && echo up || echo down")).Trim()
$port4600 = (Invoke-Docker -DockerArgs @("exec", $ContainerName, "sh", "-lc", "netstat -lntp 2>/dev/null | grep ':4600' >/dev/null 2>&1 && echo up || echo down")).Trim()

if ($pactAlive -ne "up" -or $port4600 -ne "up") {
    Write-Host "[Gewechat] Partial ready: token is available, but device layer is not ready." -ForegroundColor Yellow
    Write-Host "[Gewechat] This usually causes getLoginQrCode => device create failed." -ForegroundColor Yellow
    Write-Host ("[Gewechat] Detected: pact={0}, port4600={1}" -f $pactAlive, $port4600) -ForegroundColor Yellow
    Write-Host "[Gewechat] Container hint: cannot connect to device backend, check network connectivity." -ForegroundColor Yellow
    Write-Host "Diagnostics:" -ForegroundColor Cyan
    Write-Host ("  docker exec {0} sh -lc tail -n 120 /root/gewe/base/pact.log" -f $ContainerName)
    Write-Host ("  docker exec {0} sh -lc tail -n 120 /root/gewe/base/log/system.txt" -f $ContainerName)
    throw "Device layer not ready (pact/4600). Token=$token"
}

Write-Host "[Gewechat] Ready. GEWECHAT_TOKEN = $token" -ForegroundColor Green
Write-Host "Next step to request login QR and appId:" -ForegroundColor Cyan
Write-Host ("URL: http://127.0.0.1:{0}/v2/api/login/getLoginQrCode" -f $ApiPort)
Write-Host "Header Content-Type: application/json"
Write-Host ("Header X-GEWE-TOKEN: {0}" -f $token)
$loginPayload = @{ appId = ""; type = "ipad"; regionId = "510000" } | ConvertTo-Json -Compress
Write-Host ("Body: {0}" -f $loginPayload)
