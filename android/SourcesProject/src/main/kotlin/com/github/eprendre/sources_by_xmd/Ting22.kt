package com.github.eprendre.sources_by_xmd

import com.github.eprendre.tingshu.extensions.config
import com.github.eprendre.tingshu.extensions.getCookie
import com.github.eprendre.tingshu.sources.AudioUrlExtraHeaders
import com.github.eprendre.tingshu.sources.AudioUrlExtractor
import com.github.eprendre.tingshu.sources.AudioUrlJsoupExtractor
import com.github.eprendre.tingshu.sources.ISearchVerification
import com.github.eprendre.tingshu.sources.TingShu
import com.github.eprendre.tingshu.utils.*
import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import java.net.URLEncoder

/**
 * 22听书（一夜幻听网 https://22ting.com/）修复版。
 *
 * 站点现状（2026-09 实测）：
 *  - 分类页 /html/22X.html、书籍页 /books/xxxxxx.html、播放页 /mp3/vid-from-part.html 均可直接抓取，无需验证；
 *  - 只有搜索 /search.php 需要过一次图片验证码（页面标题「系统安全验证」，图片是算术题），
 *    验证状态保存在 PHP 会话（PHPSESSID cookie）里；
 *  - 站点限制「搜索 6 秒一次」，超频会返回「提示信息」页。
 *
 * 因此本源实现 ISearchVerification，把验证交给 app 的搜索验证流程：
 * 点「验证」→ app 打开 getSearchVerificationUrl 指向的验证页 → 用户填一次验证码 →
 * app 等 getSearchDelayMs 后重新搜索 → 本源带 WebView 的 cookie 请求即可拿到结果。
 */
object Ting22 : TingShu(), ISearchVerification, AudioUrlExtraHeaders {

    private const val BASE = "https://22ting.com/"

    /** 上一次请求搜索接口时的会话是否有效（false = 需要用户过一次验证码） */
    @Volatile
    private var sessionValidated = false

    override fun getSourceId(): String {
        return "22a11c0de5f60718293a4b5c6d7e8f90"
    }

    override fun getUrl(): String {
        return BASE
    }

    override fun getName(): String {
        return "22听书"
    }

    override fun getDesc(): String {
        return "一夜幻听网（22ting.com）修复版。\n搜索需过一次图片验证码：点底部「需验证」按钮完成验证后即可搜索；" +
                "分类/章节/播放无需验证。\n站点限制搜索 6 秒一次。"
    }

    override fun isWebViewNotRequired(): Boolean {
        return true
    }

    override fun isCacheable(): Boolean {
        return true
    }

    // ------------------------------------------------------------------ 搜索

    override fun search(keywords: String, page: Int): Pair<List<Book>, Int> {
        val kw = URLEncoder.encode(keywords, "utf-8")
        val url = BASE + "search.php?page=" + page + "&searchword=" + kw + "&searchtype="
        val conn = Jsoup.connect(url).config()
        cookieHeader()?.let { conn.header("Cookie", it) }
        val doc = conn.timeout(20000).get()
        val title = doc.title()
        if (title.contains("系统安全验证")) {
            // 会话未通过验证 → 交给 app 的验证流程
            sessionValidated = false
            return Pair(emptyList(), page)
        }
        if (title.contains("提示信息") || title.contains("搜索限制")) {
            // 站点限流：搜索 6 秒一次，本次直接放弃
            return Pair(emptyList(), page)
        }
        sessionValidated = true
        return Pair(parseBookList(doc), totalPageOf(doc) ?: page)
    }

    override fun isSearchValidated(): Boolean {
        return sessionValidated
    }

    override fun getSearchVerificationUrl(keywords: String): String {
        return BASE + "search.php?searchword=" + URLEncoder.encode(keywords, "utf-8")
    }

    override fun getSearchDelayMs(): Long {
        // 站点限定「搜索限制为6秒一次」
        return 6500L
    }

    // ------------------------------------------------------------- 分类（发现）

    override fun getCategoryMenus(): List<CategoryMenu> {
        val menu1 = CategoryMenu(
            "小说", listOf(
                CategoryTab("玄幻", BASE + "html/221.html"),
                CategoryTab("言情", BASE + "html/222.html"),
                CategoryTab("都市", BASE + "html/223.html"),
                CategoryTab("恐怖", BASE + "html/224.html"),
                CategoryTab("惊悚", BASE + "html/225.html"),
                CategoryTab("推理", BASE + "html/226.html"),
                CategoryTab("武侠", BASE + "html/227.html"),
                CategoryTab("历史", BASE + "html/228.html"),
                CategoryTab("军事", BASE + "html/229.html"),
                CategoryTab("穿越", BASE + "html/2210.html"),
                CategoryTab("科幻", BASE + "html/2211.html"),
                CategoryTab("网游", BASE + "html/2212.html")
            )
        )

        val menu2 = CategoryMenu(
            "其它", listOf(
                CategoryTab("评书", BASE + "html/2213.html"),
                CategoryTab("戏曲", BASE + "html/2214.html"),
                CategoryTab("笑话", BASE + "html/2215.html"),
                CategoryTab("儿童", BASE + "html/2216.html"),
                CategoryTab("财经", BASE + "html/2217.html"),
                CategoryTab("广播", BASE + "html/2218.html"),
                CategoryTab("诗歌", BASE + "html/2219.html"),
                CategoryTab("文学", BASE + "html/2220.html"),
                CategoryTab("粤语", BASE + "html/2221.html"),
                CategoryTab("经典", BASE + "html/2222.html"),
                CategoryTab("相声小品", BASE + "html/2223.html"),
                CategoryTab("百家讲坛", BASE + "html/2224.html")
            )
        )

        return listOf(menu1, menu2)
    }

    override fun getCategoryList(url: String): Category {
        val doc = Jsoup.connect(url).config().timeout(20000).get()
        val books = parseBookList(doc)
        val currentPage = Regex("-(\\d+)\\.html").find(url)?.groupValues?.get(1)?.toInt() ?: 1
        val totalPage = totalPageOf(doc) ?: currentPage
        val nextUrl = if (currentPage < totalPage) {
            if (Regex("-\\d+\\.html").containsMatchIn(url)) {
                url.replace(Regex("-\\d+\\.html"), "-" + (currentPage + 1) + ".html")
            } else {
                url.replace(".html", "-" + (currentPage + 1) + ".html")
            }
        } else {
            ""
        }
        return Category(books, currentPage, totalPage, url, nextUrl)
    }

    // ------------------------------------------------------------- 书籍详情

    override fun getBookDetailInfo(bookUrl: String, loadEpisodes: Boolean, loadFullPages: Boolean): BookDetail {
        val doc = Jsoup.connect(bookUrl).config().timeout(30000).get()

        val episodes = ArrayList<Episode>()
        if (loadEpisodes) {
            doc.select("#yuedu ul.ul-36 li a").forEach { a ->
                val href = a.attr("href")
                if (!href.contains("/mp3/")) return@forEach
                val title = a.attr("title").ifEmpty { a.text() }
                episodes.add(Episode(title, absUrl(href)))
            }
        }

        var author = ""
        var artist = ""
        var intro = ""
        doc.select("p.f-gray").forEach { p ->
            val text = p.text()
            if (intro.isEmpty() && text.contains("内容介绍")) {
                intro = text.substringAfter("内容介绍：").substringAfter("内容介绍:")
            }
            if (author.isEmpty()) {
                val m = Regex("作者：(.*?)，由(.*?)播音").find(text)
                if (m != null) {
                    author = m.groupValues[1].trim()
                    artist = m.groupValues[2].trim()
                }
            }
        }
        val cover = doc.selectFirst(".style-img img")?.attr("src")
            ?: doc.selectFirst("img[src*=image]")?.attr("src") ?: ""

        return BookDetail(episodes, intro, artist, author, episodes.size, cover)
    }

    // ------------------------------------------------------------- 音频提取

    override fun getAudioUrlExtractor(): AudioUrlExtractor {
        AudioUrlJsoupExtractor.setUp { doc ->
            // 播放页里的 JS: var now="https://aod.cos.tx.xmcdn.com/....m4a";
            val html = doc.html()
            Regex("var\\s+now\\s*=\\s*\"([^\"]+)\"").find(html)?.groupValues?.get(1) ?: ""
        }
        return AudioUrlJsoupExtractor
    }

    override fun headers(audioUrl: String): Map<String, String> {
        val map = HashMap<String, String>()
        if (audioUrl.contains("xmcdn.com") || audioUrl.contains("22ting.com")) {
            map["Referer"] = BASE
        }
        return map
    }

    // ------------------------------------------------------------- 工具方法

    private fun cookieHeader(): String? {
        return try {
            getCookie(BASE)
        } catch (e: Exception) {
            null
        }
    }

    private fun absUrl(href: String): String {
        return when {
            href.startsWith("http") -> href
            href.startsWith("/") -> BASE.trimEnd('/') + href
            else -> BASE + href
        }
    }

    /**
     * 搜索结果页和分类页用的是同一套列表结构：
     * ul.row-b > li > .style-img > (a.img-80 > .img-box > img) + section > (h2 > span.fr + a.f-bold) + p.f-gray
     */
    private fun parseBookList(doc: Document): List<Book> {
        val list = ArrayList<Book>()
        doc.select("ul.row-b > li, ul.row3 > li, ul.row-b li, .style-img").forEach { li ->
            val a = li.selectFirst("h2 a.f-bold")
                ?: li.selectFirst("a.f-bold")
                ?: return@forEach
            val title = a.text().trim()
            if (title.isEmpty()) return@forEach
            val bookUrl = absUrl(a.attr("href"))
            val cover = li.selectFirst(".img-box img")?.attr("src")
                ?: li.selectFirst("img")?.attr("src") ?: ""
            val span = li.selectFirst("h2 span.fr")?.text()?.trim() ?: ""
            val intro = li.selectFirst("p.f-gray")?.text()?.trim() ?: ""
            var author = span
            var artist = span
            val m = Regex("作者：(.*?)，由(.*?)播音").find(intro)
            if (m != null) {
                author = m.groupValues[1].trim()
                artist = m.groupValues[2].trim()
            }
            list.add(Book(cover, bookUrl, title, author, artist).apply {
                this.intro = intro
                this.sourceId = getSourceId()
            })
        }
        return list
    }

    private fun totalPageOf(doc: Document): Int? {
        val bar = doc.selectFirst(".pagebar") ?: return null
        var max = 1
        bar.select("a").forEach { a ->
            val href = a.attr("href")
            Regex("[?&]page=(\\d+)").find(href)?.let { max = Math.max(max, it.groupValues[1].toInt()) }
            Regex("-(\\d+)\\.html").find(href)?.let { max = Math.max(max, it.groupValues[1].toInt()) }
        }
        return max
    }
}
