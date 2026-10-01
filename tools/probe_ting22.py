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
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
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
        # 验证码图长什么样（存到系统临时目录，方便人工看；不往仓库里塞文件）
        if im:
            iu = urllib.parse.urljoin(BASE + "search.php", im.group(1))
            st2, hd2, iraw = get(iu, referer=BASE + "search.php?searchword=" + q)
            out = os.path.join(tempfile.gettempdir(), "ting22_captcha.jpg")
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
# ②c 验证码会话：分两趟跑，中间由人看一次图（脚本不 OCR）
#     python probe_ting22.py captcha          → 取图存临时目录，打印路径
#     python probe_ting22.py captcha 16       → 用答案过验证码，再验证「换会话还要不要验证」
# --------------------------------------------------------------------------

JAR_FILE = os.path.join(tempfile.gettempdir(), "ting22_probe_cookies.lwp")


def probe_captcha(answer=None):
    head("②c 验证码会话（answer=%s）" % (answer or "未给，只取图"))

    kw = "三体"
    q = urllib.parse.quote(kw)
    jar = http.cookiejar.LWPCookieJar(JAR_FILE)
    if os.path.exists(JAR_FILE):
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def go(url, data=None, referer=BASE):
        req = urllib.request.Request(url, data=data)
        req.add_header("User-Agent", UA_M)
        req.add_header("Referer", referer)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        for i in range(3):
            try:
                with op.open(req, timeout=45) as r:
                    return r.status, dict(r.headers), r.read()
            except Exception as e:
                if i == 2:
                    raise
                print("        … 重试 %d（%s）" % (i + 1, str(e)[:50]))
                time.sleep(3)

    search_url = BASE + "search.php?searchword=" + q
    check_url = (BASE + "search.php?scheckAC=check&page=&searchtype=&order=&tid=&area="
                 "&year=&letter=&yuyan=&state=&money=&ver=&jq=")

    # 注意：每请求一次 vdimgck.php，服务端的验证码就换一次 —— 所以「看图」和「提交」
    # 必须分两趟，且第二趟绝不能再碰图片，否则答案立刻失效。
    if not answer:
        st, hd, raw = go(search_url)
        html = text_of(raw, hd)
        print("        GET 搜索页 → HTTP %s  title=%s  需验证码=%s"
              % (st, title_of(html), "系统安全验证" in html))
        print("        会话 cookie: %s" % [(c.name, c.value) for c in jar])
        im = re.search(r'src="([^"]*vdimgck[^"]*)"', html)
        if not im:
            print("        没有验证码图，可能这个会话已经通过了")
            return
        iu = urllib.parse.urljoin(BASE + "search.php", im.group(1))
        st2, hd2, iraw = go(iu)
        img = os.path.join(tempfile.gettempdir(), "ting22_captcha.jpg")
        with open(img, "wb") as f:
            f.write(iraw)
        jar.save(ignore_discard=True, ignore_expires=True)
        print("        验证码图 %d 字节 → %s（请读出算式）" % (len(iraw), img))
        print("        下一趟：probe_ting22.py captcha <答案>")
        return

    # ---- 第二趟：只提交，不碰图片 ----
    print("        带着会话 cookie 直接提交答案（不重新取图，否则答案失效）")
    print("        会话 cookie: %s" % [(c.name, c.value) for c in jar])
    body = urllib.parse.urlencode({"validate": answer, "searchword": kw}).encode()
    st3, hd3, raw3 = go(check_url, data=body, referer=search_url)
    h3 = text_of(raw3, hd3)
    n3 = len(re.findall(r'href="(/books/\d+\.html)"', h3))
    print("        POST validate=%s → HTTP %s  %d 字节  title=%s  结果=%d"
          % (answer, st3, len(raw3), title_of(h3), n3))
    if n3:
        books = re.findall(r'href="(/books/\d+\.html)"[^>]*class="f-bold"[^>]*>([^<]*)<', h3)
        if not books:
            books = re.findall(r'<a href="(/books/\d+\.html)" class="f-bold">([^<]*)</a>', h3)
        for u, t in books[:5]:
            print("          · %s  %s" % (t, u))
    jar.save(ignore_discard=True, ignore_expires=True)
    print("        过验证后的会话 cookie: %s" % [(c.name, c.value) for c in jar])

    # 同一会话再搜一次（不提交验证码）—— 验证「过一次验证码后本会话是否长期可用」
    time.sleep(7)
    st4, hd4, raw4 = go(search_url)
    h4 = text_of(raw4, hd4)
    print("        同一会话再搜 → HTTP %s  title=%-14s 需验证码=%s 结果=%d"
          % (st4, title_of(h4), "系统安全验证" in h4,
             len(re.findall(r'href="(/books/\d+\.html)"', h4))))

    # 换一个全新会话（不带任何 cookie）再搜一次：验证码是「按会话」还是「按 IP/时间」
    time.sleep(7)
    fresh = http.cookiejar.CookieJar()
    op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(fresh))
    req = urllib.request.Request(search_url)
    req.add_header("User-Agent", UA_M)
    req.add_header("Referer", BASE)
    try:
        with op2.open(req, timeout=45) as r:
            h5 = r.read().decode("utf-8", "replace")
        print("        换全新会话再搜 → HTTP %s  title=%-14s 需验证码=%s 结果=%d"
              % (r.status, title_of(h5), "系统安全验证" in h5,
                 len(re.findall(r'href="(/books/\d+\.html)"', h5))))
    except Exception as e:
        print("        换全新会话再搜 → ❌ %s" % str(e)[:70])


# --------------------------------------------------------------------------
# ②d 换 UA / 换 Referer 能不能绕过验证码（爬虫 UA 白名单常见）
# --------------------------------------------------------------------------

def probe_ua():
    head("②d 换 UA / Referer 能不能绕过验证码（每次都用全新会话）")

    kw = "三体"
    q = urllib.parse.quote(kw)
    uas = [
        ("mobile Chrome", UA_M),
        ("desktop Chrome", UA_D),
        ("Baiduspider", "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)"),
        ("Googlebot", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
        ("Sogou", "Sogou web spider/4.0(+http://www.sogou.com/docs/help/webmasters.htm#07)"),
        ("360Spider", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 360Spider"),
        ("空 UA", ""),
        ("iPhone Safari", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
        ("WeChat", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 MicroMessenger/8.0.44"),
    ]
    for label, ua in uas:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(BASE + "search.php?searchword=" + q)
        if ua:
            req.add_header("User-Agent", ua)
        req.add_header("Referer", BASE)
        try:
            with op.open(req, timeout=45) as r:
                h = r.read().decode("utf-8", "replace")
            n = len(re.findall(r'href="(/books/\d+\.html)"', h))
            print("        %-16s HTTP %s  title=%-16s 验证码=%-5s 结果=%d"
                  % (label, r.status, title_of(h), "系统安全验证" in h, n))
        except Exception as e:
            print("        %-16s ❌ %s" % (label, str(e)[:60]))
        time.sleep(6.5)

    # Referer 各种花样（同会话仍有意义：第一次拿验证码，第二次带不同 Referer）
    print()
    print("[Referer 花样]")
    for label, ref in [("无 Referer", None),
                       ("站内搜索页", BASE + "search.php?searchword=" + q),
                       ("首页", BASE),
                       ("百度", "https://www.baidu.com/")]:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(BASE + "search.php?searchword=" + q)
        req.add_header("User-Agent", UA_M)
        if ref:
            req.add_header("Referer", ref)
        try:
            with op.open(req, timeout=45) as r:
                h = r.read().decode("utf-8", "replace")
            print("        %-16s HTTP %s  title=%-16s 验证码=%-5s 结果=%d"
                  % (label, r.status, title_of(h), "系统安全验证" in h,
                     len(re.findall(r'href="(/books/\d+\.html)"', h))))
        except Exception as e:
            print("        %-16s ❌ %s" % (label, str(e)[:60]))
        time.sleep(6.5)

    # 验证码图响应头里会不会漏答案
    print()
    print("[验证码图响应头]")
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(BASE + "search.php?searchword=" + q)
    req.add_header("User-Agent", UA_M)
    with op.open(req, timeout=45) as r:
        h = r.read().decode("utf-8", "replace")
    req2 = urllib.request.Request(BASE + "include/vdimgck.php")
    req2.add_header("User-Agent", UA_M)
    req2.add_header("Referer", BASE + "search.php?searchword=" + q)
    with op.open(req2, timeout=45) as r:
        print("        HTTP %s" % r.status)
        for k, v in r.headers.items():
            print("          %s: %s" % (k, v))
        print("        图 %d 字节" % len(r.read()))


# --------------------------------------------------------------------------
# ②e 书籍详情页：挑出 author/artist/intro 能用的稳定选择器
#     （两个引擎都是「取第一个命中节点」，所以第一个 p.f-gray 是谁很关键）
# --------------------------------------------------------------------------

def probe_detail(book_url=None):
    head("②e 书籍详情页 p 元素清单 + 候选选择器实测")

    book_url = book_url or (BASE + "books/2220945.html")
    st, hd, raw = get(book_url, referer=BASE)
    html = text_of(raw, hd)
    print("[详情页] %s → HTTP %s  %d 字节  title=%s" % (book_url, st, len(raw), title_of(html)))

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    print()
    print("  详情区所有 <p>（按文档顺序，就是引擎 pool[0] 的取法）：")
    for i, p in enumerate(soup.select("p")):
        cls = " ".join(p.get("class") or [])
        txt = p.get_text(" ", strip=True)
        if not txt:
            continue
        print("    [%2d] class=%-24s %s" % (i, cls[:24], txt[:90]))
        if i > 18:
            print("    …（后面省略）")
            break

    print()
    print("  候选选择器 → 引擎实际会取到的第一个节点文本：")
    print("  （App 的 MiniHTML 只认 tag/.class/#id/[attr]/[attr=v]/[attr*=v]/空格/>，没有伪类，")
    print("    所以只能用 div.style-img.pd10 这个「详情头专属类」把推荐位排除掉）")
    candidates = [
        "p.f-gray@text",
        "p.f-gray@regex(作者：(.*?)，由(.*?)播音,1)",
        "div.style-img.pd10 section > p.f-gray@regex(作者：(.*?)，由(.*?)播音,1)",
        "div.style-img.pd10 section > p.f-gray@regex(作者：(.*?)，由(.*?)播音,2)",
        "div.style-img.pd10 section > p.txt-ov@regex(播音：(.*))",
        "div.style-img.pd10 section > p.f-gray@regex(内容介绍：(.*))",
        "h1.style-title@text",
        "div.style-img.pd10 img@src",
        ".style-img img@src",
        "#yuedu ul.ul-36 li a@title",
        "#yuedu ul.ul-36 li a@href",
    ]
    for c in candidates:
        try:
            v = R.extract(c, [soup])
        except Exception as e:
            v = "<异常 %s>" % str(e)[:40]
        print("    %-62s → %s" % (c, (v or "(空)")[:70]))


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


def load_rule():
    """优先读真正要交付的规则文件；没有就用内置草稿"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending", "ting22.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            rules = json.load(f)
        print("[规则来源] %s（%d 条）" % (p, len(rules)))
        return rules[0]
    print("[规则来源] 内置草稿 CANDIDATE（pending/ting22.json 不存在）")
    return CANDIDATE


def engine_chain(rule, books, label):
    """books → do_detail → do_audio → Range 试听"""
    print()
    print("【%s】%d 本，取第一本走完链路" % (label, len(books)))
    for b in books[:3]:
        print("    · %-24s | %s | 作者=%s 播音=%s"
              % (b["title"][:24], b["url"], b["author"], b["artist"]))
    if not books:
        print("    ❌ 没拿到书")
        return
    b = books[0]

    print()
    print("[② 章节] do_detail(%s)" % b["url"])
    t0 = time.time()
    eps = R.do_detail(rule, b)
    print("    → 章节 %d 集（%.1fs）" % (len(eps), time.time() - t0))
    if not eps:
        print("    ❌ 没解析出章节")
        return
    print("    第一集：%s  →  %s" % (eps[0]["title"], eps[0]["url"]))
    print("    最后一集：%s  →  %s" % (eps[-1]["title"], eps[-1]["url"]))

    print()
    print("[③ 音频] do_audio(%s)" % eps[0]["url"])
    url, headers = R.do_audio(rule, eps[0])
    print("    → %s" % url)
    print("    请求头：%s" % headers)
    if not url:
        print("    ❌ 没取到音频地址")
        return

    print()
    print("[④ 试听] Range bytes=0-1024")
    req = urllib.request.Request(url)
    req.add_header("Range", "bytes=0-1024")
    req.add_header("User-Agent", R.UA_D)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with R.OPENER.open(req, timeout=45) as r:
            data = r.read(1025)
            print("    → HTTP %s  %s  %d 字节  ✅"
                  % (r.status, r.headers.get("Content-Type"), len(data)))
    except Exception as e:
        print("    → ❌ %s" % e)


def probe_engine(mode="category"):
    """用 rule_engine（App 规则引擎的 Python 复刻）+ 真正交付的规则文件跑链路。

    mode=category : 走分类（不需要验证码）
    mode=search   : 走搜索（需要先把「过过验证码的会话」灌进引擎的 cookie jar）
    """
    rule = load_rule()

    if mode == "search":
        head("③b 搜索链路（把过过验证码的会话灌进 rule_engine.JAR，再跑 do_search）")
        jar = http.cookiejar.LWPCookieJar(JAR_FILE)
        if not os.path.exists(JAR_FILE):
            print("    ❌ 没有会话文件 %s，先跑：probe_ting22.py captcha <答案>" % JAR_FILE)
            return
        jar.load(ignore_discard=True, ignore_expires=True)
        n = 0
        for c in jar:
            R.JAR.set_cookie(http.cookiejar.Cookie(
                0, c.name, urllib.parse.quote(c.value, safe=""), None, False,
                c.domain, False, False, "/", True, False, None, False, None, None, {}))
            n += 1
        print("    已灌入 %d 个 cookie：%s" % (n, [(c.name, c.value) for c in jar]))
        print("    注意：这一步只是证明「规则的搜索选择器是对的」，")
        print("          冷会话直接搜索一定会被站点弹验证码（见 ② 段）。")
        print("    站点限制「搜索 6 秒一次」，先等 8 秒避免撞限流…")
        time.sleep(8)
        books = R.do_search(rule, "三体")
        print()
        print("[① 搜索] do_search(三体) → %d 条" % len(books))
        engine_chain(rule, books, "搜索结果")
        return

    head("③a 分类链路：do_menus → 分类第一页 → 第一本 → 章节 → 音频 → 试听")

    menus = R.do_menus(rule)
    print("[do_menus] 共 %d 个分类" % len(menus))
    groups = {}
    for g, t, u in menus:
        groups.setdefault(g, []).append((t, u))
    for g, items in groups.items():
        print("    %s（%d）：%s" % (g, len(items), "、".join(t for t, _ in items)))

    cat_url = menus[0][2]
    print()
    print("[① 分类第一页] %s" % cat_url)
    html = R.fetch(cat_url, referer=BASE, desktop=False)
    lr = rule.get("search") or {}
    books = R.parse_list(html, {"list": lr.get("list"),
                                "title": lr.get("title"),
                                "urlRule": lr.get("urlRule"),
                                "cover": lr.get("cover"),
                                "author": lr.get("author"),
                                "artist": lr.get("artist")}, rule)
    engine_chain(rule, books, "分类第一页")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "raw"):
        probe_raw()
    if which in ("all", "search"):
        probe_search()
    if which in ("all", "forge"):
        probe_forge()
    if which == "ua":
        probe_ua()
    if which == "detail":
        probe_detail(sys.argv[2] if len(sys.argv) > 2 else None)
    if which == "captcha":
        probe_captcha(sys.argv[2] if len(sys.argv) > 2 else None)
    if which in ("all", "engine"):
        probe_engine("category")
    if which == "engine-search":
        probe_engine("search")
