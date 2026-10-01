# 我的听书 · 书源（全部源集中在这里）

**iOS + 安卓两个平台的源都放在这一个仓库**，仅供自用测试。
公开的 App 仓库（`mytingshu-ios`）只保留播放器外壳与书源**格式说明**，不含具体站点实现。

## 在 App 里导入（iOS）

`设置 → 源管理 → 导入书源 → 粘贴下面任一条订阅地址`，或直接把 JSON 粘进「粘贴 JSON」框：

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

| 源 | 状态 | 形态 |
| --- | --- | --- |
| **有听网 / 275听书 / 单田芳评书网 / 爱听书 / 13听书网 / 乐听网 / 酷我畅听 / 书音FM / 29听书网 / 22听书**（10 个） | ✅ 已迁移为 **JSON 规则**（在 `subscription/sources.json`，导入即用；全部实测到 `HTTP 206 + audio/*`） | 规则引擎 v2 |
| 恋听网 | ⏸ 规则已就绪（`tools/pending/ting55.json`），但音频 CDN `pp.ting55.com` 对**海外出口**返回 404/HTML → 本机验不通，**暂未并入订阅**（国内手机应可用） | 待验 |
| Audiobookshelf | ✅ App 内置连接器 | 非抓站源 |

> 22听书：搜索要过图片验证码（规则里配 `verification`，App 会弹内置浏览器过一次）+ 6 秒搜索限流（`searchDelayMs`）；
> 它家**老书音频指向已下线的 `audio.xmcdn.com`（403）**，新书走 `aod.cos.tx.xmcdn.com` 正常 → 搜「三体」点进去可能播不了，属站点数据问题。

### 规则引擎 v2 已支持（`subscription/sources.json` 用的字段）

| 能力 | 字段 |
| --- | --- |
| POST 搜索 | `search.method` / `search.body`（表单**不补 host**） |
| 每步 UA | `ua` / `search.ua` / `detail.ua` / `detail.dirUA` / `audio.ua` |
| 两步取目录 | `detail.dirUrl`（先取目录入口）+ `detail.episodes` + `detail.pages.{url,max}` |
| 自动解 JS 守卫 | 全站默认（「反转 + base64」型 `pt_guid` / `__51guid__` 等全部 cookie 都写） |
| 音频签名 | `audio.sign.{kind,input,alphabet,header,param}`，已实现 `ptcmsSp` / `md5` / `base64Quote` |
| 限流重试 | `audio.retries` + `audio.retryDelayMs`（突发限流要隔几秒换新签名） |
| 状态校验 | `audio.statusField` + `audio.statusOK`（HTTP 200 但 status≠200 时重试） |
| 地址改写 | `audio.replace`（如 https 证书过期换回 http） |
| 随机 cookie | `audio.cookies`（值写 `randHex16`） |
| 取祖先节点 | 取值规则前缀 `^li img@src`（封面常与条目容器不同层） |
| JSON 字段回退 | `audio.field` + `audio.fieldAlt` |

### 校验

```bash
python3 tools/verify_rules.py subscription/sources.json 三体        # 订阅里全部规则
python3 tools/verify_rules.py subscription/sources.json 三体 itingshu  # 只测某个
python3 tools/live_tests/itingshu_verify.py                        # 站点原生链路（对照用）
```

`tools/rule_engine.py` 是**规则引擎的 Python 复刻**（语义与 App 里的 Swift 实现一致），
所以规则能不能用，在这里就能先验证，不用等装到手机上。

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
