# -*- coding: utf-8 -*-
"""恋听网 (ting55) 规则化探测脚本 —— 只用于确认 JSON 规则该写什么选择器/字段。

不修改任何共享文件；纯探测，输出原始片段。

用法：
  python probe_ting55.py            # 全链路
  python probe_ting55.py search     # 只看搜索页结构
"""
import json
import re
import secrets
import ssl
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://m.ting55.com"
UA_M = ("Mozilla/5.0 (Linux; Android 9; SM-S9280) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36")
UA_D = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

RETRIES = 5


def req(url, data=None, headers=None, referer=None, tries=RETRIES):
    h = {"User-Agent": UA_M, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
         "Connection": "close"}
    if referer:
        h["Referer"] = referer
    if data is not None:
        h.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            r = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(r, timeout=30, context=CTX) as resp:
                return resp.status, dict(resp.headers), resp.read(), resp.geturl()
        except Exception as e:
            last = e
            time.sleep(min(0.8 * (i + 1), 4.0))
    raise last


def text(url, **kw):
    st, hd, raw, fin = req(url, **kw)
    return st, hd, raw.decode("utf-8", "replace"), fin


def show(title, s, n=1400):
    print("\n" + "-" * 70)
    print("### " + title)
    print("-" * 70)
    print(s[:n])


def dump():
    """把关键页面存到 %TEMP%\\ting55probe 方便离线比对结构。"""
    import os
    out = os.path.join(os.environ.get("TEMP", "."), "ting55probe")
    os.makedirs(out, exist_ok=True)
    targets = {
        "home.html": BASE + "/",
        "search.html": BASE + "/search/" + urllib.parse.quote("三体", safe=""),
        "category.html": BASE + "/category/1",
        "detail_1367.html": BASE + "/book/1367",
        "ep_1367-1.html": BASE + "/book/1367-1",
    }
    for name, url in targets.items():
        try:
            st, hd, raw, fin = req(url, tries=8)
            with open(os.path.join(out, name), "wb") as f:
                f.write(raw)
            print("OK   %-20s %6d bytes  %s" % (name, len(raw), url))
        except Exception as e:
            print("FAIL %-20s %s: %s" % (name, type(e).__name__, e))
    print("dump 目录：%s" % out)


def sel():
    """用 bs4 试候选选择器（同时参照 App 端 MiniHTML.select 的能力边界）。"""
    import os
    from bs4 import BeautifulSoup
    out = os.path.join(os.environ.get("TEMP", "."), "ting55probe")
    cands = [
        "div.slist > a",
        "div.clist > a",
        "div.slist > a, div.clist > a",
        'a[href*="/book/"]',
        'section div > a[href*="/book/"]',
        'div dl > dt > img',
    ]
    for name in ("search.html", "category.html", "detail_1367.html"):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            print("缺少 %s（先跑 dump）" % p)
            continue
        soup = BeautifulSoup(open(p, encoding="utf-8").read(), "lxml")
        print("\n===== %s =====" % name)
        for c in cands:
            nodes = soup.select(c)
            titles = []
            for n in nodes[:3]:
                href = n.get("href") or ""
                h3 = n.select_one("h3")
                titles.append("%s|%s" % (href, (h3.get_text(" ", strip=True) if h3 else n.get_text(" ", strip=True))[:14]))
            print("  %-42s n=%-3d %s" % (c, len(nodes), titles))


def scan():
    """扫「三体」搜索结果里每本书第 1 集的 /glink 音源域名与可播性。"""
    kw = sys.argv[2] if len(sys.argv) > 2 else "三体"
    surl = "%s/search/%s" % (BASE, urllib.parse.quote(kw, safe=""))
    st, hd, html, fin = text(surl, referer=BASE + "/")
    ids = []
    for href, _bid, txt in re.findall(r'<a href="(/book/(\d+))"[^>]*>.*?<h3[^>]*>(.*?)</h3>', html, re.S):
        ids.append((href, re.sub(r"<[^>]+>", "", txt).replace(" ", "")))
    extra = sys.argv[3:] if len(sys.argv) > 3 else []
    for b in extra:
        ids.append(("/book/" + b, "(手工) " + b))
    print("搜索「%s」命中 %d 条；另加 %d 个手工 book" % (kw, len(ids) - len(extra), len(extra)))
    for href, title in ids:
        bid = href.rsplit("/", 1)[-1]
        ep = "%s%s-1" % (BASE, href)
        try:
            st, hd, ehtml, fin = text(ep, referer=BASE + "/")
            metas = dict(re.findall(r'<meta name="(_[a-zA-Z]+)"\s+content="([^"]*)"', ehtml))
            body = urllib.parse.urlencode({
                "bookId": metas.get("_b", ""), "isPay": metas.get("_h", "0") or "0",
                "page": metas.get("_cp", "1") or "1"}).encode()
            st, hd, raw, fin = req(BASE + "/glink", data=body, referer=ep, headers={
                "xt": metas.get("_c", ""), "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE, "Cookie": "mhting55=" + secrets.token_hex(8)})
            j = json.loads(raw.decode("utf-8", "replace").strip() or "{}")
            aurl = (j.get("ourl") or "") or (j.get("url") or "")
            host = urllib.parse.urlparse(aurl).netloc or "-"
            line = "%-8s %-16s status=%-3s host=%-18s" % (bid, title[:16], j.get("status"), host)
            if aurl:
                try:
                    ast, ahd, araw, afin = req(aurl, referer=ep, tries=2,
                                               headers={"Range": "bytes=0-1024", "User-Agent": UA_D})
                    line += " Range=HTTP %s CT=%s" % (ast, ahd.get("Content-Type"))
                except Exception as e:
                    line += " Range=❌%s" % type(e).__name__
            print(line)
            time.sleep(1.2)
        except Exception as e:
            print("%-8s %-16s ❌ %s: %s" % (bid, title[:16], type(e).__name__, e))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    if only == "dump":
        dump()
        return
    if only == "sel":
        sel()
        return
    if only == "scan":
        scan()
        return

    # ---------- 0. 首页分类 ----------
    if only in ("", "home"):
        st, hd, html, fin = text(BASE + "/")
        print("\n[0] GET %s -> HTTP %s  %d bytes  CT=%s" %
              (BASE + "/", st, len(html), hd.get("Content-Type")))
        m = re.search(r'<nav[^>]*class="[^"]*nav[^"]*"[^>]*>(.*?)</nav>', html, re.S)
        seg = m.group(0) if m else ""
        show("nav 原文", seg, 1200)
        print("nav /category/ 链接：",
              re.findall(r'href="(/category/\d+)"[^>]*>([^<]+)<', seg)[:20])

    # ---------- 1. 搜索 ----------
    kw = "三体"
    surl = "%s/search/%s" % (BASE, urllib.parse.quote(kw, safe=""))
    st, hd, html, fin = text(surl, referer=BASE + "/")
    print("\n[1] GET %s -> HTTP %s  %d bytes  CT=%s" %
          (surl, st, len(html), hd.get("Content-Type")))
    html = sys.modules[__name__].SEARCH_HTML = html

    # 列表容器
    for cls in ("clist", "slist"):
        print("   div.%s 出现次数 = %d" % (cls, html.count('class="%s"' % cls)))
    m = re.search(r'<div class="(?:clist|slist)"[^>]*>', html)
    print("   容器标签：", m.group(0) if m else "(无)")
    # 第一段列表 HTML
    m = re.search(r'<div class="(?:clist|slist)"[^>]*>(.*?)</div>\s*(?:<div class="cpage"|</section>)',
                  html, re.S)
    if m:
        show("搜索列表第一段（前 2 个 <a> 的完整结构）", m.group(1)[:2600])
    else:
        idx = html.find('class="slist"')
        if idx < 0:
            idx = html.find('class="clist"')
        show("搜索页 slist/clist 附近", html[max(0, idx - 200):idx + 2600])

    if only == "search":
        return

    # ---------- 2. 详情 + 章节 ----------
    m = re.search(r'<a href="(/book/(\d+))"', html)
    book = m.group(1) if m else "/book/1367"
    print("\n[2] 详情 %s%s" % (BASE, book))
    st, hd, dhtml, fin = text(BASE + book, referer=BASE + "/")
    print("   HTTP %s  %d bytes" % (st, len(dhtml)))
    m = re.search(r'<div class="binfo">(.*?)</div>', dhtml, re.S)
    show("binfo", m.group(1) if m else "(无)", 1500)
    m = re.search(r'<h2>\s*分集收听[^<]*</h2>', dhtml)
    print("   h2:", m.group(0) if m else "(无)")
    m = re.search(r'<div class="plist">(.*?)</div>', dhtml, re.S)
    show("plist 开头", m.group(1)[:900] if m else "(无)")
    eps = re.findall(r'<a[^>]*href="(/book/\d+-\d+)"[^>]*>(.*?)</a>', dhtml, re.S)
    print("   plist 章节总数 = %d" % len(eps))
    print("   前 3 个：", eps[:3])
    print("   后 3 个：", eps[-3:])

    # ---------- 3. 章节页 meta ----------
    ep_url = BASE + (eps[0][0] if eps else book + "-1")
    print("\n[3] 章节页 %s" % ep_url)
    st, hd, ehtml, fin = text(ep_url, referer=BASE + "/")
    metas = dict(re.findall(r'<meta name="(_[a-zA-Z]+)"\s+content="([^"]*)"', ehtml))
    print("   HTTP %s  metas = %s" % (st, metas))

    # ---------- 4. /glink ----------
    xt = metas.get("_c", "")
    body = urllib.parse.urlencode({
        "bookId": metas.get("_b", ""),
        "isPay": metas.get("_h", "0") or "0",
        "page": metas.get("_cp", "1") or "1",
    }).encode()
    print("\n[4] POST /glink  body=%s" % body.decode())
    st, hd, raw, fin = req(BASE + "/glink", data=body, referer=ep_url, headers={
        "xt": xt, "X-Requested-With": "XMLHttpRequest", "Origin": BASE,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Cookie": "mhting55=" + secrets.token_hex(8),
    })
    txt = raw.decode("utf-8", "replace").strip()
    print("   HTTP %s  CT=%s" % (st, hd.get("Content-Type")))
    print("   BODY: %s" % txt[:600])
    try:
        j = json.loads(txt)
    except Exception as e:
        print("   非 JSON: %s" % e)
        return
    print("   status=%r  type=%s" % (j.get("status"), type(j.get("status")).__name__))
    print("   ourl=%r" % (j.get("ourl") or "")[:120])
    print("   url =%r" % (j.get("url") or "")[:120])
    print("   title(decoded)=%r" % urllib.parse.unquote_plus(j.get("title") or ""))
    aurl = (j.get("ourl") or "") or (j.get("url") or "")
    if not aurl:
        return

    # ---------- 5. Range 试听 ----------
    print("\n[5] Range bytes=0-1024 -> %s" % aurl[:110])
    try:
        st, hd, raw, fin = req(aurl, referer=ep_url,
                               headers={"Range": "bytes=0-1024", "User-Agent": UA_D}, tries=3)
        print("   HTTP %s  CT=%s  CR=%s  bytes=%d  首 16 字节=%r"
              % (st, hd.get("Content-Type"), hd.get("Content-Range"), len(raw), raw[:16]))
    except Exception as e:
        print("   ❌ %s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    main()
