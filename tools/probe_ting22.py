# -*- coding: utf-8 -*-
"""22听书（一夜幻听网 22ting.com）逆向探测脚本 —— 迁移 Swift Ting22Source 前的链路确认。

跑法：
    cd G:\\工作台\\ximalaya\\wodetingshu\\sources-private\\tools
    C:\\Users\\Administrator\\AppData\\Local\\Python\\bin\\python.exe probe_ting22.py

分三段：
  ① 裸探：分类页 / 书籍页 / 播放页 / 音频 Range 的真实结构与响应头
  ② 搜索探：冷会话、带验证码会话、限流页各是什么样；验证码怎么过
  ③ 链路证明：用 rule_engine（App 规则引擎的 Python 复刻）跑
     do_menus → 分类第一页 → 第一本 → do_detail 章节 → do_audio → Range 试听

本脚本只读线上站点，不改任何东西。
"""
import http.cookiejar
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rule_engine as R  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

HOST = "https://22ting.com"
BASE = HOST + "/"
UA_D = R.UA_D
UA_M = R.UA_M

JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


def get(url, referer=None, ua=UA_M, cookie=None, method="GET", body=None, timeout=45, tries=3):
    """返回 (status, headers, bytes)。网络抖动最多重试 3 次（间隔 3 秒）。"""
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, data=body)
        req.add_header("User-Agent", ua)
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        if referer:
            req.add_header("Referer", referer)
        if cookie:
            req.add_header("Cookie", cookie)
        if method != "GET":
            req.get_method = lambda: method
        try:
            with OPENER.open(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
        except Exception as e:  # 超时/连接重置
            last = e
            if i < tries - 1:
                print("        … 第 %d 次请求失败（%s），3 秒后重试" % (i + 1, str(e)[:60]))
                time.sleep(3)
    raise last


def text_of(raw, headers):
    ct = (headers.get("Content-Type") or "").lower()
    enc = "gbk" if "gbk" in ct or "gb2312" in ct else "utf-8"
    return raw.decode(enc, "replace")


def title_of(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    return (m.group(1).strip() if m else "")[:80]


def head(t):
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


# --------------------------------------------------------------------------
# ① 裸探：结构
# --------------------------------------------------------------------------

def probe_raw():
    head("① 裸探：分类页 / 书籍页 / 播放页 / 音频")

    # --- 分类页 ---
    url = BASE + "html/221.html"
    st, hd, raw = get(url, referer=BASE)
    html = text_of(raw, hd)
    print("[分类页] %s → HTTP %s  %d 字节  title=%s" % (url, st, len(raw), title_of(html)))
    print("        ul.row3.row-b 命中 : %d" % len(re.findall(r'<ul class="row3 row-b"', html)))
    print("        li.col-* 命中       : %d" % len(re.findall(r'<li class="col-', html)))
    print("        a.f-bold 命中       : %d" % len(re.findall(r'class="f-bold"', html)))
    print("        /books/ 链接        : %d" % len(re.findall(r'href="(/books/\d+\.html)"', html)))
    # 分页
    pg = re.findall(r'class="pagebar"[\s\S]{0,400}?</div>', html)
    print("        pagebar 片段        : %s" % (re.sub(r"\s+", " ", pg[0])[:220] if pg else "(无)"))
    blk = re.search(r'<ul class="row3 row-b">([\s\S]*?)</li>', html)
    if blk:
        print("        第一条 li 原文     : %s" % re.sub(r"\s+", " ", blk.group(1) + "</li>")[:420])

    # --- 分类第 2 页 URL 形态 ---
    url2 = BASE + "html/221-2.html"
    st2, hd2, raw2 = get(url2, referer=url)
    h2 = text_of(raw2, hd2)
    print("[分类页2] %s → HTTP %s  %d 字节  title=%s  /books/ 链接 %d"
          % (url2, st2, len(raw2), title_of(h2), len(re.findall(r'href="(/books/\d+\.html)"', h2))))

    # --- 书籍页 ---
    book = BASE + "books/2235.html"
    st3, hd3, raw3 = get(book, referer=BASE)
    bh = text_of(raw3, hd3)
    print("[书籍页] %s → HTTP %s  %d 字节  title=%s" % (book, st3, len(raw3), title_of(bh)))
    print("        #yuedu ul.ul-36 li a 命中 : %d" % len(re.findall(r'<li id="\d+"><a title="', bh)))
    print("        href=\"/mp3/...\" 命中     : %d" % len(re.findall(r'href="(/mp3/\d+-\d+-\d+\.html)"', bh)))
    print("        p.f-gray（作者/播音）    : %s" % re.sub(r"<[^>]+>", "", (re.search(r'<p class="f-gray mb10">([\s\S]*?)</p>', bh) or [None, ""])[1] if re.search(r'<p class="f-gray mb10">([\s\S]*?)</p>', bh) else "")[:160])
    print("        封面 img                : %s" % ((re.search(r'<div class="style-img[\s\S]{0,400}?<img[^>]+src="([^"]+)"', bh) or [None, ""])[1]))
    ep = re.search(r'<li id="\d+"><a title="([^"]*)" href="(/mp3/[^"]+)"', bh)
    print("        第一章                  : %s" % (str(ep.groups()) if ep else "(无)"))

    # --- 播放页 ---
    play = BASE + "mp3/2235-0-0.html"
    st4, hd4, raw4 = get(play, referer=book)
    ph = text_of(raw4, hd4)
    print("[播放页] %s → HTTP %s  %d 字节  title=%s" % (play, st4, len(raw4), title_of(ph)))
    m = re.search(r'var\s+now\s*=\s*"([^"]+)"', ph)
    print("        var now                 : %s" % (m.group(1) if m else "(未命中)"))
    print("        next/pre 变量           : %s" % ((re.search(r'var next="([^"]*)"', ph) or [None, ""])[1]))
    print("        是否有验证/跳转脚本     : %s" % ("系统安全验证" in ph or "提示信息" in ph))

    # --- 音频真拉 ---
    if m:
        aurl = m.group(1)
        req = urllib.request.Request(aurl)
        req.add_header("Range", "bytes=0-1024")
        req.add_header("User-Agent", UA_M)
        req.add_header("Referer", BASE)
        try:
            with R.OPENER.open(req, timeout=45) as r:
                data = r.read(1025)
                print("[音频]   %s" % aurl[:110])
                print("         → HTTP %s  %s  %d 字节" % (r.status, r.headers.get("Content-Type"), len(data)))
                print("         Accept-Ranges=%s  Content-Range=%s" % (r.headers.get("Accept-Ranges"), r.headers.get("Content-Range")))
        except Exception as e:
            print("[音频]   ❌ %s" % e)
        # 不带 Referer 试一次，看是否 403
        req2 = urllib.request.Request(aurl)
        req2.add_header("Range", "bytes=0-1024")
        req2.add_header("User-Agent", UA_M)
        try:
            with R.OPENER.open(req2, timeout=45) as r:
                print("         （无 Referer）HTTP %s %s" % (r.status, r.headers.get("Content-Type")))
        except Exception as e:
            print("         （无 Referer）❌ %s" % str(e)[:80])


# --------------------------------------------------------------------------
# ② 搜索探测
# --------------------------------------------------------------------------

def probe_search():
    head("② 搜索探测：验证码 / 限流 / 真实入口")

    kw = "三体"
    q = urllib.parse.quote(kw)

    # 冷会话（无 cookie）GET
    st, hd, raw = get(BASE + "search.php?searchword=" + q, referer=BASE)
    html = text_of(raw, hd)
    print("[冷会话 GET]     HTTP %s  %d 字节  title=%s" % (st, len(raw), title_of(html)))
    print("        需验证码=%s   限流页=%s   /books/ 链接=%d"
          % ("系统安全验证" in html, "搜索限制" in html or "提示信息" in html,
             len(re.findall(r'href="(/books/\d+\.html)"', html))))
    ck = [(c.name, c.value) for c in JAR]
    print("        冷会话拿到 cookie: %s" % ck)
    if "系统安全验证" in html:
        im = re.search(r'src="([^"]*vdimgck[^"]*)"', html)
        act = re.search(r'<form[^>]*action="([^"]*)"', html)
        print("        验证码图 : %s" % (im.group(1) if im else "(无)"))
        print("        表单 action: %s" % (act.group(1) if act else "(无)"))
        # 验证码图长什么样（存盘，人工/后续 OCR 用）
        if im:
            iu = urllib.parse.urljoin(BASE + "search.php", im.group(1))
            st2, hd2, iraw = get(iu, referer=BASE + "search.php?searchword=" + q)
            out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending", "ting22_captcha.jpg")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(iraw)
            print("        验证码图 HTTP %s %s %d 字节 → 存到 %s"
                  % (st2, hd2.get("Content-Type"), len(iraw), out))

    # 冷会话 POST 表单入口
    print()
    print("[POST 搜索]     走 ?scheckAC=check 表单入口")
    body = urllib.parse.urlencode({"searchword": kw}).encode()
    st3, hd3, raw3 = get(BASE + "search.php?scheckAC=check&page=&searchtype=&order=&tid=&area="
                         "&year=&letter=&yuyan=&state=&money=&ver=&jq=",
                         referer=BASE + "search.php?searchword=" + q)
    h3 = text_of(raw3, hd3)
    print("        HTTP %s  %d 字节  title=%s  需验证码=%s"
          % (st3, len(raw3), title_of(h3), "系统安全验证" in h3 or "validate" in h3))

    # 是否别的搜索入口不吃验证码
    print()
    for alt in ["search.php?page=1&searchword=%s&searchtype=" % q,
                "search.php?searchword=%s&searchtype=&page=1" % q,
                "so.php?searchword=%s" % q,
                "search/?searchword=%s" % q,
                "index.php?m=search&searchword=%s" % q]:
        st_a, hd_a, raw_a = get(BASE + alt, referer=BASE)
        ha = text_of(raw_a, hd_a)
        print("        %-52s HTTP %s  %d 字节  title=%-22s 验证=%s 结果=%d"
              % (alt[:52], st_a, len(raw_a), title_of(ha),
                 "系统安全验证" in ha,
                 len(re.findall(r'href="(/books/\d+\.html)"', ha))))
        time.sleep(0.4)


# --------------------------------------------------------------------------
# ②b 验证码 cookie 伪造测试
# --------------------------------------------------------------------------

def probe_forge():
    head("②b 验证码 cookie 伪造：ssea2_search / __ckMd5 是不是会话绑定的")

    kw = "三体"
    q = urllib.parse.quote(kw)
    # 上一次成功过验证码后落下的 cookie（research/22ting/jar.txt）
    KNOWN_MD5 = "db186d3d32eb0a0e"
    cases = [
        ("无 cookie", None),
        ("ssea2_search=ok", "ssea2_search=ok"),
        ("ssea2_search=ok + __ckMd5=<已知值>",
         "ssea2_search=ok; ssea2_search__ckMd5=" + KNOWN_MD5),
        ("__ckMd5=<已知值> only", "ssea2_search__ckMd5=" + KNOWN_MD5),
        ("ssea2_search=ok + __ckMd5=md5('ok')",
         "ssea2_search=ok; ssea2_search__ckMd5=" + __import__("hashlib").md5(b"ok").hexdigest()[:16]),
    ]
    for label, ck in cases:
        try:
            st, hd, raw = get(BASE + "search.php?searchword=" + q, referer=BASE, cookie=ck, tries=2)
        except Exception as e:
            print("        %-38s ❌ %s" % (label, str(e)[:50]))
            continue
        html = text_of(raw, hd)
        print("        %-38s HTTP %s %d 字节 title=%-14s 验证=%s 结果=%d"
              % (label, st, len(raw), title_of(html), "系统安全验证" in html,
                 len(re.findall(r'href="(/books/\d+\.html)"', html))))
        time.sleep(6.5)  # 站点限制搜索 6 秒一次

    # validate 参数是否真校验（乱填能不能过）
    print()
    print("[validate 是否真校验]  POST ?scheckAC=check  validate=999")
    body = urllib.parse.urlencode({"validate": "999", "searchword": kw}).encode()
    st, hd, raw = get(BASE + "search.php?scheckAC=check&page=&searchtype=&order=&tid=&area="
                      "&year=&letter=&yuyan=&state=&money=&ver=&jq=",
                      referer=BASE + "search.php?searchword=" + q, method="POST", body=body, tries=2)
    html = text_of(raw, hd)
    print("        HTTP %s %d 字节  title=%s  验证=%s  结果=%d"
          % (st, len(raw), title_of(html), "系统安全验证" in html,
             len(re.findall(r'href="(/books/\d+\.html)"', html))))


# --------------------------------------------------------------------------
# ③ 用规则引擎跑分类链路（证据）
# --------------------------------------------------------------------------

CANDIDATE = {
    "id": "ting22",
    "name": "22听书",
    "host": HOST,
    "encoding": "utf-8",
    "ua": "mobile",
    "categories": [
        {"title": "玄幻", "url": "{host}/html/221.html", "group": "小说"},
        {"title": "言情", "url": "{host}/html/222.html", "group": "小说"},
        {"title": "都市", "url": "{host}/html/223.html", "group": "小说"},
        {"title": "恐怖", "url": "{host}/html/224.html", "group": "小说"},
        {"title": "惊悚", "url": "{host}/html/225.html", "group": "小说"},
        {"title": "推理", "url": "{host}/html/226.html", "group": "小说"},
        {"title": "武侠", "url": "{host}/html/227.html", "group": "小说"},
        {"title": "历史", "url": "{host}/html/228.html", "group": "小说"},
        {"title": "军事", "url": "{host}/html/229.html", "group": "小说"},
        {"title": "穿越", "url": "{host}/html/2210.html", "group": "小说"},
        {"title": "科幻", "url": "{host}/html/2211.html", "group": "小说"},
        {"title": "网游", "url": "{host}/html/2212.html", "group": "小说"},
        {"title": "评书", "url": "{host}/html/2213.html", "group": "其它"},
        {"title": "戏曲", "url": "{host}/html/2214.html", "group": "其它"},
        {"title": "笑话", "url": "{host}/html/2215.html", "group": "其它"},
        {"title": "儿童", "url": "{host}/html/2216.html", "group": "其它"},
        {"title": "财经", "url": "{host}/html/2217.html", "group": "其它"},
        {"title": "广播", "url": "{host}/html/2218.html", "group": "其它"},
        {"title": "诗歌", "url": "{host}/html/2219.html", "group": "其它"},
        {"title": "文学", "url": "{host}/html/2220.html", "group": "其它"},
        {"title": "粤语", "url": "{host}/html/2221.html", "group": "其它"},
        {"title": "经典", "url": "{host}/html/2222.html", "group": "其它"},
        {"title": "相声小品", "url": "{host}/html/2223.html", "group": "其它"},
        {"title": "百家讲坛", "url": "{host}/html/2224.html", "group": "其它"},
    ],
    "search": {
        "url": "{host}/search.php?page={page}&searchword={kw}&searchtype=",
        "list": "ul.row-b > li",
        "title": "h2 a.f-bold@text",
        "urlRule": "h2 a.f-bold@href",
        "cover": ".img-box img@src",
        "author": "h2 span.fr@text",
        "artist": "p.f-gray@regex(作者：(.*?)，由(.*?)播音,2)",
        "intro": "p.f-gray@text",
    },
    "detail": {
        "episodes": "#yuedu ul.ul-36 li a",
        "episodeTitle": "@title",
        "episodeUrl": "@href",
        "cover": ".style-img img@src",
        "intro": "p.f-gray@regex(内容介绍：(.*))",
        "author": "p.f-gray@regex(作者：(.*?)，由(.*?)播音,1)",
        "artist": "p.f-gray@regex(作者：(.*?)，由(.*?)播音,2)",
    },
    "audio": {
        "type": "regex",
        "pattern": r'var\s+now\s*=\s*"([^"]+)"',
        "referer": "{host}/",
    },
}


def probe_engine():
    head("③ 规则引擎链路：do_menus → 分类第一页 → 第一本 → 章节 → 音频 → 试听")
    rule = CANDIDATE

    menus = R.do_menus(rule)
    print("[do_menus] 共 %d 个分类" % len(menus))
    groups = {}
    for g, t, u in menus:
        groups.setdefault(g, []).append((t, u))
    for g, items in groups.items():
        print("        %s（%d）：%s" % (g, len(items), "、".join(t for t, _ in items)))

    # 分类第一页
    cat_url = menus[0][2]
    print()
    print("[分类第一页] %s" % cat_url)
    html = R.fetch(cat_url, referer=BASE, desktop=False)
    books = R.parse_list(html, {"list": rule["search"]["list"],
                                "title": rule["search"]["title"],
                                "urlRule": rule["search"]["urlRule"],
                                "cover": rule["search"]["cover"],
                                "author": rule["search"]["author"],
                                "artist": rule["search"]["artist"]}, rule)
    print("        → %d 本" % len(books))
    for b in books[:3]:
        print("          %-22s | %s | 作者=%s 播音=%s | %s"
              % (b["title"][:22], b["url"], b["author"], b["artist"], b["cover"][:60]))
    if not books:
        print("        ❌ 分类页没解析出书")
        return
    b = books[0]

    # 章节
    print()
    print("[章节] %s" % b["url"])
    t0 = time.time()
    eps = R.do_detail(rule, b)
    print("        → %d 集（%.1fs）" % (len(eps), time.time() - t0))
    if not eps:
        print("        ❌ 没解析出章节")
        return
    print("        第一集：%s  %s" % (eps[0]["title"], eps[0]["url"]))
    print("        最后一集：%s  %s" % (eps[-1]["title"], eps[-1]["url"]))

    # 音频
    print()
    print("[音频] %s" % eps[0]["url"])
    url, headers = R.do_audio(rule, eps[0])
    print("        → %s" % url)
    print("        请求头：%s" % headers)

    # 试听
    req = urllib.request.Request(url)
    req.add_header("Range", "bytes=0-1024")
    req.add_header("User-Agent", UA_M)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with R.OPENER.open(req, timeout=45) as r:
            data = r.read(1025)
            print("        试听 → HTTP %s  %s  %d 字节  ✅"
                  % (r.status, r.headers.get("Content-Type"), len(data)))
    except Exception as e:
        print("        试听 → ❌ %s" % e)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "raw"):
        probe_raw()
    if which in ("all", "search"):
        probe_search()
    if which in ("all", "forge"):
        probe_forge()
    if which in ("all", "engine"):
        probe_engine()
