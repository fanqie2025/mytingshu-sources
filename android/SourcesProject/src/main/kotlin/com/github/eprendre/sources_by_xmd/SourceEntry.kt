package com.github.eprendre.sources_by_xmd

import com.github.eprendre.tingshu.sources.TingShu
import java.lang.reflect.Modifier
import java.net.URI

/**
 * 合并源入口。
 *
 * 这个 jar 里除了本源（[Ting22]，22听书修复版）外，还用 d8 合并进了社区几个外置源包的 dex：
 *   sources_by_ting29 / sources_by_m1ngzer / sources_by_eprendre / sources_by_shun /
 *   sources_by_bxb100 / sources_by_luyou
 * 它们的源类在同一个 DexClassLoader 里，所以这里用反射把各包的 SourceEntry.getSources()
 * 取出来汇总，并按 **源ID** 与 **站点域名** 去重，最后交给 app。
 *
 * 去重优先级 = [PACKAGES] 的顺序（越靠前越优先保留）：
 *   自己的修复源 > ting29（新且经 live test）> m1ngzer（书音FM）> eprendre > shun > bxb100 > luyou（2021 老包）
 * 例：22ting.com 同时存在于本源与 shun 包的「一夜幻听」，去重后只保留本源的「22听书」。
 */
object SourceEntry {

    /** 本源内置的源（优先级最高） */
    private fun ownSources(): List<TingShu> = listOf(Ting22)

    /**
     * 死站黑名单：站点已确认无法访问（2026-10-01 体检：DNS / HTTP / 页面标题三方交叉验证）。
     * 按**站点域名**匹配（比按 sourceId 稳，因为部分包的 sourceId 拿不全）。
     * 命中即不加载，源管理里就不会再出现这些废源。
     */
    private val DEAD_HOSTS = setOf(
        "tingzh.com",   // 中文听书网：本机 DNS 黑洞到 127.0.0.1；域名已落到垃圾 CDN
        "70ts.com",     // 麒麟听书：全站 404（/、/index.php、/list/、/search.php 六路径实测）
        "ting74.com",   // 74听书：HTTP/HTTPS 均无响应
        "xiai123.com",  // 口袋微课堂：无响应
        "ysxs8.top",    // 有声小说吧：DNS 解析失败
        "ysxs8.com",    // 有声小说吧：无响应
        "ychy.org",     // 海洋听书网：只剩停放跳转页
        "ychy.com",     // 海洋听书网：根路径 404
        "88tingshu.com" // 88听书网：无 A 记录
    )

    /** 需要反射汇总的其它包，按优先级从高到低排列 */
    private val PACKAGES = listOf(
        "sources_by_ting29",
        "sources_by_m1ngzer",
        "sources_by_eprendre",
        "sources_by_shun",
        "sources_by_bxb100",
        "sources_by_luyou"
    )

    /** 判断两段域名是否属于同一站点时需要忽略的子域前缀 */
    private val SUBDOMAIN_PREFIX = setOf("www", "m", "api", "mobile", "app", "mobi", "wap", "waps", "mip")

    /** 需要保留三段后缀的二级域 */
    private val THREE_PART_SUFFIX = setOf("com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "com.hk", "com.tw")

    @JvmStatic
    fun getDesc(): String {
        return "合并源（已去重）"
    }

    @JvmStatic
    fun getCategory(): String {
        return "听书"
    }

    @JvmStatic
    fun getSources(): List<TingShu> {
        val all = ArrayList<TingShu>()
        all.addAll(ownSources())
        for (pkg in PACKAGES) {
            all.addAll(loadFrom(pkg))
        }
        return dedupe(all)
    }

    /** 反射调用其它包的 SourceEntry.getSources()；任何异常都不影响整体加载 */
    private fun loadFrom(pkg: String): List<TingShu> {
        return try {
            val cls = Class.forName("com.github.eprendre.$pkg.SourceEntry")
            invokeGetSources(cls) ?: emptyList()
        } catch (t: Throwable) {
            emptyList()
        }
    }

    private fun invokeGetSources(cls: Class<*>): List<TingShu>? {
        val methods = cls.methods.filter { it.name == "getSources" && it.parameterTypes.isEmpty() }
        if (methods.isEmpty()) return null
        val instance = try {
            val f = cls.getField("INSTANCE") // Kotlin object
            f.get(null)
        } catch (t: Throwable) {
            null
        }
        for (m in methods) {
            try {
                val isStatic = Modifier.isStatic(m.modifiers)
                if (!isStatic && instance == null) continue
                @Suppress("UNCHECKED_CAST")
                val result = m.invoke(if (isStatic) null else instance) as? List<TingShu>
                if (result != null) return result
            } catch (t: Throwable) {
                // 换下一个重载/下一个目标继续尝试
            }
        }
        return null
    }

    /** 先按 sourceId 去重，再按站点域名去重（保留靠前的那个） */
    private fun dedupe(list: List<TingShu>): List<TingShu> {
        val seenIds = HashSet<String>()
        val seenSites = HashSet<String>()
        val out = ArrayList<TingShu>(list.size)
        for (s in list) {
            val id = try {
                s.getSourceId()
            } catch (t: Throwable) {
                null
            }
            if (id.isNullOrEmpty() || !seenIds.add(id)) continue

            val site = try {
                siteKey(s.getUrl())
            } catch (t: Throwable) {
                ""
            }
            // 死站直接跳过（站点已关停，加载了也搜不出东西）
            if (site.isNotEmpty() && site in DEAD_HOSTS) continue
            if (site.isNotEmpty() && !seenSites.add(site)) continue

            out.add(s)
        }
        return out
    }

    /** 把 URL 归一成站点标识：小写、去掉常见子域前缀、保留 eTLD+1 */
    private fun siteKey(url: String?): String {
        if (url.isNullOrEmpty()) return ""
        return try {
            val raw = if (url.contains("://")) url else "http://$url"
            val host = URI(raw).host?.lowercase() ?: return ""
            var parts = host.split('.').filter { it.isNotEmpty() }
            if (parts.size > 2 && parts[0] in SUBDOMAIN_PREFIX) {
                parts = parts.drop(1)
            }
            if (parts.size >= 3) {
                val lastTwo = parts.takeLast(2).joinToString(".")
                if (lastTwo in THREE_PART_SUFFIX) return parts.takeLast(3).joinToString(".")
            }
            if (parts.size >= 2) parts.takeLast(2).joinToString(".") else host
        } catch (t: Throwable) {
            ""
        }
    }
}
