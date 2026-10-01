# 构建「合并去重」版外置源
#   1) Gradle 编译本包（Ting22 + 聚合器 SourceEntry）→ CustomSources-1.0-SNAPSHOT.jar
#   2) d8 把本包与社区各包 dex 合并成一个 classes.dex → dist\sources_by_xmd.jar
$ErrorActionPreference = "Stop"
$env:JAVA_HOME = "D:\Java\jdk-17\jdk-17.0.16"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"

$root = "G:\工作台\ximalaya\wodetingshu"
$proj = "$root\xmdsources"
$d8   = "$root\upstream\tingshu-master\dx_win\d8.bat"
$work = "$root\tools\merge"
$dist = "$root\dist"

Write-Host "=== 1/3 Gradle 编译本包 ===" -ForegroundColor Cyan
& "$root\tools\gradle-8.0\bin\gradle.bat" -p $proj jar -x dexTask --console=plain | Select-String -Pattern 'BUILD|error:|FAILED'
if ($LASTEXITCODE -ne 0) { throw "gradle 编译失败" }

$ownJar = "$proj\build\libs\CustomSources-1.0-SNAPSHOT.jar"

Write-Host "=== 2/3 d8 合并 ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null
# 参与合并的包（顺序即去重优先级：靠前的包优先保留）
$inputs = @(
    $ownJar,                                                   # sources_by_xmd（本源，最高优先级）
    "$root\sources2\sources_by_ting29.jar",                    # sources_by_ting29
    "$root\sources\m1ngzer__sources_by_m1ngzer.jar",           # sources_by_m1ngzer
    "$root\sources\kang532155241__sources_by_eprendre.jar",    # sources_by_eprendre
    "$root\sources\kang532155241__sources_by_shun.jar",        # sources_by_shun
    "$root\sources\kang532155241__sources_by_bxb100.jar",      # sources_by_bxb100
    "$root\sources\elevenChen2019__sources_by_luyou.jar"       # sources_by_luyou
)
foreach ($i in $inputs) { if (-not (Test-Path $i)) { throw "缺少输入: $i" } }

Push-Location $work
& $d8 --min-api 21 --output "$work\sources_by_xmd.jar" @inputs 2>&1 | Select-Object -Last 20
$d8exit = $LASTEXITCODE
Pop-Location
if ($d8exit -ne 0) { throw "d8 合并失败 (exit $d8exit)" }

Copy-Item "$work\sources_by_xmd.jar" "$dist\sources_by_xmd.jar" -Force

Write-Host "=== 3/3 结果 ===" -ForegroundColor Cyan
Get-ChildItem "$dist\sources_by_xmd.jar" | Select-Object FullName, Length | Format-Table -AutoSize
