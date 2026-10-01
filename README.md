# 我的听书 · 书源（私有）

**仅供本人自用测试。** 这里放抓站书源的实现与校验脚本；公开的 App 仓库只保留书源**格式说明**，
不包含任何具体站点实现。

## 内容

| 目录 | 说明 |
| --- | --- |
| `subscription/sources.json` | **订阅文件**：用 JSON 规则写的书源，在 App 里「设置 → 导入书源」填这个文件的地址即可导入 |
| `tools/verify_subscription.py` | 校验订阅文件里每个源：搜索 → 分类 → 章节 → 音频直链 → 真拉 1KB（要求 206 + `audio/*`） |
| `tools/live_tests/*_verify.py` | 各站单独的真实链路校验脚本（搜索/分类/详情/章节/直链六项） |
| `tools/guard_solver.py` | 「反转 + base64」型 JS Cookie 守卫的解 cookie 逻辑（PTCMS 要写两个 cookie，少写一个就会一直停在挑战页） |
| `native-sources/*.swift` | 需要站点专属逻辑、**JSON 规则表达不了**的源（编译进 App 用；App 已改为外壳，这里是归档） |

## 在 App 里导入

App 是私有的，`raw.githubusercontent.com` 匿名访问会 404，二选一：

1. **带 token 的地址**（推荐自用；token 只存在你自己手机里）：
   ```
   https://<你的PAT>@raw.githubusercontent.com/fanqie2025/mytingshu-sources/main/subscription/sources.json
   ```
2. **直接粘贴 JSON**：把 `subscription/sources.json` 的内容复制进 App 的「粘贴 JSON」框。

改完 `sources.json` 记得在 App 里重新导入一次（同 id 的规则会覆盖旧的）。

## 本机跑校验

```bash
python3 tools/verify_subscription.py subscription/sources.json
python3 tools/live_tests/ting15_verify.py      # 单站
```

CI（`.github/workflows/verify.yml`）每次 push 会跑一遍；**境外 runner 上部分站点可能因网络原因失败，
那不算结论**，以本机复跑为准。

## 已实现的源

| 站点 | 形态 | 备注 |
| --- | --- | --- |
| 有听网 / 275听书 / 单田芳评书网 | JSON 规则（订阅） | 直接导入即用 |
| 22听书 | native：搜索要过图片验证码 + 6 秒搜索限流 | `ISearchVerification` |
| 书音FM | native：MD5 签名 | |
| 酷我畅听 | native：专辑接口 | |
| 爱听书 / 13听书网 | native：两步取目录 + `sp` 签名音频 + 51.LA 守卫 | 守卫要写 `__51guid__` + `__51refresh__guid` |
| 乐听网 | native：`pt_guid` 守卫 + AJAX 分类 + `readplay` 双层编码换地址 | |
| 恋听网 | native：`POST /glink` 换地址 + 随机 `mhting55` cookie 规避频控 | |
| 29听书网 | native：JSON 分类 + 守卫 + PC `/player.html` 的 `mp3:` 表达式求值 | |

## 注意

- 抓站源会随站点改版失效，用上面的脚本复跑定位是「选择器变了 / 守卫变了 / 加了签名」；
- **请求请保持低频**：多数站点都有频控（恋听网按 cookie 计数、29听书 30 秒搜索限流、爱听书/13听 429 换 UA）；
- 内容版权归各源站与版权方所有，仅供本人本地测试，勿传播、勿商用、勿批量抓取。
