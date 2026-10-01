# -*- coding: utf-8 -*-
"""书音FM（m.mekui.com）真机探测脚本 —— 为写 JSON 书源规则做证据采集。

要回答的问题：
  1. ecmsapi 各接口的真实返回结构与字段名（搜索 / 分类导航 / 分类列表 / 详情 / 章节）
  2. 章节从哪来、书与章节的 URL 形态
  3. 音频地址怎么算：SeriesUrl 的签名输入串、参数名、token 是否必须"新鲜"
  4. 有没有不需要签名的替代入口（静态 CDN、api.aikeu.com、旧版 HTML 页）

用法：
  python tools/probe_mekui.py                 # 全链路，关键词"三体"
  python tools/probe_mekui.py 三体
  python tools/probe_mekui.py "" 116875 1     # 跳过搜索，直接指定 bookId/chapterId
环境变量 MEKUI_NOPROXY=1 可强制直连（默认跟随系统代理）。
只读探测，不写任何文件。
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

HOST = "https://m.mekui.com"
API = HOST + "/ecmsapi/index.php"
TOKEN_KEY = "056a308c515e16b2fe5a5c631319339cbc60a8ee0e03d016"  # 来自 MekuiSource.swift:14

UA_M = ("Mozilla/5.0 (Linux; Android 9; SM-S9280) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36")
UA_D = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}) if os.environ.get("MEKUI_NOPROXY") == "1"
    else urllib.request.ProxyHandler())


def get(url, referer=HOST + "/", desktop=False, timeout=30, rng=None, extra=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA_D if desktop else UA_M)
    req.add_header("Referer", referer)
    if rng:
        req.add_header("Range", rng)
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(), r.url
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Content-Type", "") if e.headers else ""), e.read(), url
    except Exception as e:                      # SSL/连接层失败也要能继续往下探
        return 0, "ERROR %s" % type(e).__name__, str(e).encode("utf-8", "replace"), url


def jget(params):
    st, ct, raw, _ = get(API + "?" + urllib.parse.urlencode(params))
    try:
        return st, json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return st, None


def head(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "三体"
    bid = sys.argv[2] if len(sys.argv) > 2 else ""
    cid = sys.argv[3] if len(sys.argv) > 3 else ""

    head("0 首页可达性")
    st, ct, raw, _ = get(HOST + "/")
    home = raw.decode("utf-8", "replace")
    print("HTTP %s %s %d bytes  守卫(var reversed)=%s" % (st, ct, len(raw), "var reversed" in home))
    print("首页里 content 是 10 位数字的 meta：%s"
          % re.findall(r'<meta[^>]*content="(\d{10})"', home)[:5])

    # ---------------- 1 搜索 ----------------
    if kw and not bid:
        head("1 搜索 mod=movie&act=search")
        st, obj = jget({"mod": "movie", "act": "search", "keyword": kw,
                        "page": "1", "pagesize": "20"})
        print("HTTP %s" % st)
        print(json.dumps(obj, ensure_ascii=False)[:900] if obj else "<非 JSON>")
        print("顶层键：%s" % (list(obj.keys()) if isinstance(obj, dict) else "-"))
        d = (obj or {}).get("data") or {}
        lst = d.get("list") or []
        print("data 键：%s   list 条数=%d" % (list(d.keys()), len(lst)))
        if lst:
            print("条目字段：%s" % list(lst[0].keys()))
            for f in ("id", "title", "player", "author", "writer", "titlepic",
                      "moviesay", "intro", "content", "username", "titleurl"):
                print("   %-10s = %r" % (f, lst[0].get(f)))
            bid = str(lst[0]["id"])

    # ---------------- 2 分类导航 ----------------
    head("2 分类导航 mod=column&act=navigation")
    st, obj = jget({"mod": "column", "act": "navigation", "classid": "0"})
    cats = (obj or {}).get("list") or []
    print("HTTP %s  顶层键=%s  分类数=%d" % (st, list((obj or {}).keys()), len(cats)))
    for c in cats:
        print("   classid=%-4s classname=%s" % (c.get("classid"), c.get("classname")))
    cid_for_list = str(cats[0].get("classid")) if cats else "28"

    # ---------------- 3 分类列表 ----------------
    head("3 分类列表 mod=movie&act=list")
    st, obj = jget({"mod": "movie", "act": "list", "classid": cid_for_list,
                    "page": "1", "pagesize": "20"})
    d = (obj or {}).get("data") or {}
    lst = d.get("list") or []
    print("HTTP %s  total=%s list=%d" % (st, d.get("total"), len(lst)))
    if lst:
        print("条目字段：%s" % list(lst[0].keys()))
        print("条目样本：%s" % json.dumps(lst[0], ensure_ascii=False)[:400])
        print("★ 注意：条目里有没有 url/bookurl 字段？→ %s"
              % [k for k in ("url", "bookurl", "titleurl", "link") if k in lst[0]])
        if not bid:
            bid = str(lst[0]["id"])

    # ---------------- 4 详情 ----------------
    head("4 详情 mod=movie&act=detail  id=%s" % bid)
    st, obj = jget({"mod": "movie", "act": "detail", "id": bid})
    det = ((obj or {}).get("data") or {}).get("detail") or {}
    print("HTTP %s  detail 字段=%s" % (st, list(det.keys())))
    print(json.dumps(det, ensure_ascii=False)[:600])

    # ---------------- 5 章节 ----------------
    head("5 章节 mod=movie&act=movielist  id=%s" % bid)
    st, obj = jget({"mod": "movie", "act": "movielist", "id": bid,
                    "page": "1", "pagesize": "1000"})
    d = (obj or {}).get("data") or {}
    chs = []
    for key in ("moielist", "movielist", "list"):
        if isinstance(d.get(key), list):
            chs = d[key]
            print("章节数组字段名：%r" % key)
            break
    print("HTTP %s  data 键=%s  count=%s  章节=%d" % (st, list(d.keys()), d.get("count"), len(chs)))
    if chs:
        print("章节字段：%s  首条=%s" % (list(chs[0].keys()), json.dumps(chs[0], ensure_ascii=False)))
        if not cid:
            cid = str(chs[0]["id"])

    if not cid:
        print("!! 没有 chapterId，音频部分跳过")
        return

    # ---------------- 6 播放页 ----------------
    play_url = "%s/play/%s/%s" % (HOST, bid, cid)
    head("6 播放页 %s" % play_url)
    st, ct, raw, _ = get(play_url)
    play = raw.decode("utf-8", "replace")
    print("HTTP %s %s %d bytes" % (st, ct, len(raw)))
    print("meta 标签：")
    for m in re.findall(r"<meta[^>]*>", play, re.I):
        print("   %s" % m.strip()[:150])
    print("含地址关键字计数：%s"
          % {k: play.lower().count(k) for k in (".mp3", ".m4a", "aikeu", "seriesurl", "ecmsapi", "token")})

    # ---------------- 7 音频接口与签名 ----------------
    def call(raw_q, label, token=None):
        q = raw_q + ("" if token is None else "&token=" + token)
        st, ct, raw, _ = get(API + "?" + q)
        text = raw.decode("utf-8", "replace")
        ok = '"SeriesUrl"' in text
        print("   %-28s → HTTP %s code=%s %s" % (
            label, st, (re.search(r'"code":(\d+)', text) or [None, "?"])[1],
            "✅ 有 SeriesUrl" if ok else text[:90].replace("\n", " ")))
        return text

    head("7 wapseries 签名语义（token = md5(原串 + '&token=' + 密钥)）")
    now = int(time.time())
    fresh_raw = "act=wapseries&id=%s&mod=movie&movieId=%s&t=%d" % (bid, cid, now)
    fresh_tok = hashlib.md5((fresh_raw + "&token=" + TOKEN_KEY).encode()).hexdigest()
    print("   原串=%s" % fresh_raw)
    print("   token=%s" % fresh_tok)
    fresh = call(fresh_raw, "新鲜 t（正确 token）", fresh_tok)
    print("   原始返回：%s" % fresh[:420])
    call(fresh_raw, "同一 t 重放", fresh_tok)
    call(raw_for := "act=wapseries&id=%s&mod=movie&movieId=%s&t=%d" % (bid, cid, now - 86400 * 30),
         "t-30天", hashlib.md5((raw_for + "&token=" + TOKEN_KEY).encode()).hexdigest())
    call("act=wapseries&id=%s&mod=movie&movieId=%s" % (bid, cid), "完全不带 t",
         hashlib.md5(("act=wapseries&id=%s&mod=movie&movieId=%s" % (bid, cid)
                      + "&token=" + TOKEN_KEY).encode()).hexdigest())
    call(fresh_raw, "不带 token")

    head("7b t 的新鲜度窗口（二分：客户端时钟误差容忍多少）")
    for delta in (0, -60, -120, -300, -600, -1800, -3600):
        rq = "act=wapseries&id=%s&mod=movie&movieId=%s&t=%d" % (bid, cid, now + delta)
        call(rq, "t%+ds" % delta, hashlib.md5((rq + "&token=" + TOKEN_KEY).encode()).hexdigest())
    print("   结论：±60s 内可用，超过 1 小时即失效 → **t 必须是请求当刻的 epoch**")

    # ---------------- 8 有没有免签名入口 ----------------
    head("8 免签名/替代入口")
    m = re.search(r'"SeriesUrl":"((?:[^"\\]|\\.)*)"', fresh)
    series = m.group(1).replace("\\/", "/") if m else ""
    signed = re.findall(r'"(https:\\/\\/mp3\.aikeu\.com\\/[^"]+)"', fresh)
    print("SeriesUrl       = %s" % series)
    for s in signed[:6]:
        print("signed_urls 项  = %s" % s.replace("\\/", "/")[:170])

    cands = [
        ("https://mp3.aikeu.com/d/audio/%s/%s.mp3" % (bid, cid), "静态 mp3 无 sign"),
        ("https://mp3.aikeu.com/d/audio/%s/%s.m4a" % (bid, cid), "静态 m4a 无 sign"),
        ("https://api.aikeu.com/api.php?kw=276262963", "api.aikeu 无 sign"),
        ("https://api.aikeu.com/api.php?kw=276262963&t=%d" % now, "api.aikeu 只带 t"),
        ("https://m.mekui.com/album/2-%s.html" % bid, "旧版 album 页"),
        ("https://m.mekui.com/book/%s" % bid, "Swift 里的 /book/{id}"),
        ("https://m.mekui.com/play/%s/%s.html" % (bid, cid), "旧版 .html 播放页"),
        ("https://www.mekui.com/", "PC 站"),
    ]
    for u, label in cands:
        st, ct, raw, final = get(u, rng="bytes=0-512")
        body = raw.decode("utf-8", "replace")
        print("   %-22s %-58s → HTTP %s %s %d bytes" % (label, u[:58], st, ct, len(raw)))
        if st == 200 and "html" in (ct or ""):
            print("        内容：%s" % re.sub(r"\s+", " ", body)[:220])

    # ---------------- 9 真拉 1KB ----------------
    if series:
        head("9 音频真实可播性（Range 0-1024）")
        st, ct, raw, final = get(series, rng="bytes=0-1024")
        print("SeriesUrl → HTTP %s %s %d bytes" % (st, ct, len(raw)))
        print("  最终地址：%s" % final)
        print("  前 16 字节：%s" % raw[:16].hex())
        mp3 = signed[0].replace("\\/", "/") if signed else ""
        if mp3:
            st, ct, raw, final = get(mp3, rng="bytes=0-1024")
            print("signed_urls[0] → HTTP %s %s %d bytes  final=%s" % (st, ct, len(raw), final[:110]))


    # ---------------- 10 kw 溯源（api.aikeu.com 免签名，只差一个 kw） ----------------
    head("10 kw 溯源：免签名的 api.aikeu.com/api.php?kw= 只要一个数字")
    st, ct, raw, _ = get("https://api.aikeu.com/api.php?kw=%s" % 276262963, rng="bytes=0-256")
    print("kw=276262963（无 sign）→ HTTP %s %s %d bytes" % (st, ct, len(raw)), raw[:8].hex())
    st, ct, raw, _ = get("https://api.aikeu.com/api.php?kw=000000000", rng="bytes=0-256")
    print("kw=000000000（无 sign）→ HTTP %s %s %d bytes  %s"
          % (st, ct, len(raw), re.sub(r"\s+", " ", raw.decode("utf-8", "replace"))[:120]))
    st, ct, raw, _ = get("https://api.aikeu.com/api.php", rng="bytes=0-256")
    print("kw 缺失              → HTTP %s %s %s" % (st, ct, re.sub(r"\s+", " ", raw.decode("utf-8", "replace"))[:120]))
    st, ct, raw, _ = get("https://mp3.aikeu.com/d/audio/%s/%s.mp3" % (bid, cid))
    print("mp3 无 sign 的报错体   → HTTP %s  %s" % (st, re.sub(r"\s+", " ", raw.decode("utf-8", "replace"))[:200]))

    print("\n各章节的 kw（靠 wapseries 换来，看有没有规律）：")
    kws = {}
    for c in range(1, 6):
        rq = "act=wapseries&id=%s&mod=movie&movieId=%d&t=%d" % (bid, c, int(time.time()))
        tk = hashlib.md5((rq + "&token=" + TOKEN_KEY).encode()).hexdigest()
        st, ct, raw, _ = get(API + "?" + rq + "&token=" + tk)
        t = raw.decode("utf-8", "replace")
        mm = re.search(r"api\.aikeu\.com\\?/api\.php\?kw=(\d+)", t)
        if mm:
            kws[c] = int(mm.group(1))
            print("   chapter %-3d kw=%s" % (c, mm.group(1)))
        else:
            print("   chapter %-3d 取不到：%s" % (c, t[:80]))
    if len(kws) >= 2:
        ks = list(kws.values())
        print("   相邻差值：%s   （等差则可推算，但源里拿不到基址）"
              % [ks[i + 1] - ks[i] for i in range(len(ks) - 1)])

    print("\n书级页 /album/2-%s.html 里有没有 kw / 音频线索：" % bid)
    st, ct, raw, _ = get("%s/album/2-%s.html" % (HOST, bid))
    album = raw.decode("utf-8", "replace")
    print("   HTTP %s  %d bytes" % (st, len(album)))
    print("   关键字计数：%s" % {k: album.lower().count(k) for k in
                              ("aikeu", ".mp3", ".m4a", "kw=", "seriesurl", "/play/%s/" % bid)})
    for pat in (r"/play/%s/(\d+)" % bid, r"musicrid[\"'：:]*(\d+)", r"kw[\"'：:]*(\d{6,})"):
        found = re.findall(pat, album)
        print("   %-32s → %d 个 %s" % (pat, len(found), found[:5]))
    print("   album 页 meta：%s" % re.findall(r'<meta[^>]*name="([^"]+)"[^>]*content="([^"]*)"', album)[:12])


    # ---------------- 11 站点 API 面：SSR 载荷 + JS chunk 里的接口 ----------------
    head("11 SSR 载荷 / JS chunk 里的接口面")
    st, ct, raw, _ = get(HOST + "/play/%s/%s" % (bid, cid))
    page = raw.decode("utf-8", "replace")
    for needle in ("276262963", "musicrid", "aikeu", "ecmsapi", "wapseries", "d/audio",
                   "SeriesUrl", "__NEXT_DATA__", "self.__next_f"):
        print("   播放页出现 %-18s × %d" % (needle, page.count(needle)))

    chunks = sorted(set(re.findall(r'src="(/_next/static/chunks/[^"]+\.js)"', page)))
    print("   播放页引用 JS chunk %d 个，逐个 grep 接口关键字：" % len(chunks))
    hit_any = False
    for ch in chunks:
        st, ct, raw, _ = get(HOST + ch)
        js = raw.decode("utf-8", "replace")
        hits = [k for k in ("ecmsapi", "wapseries", "aikeu", "node_modules", "/api/",
                            "token=", "md5", "056a308c") if k in js]
        if hits:
            hit_any = True
            print("   %-58s %6d B  命中=%s" % (ch, len(js), hits))
            for k in ("ecmsapi", "wapseries", "aikeu"):
                i = js.find(k)
                if i >= 0:
                    print("        ...%s..." % js[max(0, i - 120):i + 160].replace("\n", " "))
    if not hit_any:
        print("   （没有任何 chunk 直接命中，接口名可能是拼出来的）")

    # ---------------- 12 免签名入口的 kw 到底校不校验 ----------------
    head("12 api.aikeu.com 对 kw 的校验强度")
    for k in ("276262963", "276262964", "000000000", "1"):
        st, ct, raw, final = get("https://api.aikeu.com/api.php?kw=%s" % k, rng="bytes=0-2048")
        print("   kw=%-10s HTTP %s %s %d B  final=%s" % (k, st, ct, len(raw), final[:85]))
        print("        头 32B=%s" % raw[:32].hex())


    # ---------------- 13 还有没有"服务端渲染的章节列表 / 免 token 的系列接口" ----------------
    head("13 章节列表有没有 HTML 形态 / 有没有免 token 的系列接口")
    st, ct, raw, _ = get(HOST + "/play/%s/%s" % (bid, cid))
    page = raw.decode("utf-8", "replace")
    print("   播放页里 /play/%s/ 的上下文：" % bid)
    for m in re.finditer(r"/play/%s/\d+" % bid, page):
        print("        ...%s..." % page[max(0, m.start() - 90):m.end() + 40].replace("\n", " "))
    ch_titles = []
    st, obj = jget({"mod": "movie", "act": "movielist", "id": bid, "page": "1", "pagesize": "5"})
    for c in ((obj or {}).get("data") or {}).get("moielist") or []:
        ch_titles.append(c.get("title"))
    print("   播放页里含章节标题吗？%s" % {t: (t in page) for t in ch_titles[:3]})
    print("   播放页里含 moielist/seriesList/chapterList 字面量：%s"
          % {k: page.count(k) for k in ("moielist", "seriesList", "chapterList", "playlist")})

    print("\n   movielist 换参数能不能吐 HTML：")
    for extra in ({"format": "html"}, {"tempid": "1"}, {"jsoncallback": "cb"},
                  {"act": "movielist_html"}, {"add": "1"}, {"field": "*"}):
        st, obj = jget(dict({"mod": "movie", "act": "movielist", "id": bid,
                             "page": "1", "pagesize": "5"}, **extra))
        print("      %-28s HTTP %s → %s" % (extra, st,
              json.dumps(obj, ensure_ascii=False)[:80] if obj else "<非 JSON>"))

    print("\n   免 token 的系列接口猜测：")
    for act in ("series", "wapseries2", "playurl", "downurl", "player", "url", "geturl", "mp3"):
        st, ct, raw, _ = get(API + "?mod=movie&act=%s&id=%s&movieId=%s" % (act, bid, cid))
        body = raw.decode("utf-8", "replace")
        print("      act=%-10s HTTP %s → %s" % (act, st, body[:80].replace("\n", " ")))

    print("\n   路由猜测（book 页 / 章节页 HTML 形态）：")
    for u in ("%s/%s" % (HOST, bid), "%s/album/%s" % (HOST, bid),
              "%s/play/%s" % (HOST, bid), "%s/list/%s.html" % (HOST, cid_for_list)):
        st, ct, raw, _ = get(u)
        body = raw.decode("utf-8", "replace")
        print("      %-46s HTTP %s %-30s %d bytes  含 /play/%s/ × %d"
              % (u, st, ct, len(raw), bid, body.count("/play/%s/" % bid)))


if __name__ == "__main__":
    main()
