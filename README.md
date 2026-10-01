# 我的听书 · 书源（全部源集中在这里）

**iOS + 安卓两个平台的源都放在这一个仓库**，仅供自用测试。
公开的 App 仓库（`mytingshu-ios`）只保留播放器外壳与书源**格式说明**，不含具体站点实现。

## 在 App 里导入（iOS）

`设置 → 源管理 → 导入书源 → 用默认订阅地址（一键导入）`，或手填下面任一条：

```
https://cdn.jsdelivr.net/gh/fanqie2025/mytingshu-sources@main/subscription/sources.json
https://raw.githubusercontent.com/fanqie2025/mytingshu-sources/main/subscription/sources.json
```

> 国内优先用 **jsDelivr** 那条（`raw.githubusercontent.com` 常连不上）。
> 也可以直接把 `subscription/sources.json` 的内容粘贴进「粘贴 JSON」框。
>
> 改完订阅文件后清一次 CDN 缓存，再在 App 里重新导入（同 id 会覆盖旧的）：
> `curl "https://purge.jsdelivr.net/gh/fanqie2025/mytingshu-sources@main/subscription/sources.json"`

## 目录

| 目录 | 说明 |
| --- | --- |
| `android/SourcesProject/` | **安卓源工程（Kotlin）**：`Ting22.kt`（22听书，含图片验证码 + 6 秒搜索限流）+ `SourceEntry.kt`（把多个源聚合成一个入口并按 sourceId/域名去重）+ 我的听书外部源接口桩 |
| `android/dist/sources_by_xmd.jar` | 编译好的安卓源包，丢进 `/sdcard/Android/data/com.github.eprendre.tingshu/files/jars/` 即可 |
| `android/build_merged.ps1` | 安卓端构建：Gradle 编译 → `d8` 把多个 dex/jar 合并成一个 `classes.dex` |
| `android/dist/安卓安装说明.md`、`安装到手机.bat` | 安卓安装说明与 adb 推送脚本 |
| `native-sources/*.swift` | **iOS 原生源**（需要站点专属逻辑、JSON 规则表达不了的，编译进 App 用） |
| `subscription/sources.json` | **iOS 订阅源**（JSON 规则，在 App 内直接导入） |
| `tools/` | 逐站真实链路校验脚本（搜索→分类→详情→章节→音频直链→真拉 1KB） |

## 源清单

| 源 | 安卓 | iOS | 形态 |
| --- | --- | --- | --- |
| 22听书（22ting.com） | ✅ `Ting22.kt` | ✅ `native-sources/Sources.swift` → `Ting22Source` | 搜索要过图片验证码 + 6 秒限流 |
| 书音FM | — | ✅ `MekuiSource` | MD5 签名 |
| 酷我畅听 | — | ✅ `KuwoSource` | 专辑接口 |
| 爱听书 / 13听书网 | — | ✅ `PtcmsSource` | 两步取目录 + `sp` 签名 + 51.LA 守卫（要写 `__51guid__` 与 `__51refresh__guid` **两个** cookie） |
| 乐听网 | — | ✅ `LetingSource` | `pt_guid` 守卫 + AJAX 分类 + `readplay` 双层编码换地址 |
| 恋听网 | — | ✅ `Ting55Source` | `POST /glink` 换地址 + 随机 `mhting55` cookie 规避频控 |
| 29听书网 | — | ✅ `Ting29Source` | JSON 分类 + 守卫 + PC `/player.html` 的 `mp3:` 表达式求值 |
| 有听网 / 275听书 / 单田芳评书网 | — | ✅ `subscription/sources.json` | **JSON 规则，订阅导入即用** |
| Audiobookshelf | — | ✅（App 内置连接器，非抓站源） | 连你自己的服务器 |

> 上表里 `native-sources/` 的 8 个原生源目前**已从 App 移除**（App 改成了外壳）。
> 要用它们得二选一：**(A)** 重新编译进 App；**(B)** 扩展规则引擎，把它们改写成 `subscription/` 里的 JSON 规则。

## 本机跑校验

```bash
python3 tools/verify_subscription.py subscription/sources.json
python3 tools/live_tests/ting15_verify.py      # 单站
python3 tools/guard_solver.py                  # 守卫解 cookie 逻辑（四站实测）
python3 tools/debug_sources.py                 # 逐站定位「搜索能出、进去不行」卡在哪一步
```

CI（`.github/workflows/verify.yml`）每次 push + 每天定时跑一遍；**境外 runner 上部分站点可能因网络原因失败，
那不算结论**，以本机复跑为准。

## 注意

- 抓站源会随站点改版失效；用上面的脚本复跑，能区分是「选择器变了 / 守卫变了 / 加了签名」；
- **请求保持低频**：恋听网按 cookie 计数频控、29听书搜索 30 秒限流、爱听书/13听 429 会要求换 UA；
- 内容版权归各源站与版权方所有，仅供本人本地测试，勿传播、勿商用、勿批量抓取。
