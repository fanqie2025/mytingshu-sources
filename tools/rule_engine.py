# -*- coding: utf-8 -*-
"""规则引擎的 Python 复刻 —— 用来验证 subscription/sources.json 里的规则是否真的走得通。

语义与 App 里的 Swift 实现（Sources/RuleSource.swift）保持一致：
  fill 模板 / POST 搜索 / JS 守卫自动解 / 两步取目录（每步可指定 UA）/
  音频 post（meta 变量、签名、状态校验、重试、地址改写、随机 cookie）/ `^祖先` 取值

用法：python3 tools/rule_engine.py subscription/sources.json [关键词]
"""
import base64
import http.cookiejar
import json
import random
import re
import sys
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

UA_M = "Mozilla/5.0 (Linux; Android 9; SM-S9280) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36"
UA_D = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


# ---------- 守卫 ----------

def solve_guard(html):
    m = re.search(r'var\s+reversed\s*=\s*"([^"]+)"', html)
    if not m:
        return []
    fwd = m.group(1)[::-1]
    fwd += "=" * ((4 - len(fwd) % 4) % 4)
    try:
        js = base64.b64decode(fwd, validate=False).decode("utf-8", "replace")
    except Exception:
        return []
    vars_ = dict(re.findall(r"var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([^']*)'", js))
    via = {}
    expr = r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'([A-Za-z_][A-Za-z0-9_]*)='\s*\+\s*(?:encodeURIComponent\()?([A-Za-z_][A-Za-z0-9_]*)\)?"
    for lhs, cname, var in re.findall(expr, js):
        via[lhs] = (cname, vars_.get(var, ""))
    out = {}
    for e in re.findall(r"document\.cookie\s*=\s*([^;\n]+)", js):
        e = e.strip()
        m1 = re.match(r"'([A-Za-z_][A-Za-z0-9_]*)='\s*\+\s*(?:encodeURIComponent\()?([A-Za-z_][A-Za-z0-9_]*)\)?", e)
        if m1:
            out[m1.group(1)] = vars_.get(m1.group(2), "")
            continue
        m2 = re.match(r"'([A-Za-z_][A-Za-z0-9_]*)=([^;']*)", e)
        if m2:
            out[m2.group(1)] = m2.group(2)
            continue
        m3 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)$", e)
        if m3 and m3.group(1) in via:
            out[via[m3.group(1)][0]] = via[m3.group(1)][1]
    return list(out.items())


def set_cookie(name, value, netloc):
    JAR.set_cookie(http.cookiejar.Cookie(0, name, urllib.parse.quote(value, safe=""), None, False,
                                        netloc, False, False, "/", True, False, None, False, None, None, {}))


# ---------- 请求 ----------

def fetch(url, method="get", body=None, headers=None, referer=None, desktop=False, encoding="utf-8", retries=2):
    h = dict(headers or {})
    if referer:
        h.setdefault("Referer", referer)
    h["User-Agent"] = UA_D if desktop else UA_M

    def once():
        data = body.encode() if (method == "post" and body is not None) else None
        if data is not None:
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req = urllib.request.Request(url, data=data)
        for k, v in h.items():
            req.add_header(k, v)
        with OPENER.open(req, timeout=45) as r:
            raw = r.read()
        return raw.decode(encoding, "replace")

    text = once()
    left = retries
    netloc = urllib.parse.urlparse(url).netloc
    while left > 0 and "var reversed" in text:
        cookies = solve_guard(text)
        if not cookies:
            break
        for n, v in cookies:
            set_cookie(n, v, netloc)
        text = once()
        left -= 1
    return text


def fill(tpl, host, kw=None, page=None, extra=None):
    s = tpl.replace("{host}", host)
    if kw is not None:
        s = s.replace("{kw}", urllib.parse.quote(kw, safe=""))
    if page is not None:
        s = s.replace("{page}", str(page))
    for k, v in (extra or {}).items():
        s = s.replace("{%s}" % k, v)
    if s.startswith("http"):
        return s
    if s.startswith("/"):
        return host.rstrip("/") + s
    return host.rstrip("/") + "/" + s


def fill_text(tpl, host, kw=None, page=None, extra=None):
    """只替换变量，**不补 host** —— 表单体/请求头不是 URL"""
    s = tpl.replace("{host}", host)
    if kw is not None:
        s = s.replace("{kw}", urllib.parse.quote(kw, safe=""))
    if page is not None:
        s = s.replace("{page}", str(page))
    for k, v in (extra or {}).items():
        s = s.replace("{%s}" % k, v)
    return s


def absolute(u, host):
    if not u:
        return ""
    if u.startswith("http"):
        return u
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return host.rstrip("/") + u
    return host.rstrip("/") + "/" + u


# ---------- 取值 ----------

def extract(rule, nodes):
    sel, _, acc = rule.partition("@")
    sel = sel.strip()
    acc = acc.strip() or "text"
    pool = nodes
    if sel.startswith("^"):
        rest = sel[1:]
        tag, _, remain = rest.partition(" ")
        climbed = []
        for n in nodes:
            p = n.find_parent(tag)
            if p is not None:
                climbed.append(p)
        if climbed:
            pool = climbed
            sel = remain.strip()
    if sel:
        out = []
        for n in pool:
            out.extend(n.select(sel))
        pool = out
    if not pool:
        return ""
    node = pool[0]
    if acc == "text":
        return node.get_text(" ", strip=True)
    if acc == "ownText":
        return "".join(node.find_all(string=True, recursive=False)).strip()
    if acc == "html":
        return node.decode_contents()
    if acc.startswith("attr("):
        return node.get(acc[5:-1], "") or ""
    if acc.startswith("regex("):
        inner = acc[6:-1]
        pattern, _, g = inner.rpartition(",")
        try:
            group = int(g)
        except ValueError:
            pattern, group = inner, 1
        m = re.search(pattern, node.get_text(" ", strip=True))
        return m.group(group) if m else ""
    return node.get(acc, "") or ""


def meta(name, html):
    m = re.search(r'<meta[^>]*name=["\']%s["\'][^>]*content=["\']([^"\']*)' % re.escape(name), html)
    if not m:
        m = re.search(r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']%s["\']' % re.escape(name), html)
    return m.group(1) if m else ""


def value_at(path, obj):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return ""
    return "" if cur is None else str(cur)


# ---------- 引擎 ----------

def do_menus(rule):
    """动态分类导航：从分类大全页按分组抓出来"""
    cf = rule.get("categoriesFrom")
    if not cf:
        return [(c.get("group") or "分类", c["title"], fill(c["url"], rule["host"]))
                for c in (rule.get("categories") or [])]
    host = rule["host"]
    desktop = (cf.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"
    html = fetch(fill(cf["url"], host), referer=host + "/", desktop=desktop)
    soup = BeautifulSoup(html, "lxml")
    out = []
    for g in soup.select(cf["group"]):
        gname = extract(cf.get("groupTitle") or "dt@text", [g]) or "分类"
        for a in g.select(cf["item"]):
            t = extract(cf.get("title") or "@text", [a])
            u = extract(cf.get("urlRule") or "@href", [a])
            if t and u:
                out.append((gname, t, absolute(u, host)))
    return out


def do_search(rule, kw, page=1):
    lr = rule.get("search")
    if not lr:
        return []
    host = rule["host"]
    url = fill(lr["url"], host, kw=kw, page=page)
    method = (lr.get("method") or "get").lower()
    body = None
    if method == "post":
        body = fill_text(lr.get("body") or "searchword={kw}", host, kw=kw, page=page)
    desktop = (lr.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"
    html = fetch(url, method=method, body=body, headers=lr.get("headers"),
                 referer=host + "/", desktop=desktop,
                 encoding=lr.get("encoding") or rule.get("encoding") or "utf-8")
    return parse_list(html, lr, rule)


def _any_at(path, obj):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def parse_json_list(text, lr, host):
    """JSON 接口模式：字段写点号路径；一条规则兼容 {data:[...]} 与 [{novel:{...}}] 两种形态"""
    try:
        obj = json.loads(text)
    except Exception:
        return []
    arr = []
    if lr.get("items"):
        got = _any_at(lr["items"], obj)
        arr = got if isinstance(got, list) else []
    elif isinstance(obj, list):
        arr = obj
    elif isinstance(obj, dict):
        for key in ("data", "results", "list", "items"):
            if isinstance(obj.get(key), list):
                arr = obj[key]
                break

    def pick(paths, node):
        for p in paths:
            if not p:
                continue
            v = _any_at(p, node)
            if v is not None and str(v):
                return str(v)
        return ""

    books = []
    for item in arr:
        node = item
        if lr.get("node"):
            sub = _any_at(lr["node"], item)
            if sub is not None:
                node = sub
        title = pick([lr.get("title"), "title", "name"], node)
        url = pick([lr.get("urlRule"), "url", "bookurl"], node)
        if not title or not url:
            continue
        books.append({
            "title": title,
            "url": absolute(url, host),
            "cover": absolute(pick([lr.get("cover"), "cover", "pic", "img", "image"], node), host),
            "artist": pick([lr.get("artist"), "boyin", "artist", "narrator"], node),
            "author": pick([lr.get("author"), "author"], node),
            "intro": pick([lr.get("intro"), "content", "intro", "description"], node),
        })
    return books


def parse_list(html, lr, rule):
    host = rule["host"]
    if (lr.get("kind") or "html").lower() == "json":
        return parse_json_list(html, lr, host)
    soup = BeautifulSoup(html, "lxml")
    nodes = soup.select(lr["list"])
    books = []
    for node in nodes:
        title = extract(lr["title"], [node])
        if not title:
            continue
        url = extract(lr.get("urlRule", ""), [node]) if lr.get("urlRule") else ""
        if not url:
            url = extract(lr["title"].replace("@text", "@href"), [node])
        if not url:
            continue
        books.append({
            "title": title,
            "url": absolute(url, host),
            "cover": absolute(extract(lr["cover"], [node]), host) if lr.get("cover") else "",
            "artist": extract(lr["artist"], [node]) if lr.get("artist") else "",
            "author": extract(lr["author"], [node]) if lr.get("author") else "",
        })
    return books


def do_detail(rule, book):
    d = rule.get("detail")
    if not d:
        return []
    host = rule["host"]
    enc = d.get("encoding") or rule.get("encoding") or "utf-8"
    desktop = (d.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"
    html = fetch(book["url"], referer=host + "/", desktop=desktop, encoding=enc)
    soup = BeautifulSoup(html, "lxml")

    if d.get("dirUrl"):
        path = extract(d["dirUrl"], [soup])
        if not path:
            raise RuntimeError("详情页没找到目录入口")
        dir_url = absolute(path, host)
        dir_desktop = (d.get("dirUA") or d.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"
        episodes, seen, page_no = [], set(), 1
        max_page = (d.get("pages") or {}).get("max", 60)
        while page_no <= max_page:
            if d.get("pages"):
                url = fill(d["pages"]["url"], host, page=page_no, extra={"dir": dir_url})
            elif page_no == 1:
                url = dir_url
            else:
                url = dir_url + ("&" if "?" in dir_url else "?") + "page=%d" % page_no
            page_html = fetch(url, referer=book["url"], desktop=dir_desktop, encoding=enc)
            psoup = BeautifulSoup(page_html, "lxml")
            nodes = psoup.select(d["episodes"])
            added = 0
            for n in nodes:
                t = extract(d.get("episodeTitle") or "@text", [n])
                u = extract(d.get("episodeUrl") or "@href", [n]) or n.get("href", "")
                if not u or u in seen:
                    continue
                seen.add(u)
                episodes.append({"title": t, "url": absolute(u, host)})
                added += 1
            if added == 0:
                break
            if not d.get("pages") and len(nodes) < 50:
                break
            page_no += 1
        return episodes

    nodes = soup.select(d["episodes"])
    out = []
    for n in nodes:
        t = extract(d.get("episodeTitle") or "@text", [n])
        u = extract(d.get("episodeUrl") or "@href", [n]) or n.get("href", "")
        if u:
            out.append({"title": t, "url": absolute(u, host)})
    return out


def media_expr_url(html):
    """求值 PC 播放页里 `mp3:` 的字符串拼接表达式（29听书网）—— 与 Swift 侧同算法"""
    assign = r"(?:var\s+)?([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*['\"]([^'\"]*)['\"]"
    variables = dict(re.findall(assign, html))
    m = re.search(r"\bmp3\s*:\s*([^\n\r]+)", html)
    if m:
        expr = m.group(1).split(",")[0]
        parts, buf, quote = [], "", None
        for ch in expr:
            if quote:
                if ch == quote:
                    quote = None
                buf += ch
            elif ch in "'\"":
                quote = ch
                buf += ch
            elif ch == "+":
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        parts.append(buf)
        out, ok = "", True
        for p in parts:
            t = p.strip()
            if not t:
                continue
            if t[0] in "'\"":
                out += t[1:-1] if len(t) >= 2 else ""
            elif t in variables:
                out += variables[t]
            else:
                ok = False
                break
        if ok and out.startswith("http"):
            return out
    m2 = re.search(r"(https?://[^'\"\s<>]+\.(?:mp3|m4a|aac))", html)
    return m2.group(1) if m2 else ""


def make_sign(sg, text):
    kind = sg["kind"]
    if kind == "ptcmsSp":
        alpha = sg.get("alphabet") or "PXhw7U1B0a9kQDKZsTjIASmOeNzxYG4CHo1JyRfg2b8FLpEvr3FtVnlqMidu6c"
        out = ""
        for ch in text:
            i = alpha.find(ch)
            if i >= 0:
                out += random.choice(alpha) + alpha[(i + 3) % len(alpha)] + random.choice(alpha)
            else:
                out += "".join(random.choice(alpha) for _ in range(3))
        return out
    if kind == "md5":
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()
    if kind == "base64Quote":
        return base64.b64encode(urllib.parse.quote(text, safe="").encode()).decode()
    return text


def do_audio(rule, ep):
    a = rule.get("audio")
    host = rule["host"]
    if not a:
        return ep["url"], {}
    referer = (a.get("referer") or "{host}/").replace("{host}", host).replace("{episodeUrl}", ep["url"])
    desktop = (a.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"
    tries = max(1, a.get("retries", 1))
    last = None
    for _attempt in range(tries):
        if _attempt > 0 and a.get("retryDelayMs"):
            import time as _t; _t.sleep(a["retryDelayMs"] / 1000.0)
        try:
            if a["type"] == "direct":
                return ep["url"], {"Referer": referer}
            if a["type"] == "regex":
                html = fetch(ep["url"], referer=referer, desktop=desktop)
                m = re.search(a["pattern"], html)
                return (m.group(1) if m else "").replace("\\/", "/"), {"Referer": referer}
            if a["type"] == "pcplayer":
                variables = {}
                for k, pat in (a.get("urlVars") or {}).items():
                    mm = re.search(pat, ep["url"])
                    variables[k] = mm.group(1) if mm else ""
                page_url = fill_text(a.get("url", ep["url"]), host, extra=variables)
                html = fetch(page_url, referer=referer, desktop=True)
                return media_expr_url(html), {"Referer": referer}
            if a["type"] == "post":
                page = fetch(ep["url"], referer=host + "/", desktop=desktop)
                variables = {}
                for key, meta_name in (a.get("metaFrom") or {}).items():
                    variables[key] = meta(meta_name, page)
                for k, v in (a.get("metaDefaults") or {}).items():
                    if not variables.get(k):
                        variables[k] = v
                body = a.get("body", "")
                for k, v in variables.items():
                    body = body.replace("{%s}" % k, v)
                headers = {}
                for k, v in (a.get("headers") or {}).items():
                    vv = v
                    for kk, vv2 in variables.items():
                        vv = vv.replace("{%s}" % kk, vv2)
                    headers[k] = vv
                headers["Referer"] = referer
                headers.setdefault("X-Requested-With", "XMLHttpRequest")
                if a.get("sign"):
                    sg = a["sign"]
                    text = sg.get("input", "")
                    for k, v in variables.items():
                        text = text.replace("{%s}" % k, v)
                    sig = make_sign(sg, text)
                    if sg.get("var"):
                        # 放进变量，重新渲染一次 body（乐听：{"encodedData":"{enc}"}）
                        variables[sg["var"]] = sig
                        body = a.get("body", "")
                        for k, v in variables.items():
                            body = body.replace("{%s}" % k, v)
                    elif sg.get("header"):
                        headers[sg["header"]] = sig
                    else:
                        body += ("&" if body else "") + "%s=%s" % (sg.get("param", "sp"), sig)
                for name, val in (a.get("cookies") or {}).items():
                    v = "".join(random.choice("0123456789abcdef") for _ in range(16)) if val == "randHex16" else val
                    set_cookie(name, v, urllib.parse.urlparse(host).netloc)
                api = fill(a.get("url", ep["url"]), host)
                for k, v in variables.items():
                    api = api.replace("{%s}" % k, v)
                if (a.get("contentType") or "form").lower() == "json":
                    req = urllib.request.Request(api, data=body.encode())
                    for k, v in headers.items():
                        req.add_header(k, v)
                    req.add_header("Content-Type", "application/json; charset=utf-8")
                    req.add_header("User-Agent", UA_D if desktop else UA_M)
                    with OPENER.open(req, timeout=45) as r:
                        resp = r.read().decode("utf-8", "replace")
                else:
                    resp = fetch(api, method="post", body=body, headers=headers,
                                 referer=referer, desktop=desktop)
                if a.get("statusField"):
                    st = value_at(a["statusField"], json.loads(resp or "{}"))
                    if a.get("statusOK") and st != a["statusOK"]:
                        last = "接口状态 %s ≠ %s（可能被限流）" % (st or "?", a["statusOK"])
                        continue
                raw = ""
                obj = json.loads(resp or "{}")
                if a.get("field"):
                    raw = value_at(a["field"], obj)
                if not raw and a.get("fieldAlt"):
                    raw = value_at(a["fieldAlt"], obj)
                if not raw:
                    last = "按规则没取到音频地址"
                    continue
                final = absolute(raw, host)
                for pair in (a.get("replace") or []):
                    if len(pair) >= 2:
                        final = final.replace(pair[0], pair[1])
                final = urllib.parse.quote(final, safe=":/?&=%@#[]!$'()*+,;~")
                return final, {"Referer": referer}
        except Exception as e:
            last = str(e)
    raise RuntimeError(last or "取音频失败")

