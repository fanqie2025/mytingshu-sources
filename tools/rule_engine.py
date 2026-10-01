# -*- coding: utf-8 -*-
"""规则引擎的 Python 复刻 —— 用来验证 subscription/sources.json 里的规则是否真的走得通。

语义与 App 里的 Swift 实现（Sources/RuleSource.swift）保持一致：
  fill 模板 / POST 搜索 / JS 守卫自动解 / 两步取目录（每步可指定 UA）/
  音频 post（meta 变量、签名、状态校验、重试、地址改写、随机 cookie）/ `^祖先` 取值

用法：python3 tools/rule_engine.py subscription/sources.json [关键词]
"""
import base64
import html as html_mod
import http.cookiejar
import json
import random
import re
import sys
import time
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


def normalize_literal(text):
    """把单引号 JS/Python 对象字面量归一化成 JSON（酷我接口就是这种）"""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"":
            quote = ch
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i:i + 2])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            s = "".join(buf)
            # 单引号里的双引号要转义
            s = s.replace('\\"', '"').replace('"', '\\"')
            out.append('"' + s + '"')
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word = text[i:j]
            k = j
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] == ":":
                out.append('"' + word + '"')
            elif word in ("null", "true", "false"):
                out.append(word)
            else:
                out.append(word)
            i = j
            continue
        if ch in "[{":
            i += 1
            out.append(ch)
            # 去掉「[ ,」/「{ ,」这类尾逗号
            k = i
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k < n and text[k] == ",":
                out.append(text[i:k])
                i = k + 1
                continue
            continue
        out.append(ch)
        i += 1
    s = "".join(out)
    s = re.sub(r",(\s*[\]}])", r"\1", s)   # 尾逗号
    return s


def load_literal(text):
    """字面量 → Python 对象：先归一化再 json.loads，失败退回 ast.literal_eval"""
    try:
        return json.loads(normalize_literal(strip_bom(text)))
    except Exception:
        pass
    try:
        import ast
        return ast.literal_eval(text)
    except Exception:
        return None


def fill(tpl, host, kw=None, page=None, extra=None):
    s = tpl.replace("{host}", host)
    if kw is not None:
        s = s.replace("{kw}", urllib.parse.quote(kw, safe=""))
    if page is not None:
        s = s.replace("{page}", str(page)).replace("{page0}", str(max(0, page - 1)))
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
        s = s.replace("{page}", str(page)).replace("{page0}", str(max(0, page - 1)))
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
            out.extend(n.select(fix_sel(sel)))
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


def strip_bom(t):
    """去掉 UTF-8 BOM —— 有听网的音频接口返回就带 BOM，json.loads 会直接报错"""
    return t.lstrip("\ufeff") if isinstance(t, str) else t


def clean_text(s):
    """文本字段统一清洗：去标签 + 实体 + 再解一层 \\uXXXX（酷我 ft=music 的 ARTIST 是 \\u0026）"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", str(s))
    s = html_mod.unescape(s)
    s = s.replace("\\u0026", "&").replace("\\u002F", "/").replace("\\/", "/")
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace(chr(92) + '&', '&')
    return re.sub(r"\s+", " ", s).strip()


def parse_json_list_obj(obj, lr, host):
    if isinstance(lr.get("items"), str) and lr["items"]:
        got = _any_at(lr["items"], obj)
        arr = got if isinstance(got, list) else []
    elif isinstance(obj, list):
        arr = obj
    elif isinstance(obj, dict):
        arr = []
        for key in ("data", "results", "list", "items"):
            if isinstance(obj.get(key), list):
                arr = obj[key]
                break
    else:
        arr = []

    def pick(paths, node):
        for p in paths:
            if not p:
                continue
            v = _any_at(p, node)
            if v is not None and str(v):
                return str(v)
        return ""

    books, seen = [], set()
    for item in arr:
        node = item
        if lr.get("node"):
            sub = _any_at(lr["node"], item)
            if sub is not None:
                node = sub
        title = clean_text(pick([lr.get("title"), "title", "name"], node))
        url = pick([lr.get("urlRule"), "url", "bookurl"], node)
        if not title or not url:
            continue
        cover = pick([lr.get("cover"), "cover", "pic", "img", "image"], node)
        if cover and lr.get("prefix"):          # 相对封面要在拼绝对地址之前加前缀
            cover = lr["prefix"] + cover
        full = absolute(url, host)
        if lr.get("dedupe"):
            if full in seen:
                continue
            seen.add(full)
        books.append({
            "title": title,
            "url": full,
            "cover": absolute(cover, host),
            "artist": clean_text(pick([lr.get("artist"), "boyin", "artist", "narrator"], node)),
            "author": clean_text(pick([lr.get("author"), "author"], node)),
            "intro": clean_text(pick([lr.get("intro"), "content", "intro", "description"], node)),
        })
    return books


def parse_json_list(text, lr, host):
    """标准 JSON 模式"""
    try:
        obj = json.loads(strip_bom(text))
    except Exception:
        return []
    return parse_json_list_obj(obj, lr, host)


def parse_literal_list(text, lr, host):
    """单引号 JS/Python 字面量模式（酷我 rformat=json 名不副实）"""
    obj = load_literal(text)
    if obj is None:
        return []
    return parse_json_list_obj(obj, lr, host)


def fix_sel(sel):
    """bs4/soupsieve 要求属性值带引号：a[href*=/book/] → a[href*="/book/"]（Swift 侧两种都认）"""
    if not isinstance(sel, str) or "[" not in sel:
        return sel
    return re.sub(r"\[([A-Za-z_:.-]+)([*^$~|]?=)([^\"'\]\[]+)\]",
                  lambda m: '[%s%s"%s"]' % (m.group(1), m.group(2), m.group(3).strip()), sel)


def do_category(rule, cat_url, page=1):
    """分类列表（镜像 Swift 的 books(in:)：支持 apiVars 与 JSON/literal 模式）"""
    lr = rule.get("search") or {}
    host = rule["host"]
    desktop = (lr.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"
    url = cat_url
    variables = {}
    if lr.get("apiVars"):
        page_html = fetch(cat_url, referer=host + "/", desktop=desktop)
        for key, var_name in lr["apiVars"].items():
            m = re.search(r"var\s+%s\s*=\s*['\"]([^'\"]*)['\"]" % re.escape(var_name), page_html)
            variables[key] = m.group(1) if m else ""
        url = fill(lr["url"], host, page=page, extra=variables)
    elif page > 1:
        if lr.get("pageUrl"):
            url = fill(lr["pageUrl"], host, page=page)
        elif "?" in url:
            url = "%s&page=%d" % (url, page)
    text = fetch(url, referer=host + "/", desktop=desktop, headers=lr.get("headers"))
    return parse_list(text, lr, rule)


def parse_list(html, lr, rule):
    host = rule["host"]
    kind = (lr.get("kind") or "html").lower()
    if kind == "json":
        return parse_json_list(html, lr, host)
    if kind == "literal":
        return parse_literal_list(html, lr, host)
    soup = BeautifulSoup(html, "lxml")
    nodes = soup.select(fix_sel(lr["list"]))
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
    kind = (d.get("kind") or "html").lower()
    enc = d.get("encoding") or rule.get("encoding") or "utf-8"
    desktop = (d.get("ua") or rule.get("ua") or "mobile").lower() == "desktop"

    # 详情接口地址：可由 bookURL 正则取变量后拼出来（酷我 bookURL 只带 albumid）
    detail_url = book["url"]
    if d.get("url"):
        vars_ = {}
        for k, pat in (d.get("urlVars") or {}).items():
            m = re.search(pat, book["url"])
            vars_[k] = m.group(1) if m else ""
        detail_url = fill_text(d["url"], host, extra=vars_)
        if not detail_url.startswith("http"):
            detail_url = fill(d["url"], host, extra=vars_)

    html = fetch(detail_url, referer=host + "/", desktop=desktop, encoding=enc)

    if kind in ("json", "literal"):
        obj = json.loads(strip_bom(html)) if kind == "json" else load_literal(strip_bom(html))
        if not isinstance(obj, (dict, list)):
            raise RuntimeError("详情响应不是 %s 结构" % kind)
        arr = _any_at(d["episodes"], obj) or []
        episodes = []
        for it in arr:
            t = clean_text(_any_at(d.get("episodeTitle") or "name", it) or "")
            if d.get("episodeUrlTemplate"):
                # 章节地址要拼出来（站点只给数字 id，书 id 在 detail.urlVars 里）
                ev = dict(vars_)
                for var, path in (d.get("episodeUrlVars") or {}).items():
                    ev[var] = str(_any_at(path, it) or "")
                u = fill_text(d["episodeUrlTemplate"], host, extra=ev)
                if not u.startswith("http"):
                    u = fill(d["episodeUrlTemplate"], host, extra=ev)
            else:
                u = str(_any_at(d.get("episodeUrl") or "url", it) or "")
            if u:
                episodes.append({"title": t, "url": u})
        if d.get("cover"):
            book["cover"] = str(_any_at(d["cover"], obj) or "") or book.get("cover", "")
        if d.get("artist"):
            book["artist"] = clean_text(_any_at(d["artist"], obj) or "")
        if d.get("intro"):
            book["intro"] = clean_text(_any_at(d["intro"], obj) or "")
        return episodes

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
            nodes = psoup.select(fix_sel(d["episodes"]))
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

    nodes = soup.select(fix_sel(d["episodes"]))
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
            if a["type"] == "api":
                # 通用版：从章节地址正则取变量 → 拼接口地址 → GET → 点号路径取值 → 退正则
                variables = {"now": str(int(time.time()))}
                for k, pat in (a.get("urlVars") or {}).items():
                    mm = re.search(pat, ep["url"])
                    variables[k] = mm.group(1) if mm else ""
                api = fill_text(a.get("url", ep["url"]), host, extra=variables)
                if not api.startswith("http"):
                    api = fill(a.get("url", ep["url"]), host, extra=variables)
                text = fetch(api, referer=referer, desktop=desktop, headers=a.get("headers"))
                raw = ""
                if a.get("field"):
                    try:
                        raw = value_at(a["field"], json.loads(strip_bom(text)))
                    except Exception:
                        obj = load_literal(text)
                        if isinstance(obj, (dict, list)):
                            raw = value_at(a["field"], obj)
                if not raw and a.get("fieldAlt"):
                    try:
                        raw = value_at(a["fieldAlt"], json.loads(strip_bom(text)))
                    except Exception:
                        pass
                if not raw and a.get("pattern"):
                    m = re.search(a["pattern"], text)
                    raw = m.group(1) if m else ""
                if not raw:
                    last = "api 没取到地址"
                    continue
                final = absolute(raw, host)
                for pair in (a.get("replace") or []):
                    if len(pair) >= 2:
                        final = final.replace(pair[0], pair[1])
                return final, {"Referer": referer}
            if a["type"] == "pcplayer":
                variables = {"now": str(int(time.time()))}
                for k, pat in (a.get("urlVars") or {}).items():
                    mm = re.search(pat, ep["url"])
                    variables[k] = mm.group(1) if mm else ""
                page_url = fill_text(a.get("url", ep["url"]), host, extra=variables)
                html = fetch(page_url, referer=referer, desktop=True)
                return media_expr_url(html), {"Referer": referer}
            if a["type"] == "post":
                # {now}：请求当刻的 epoch 秒（签名与 URL 必须用同一个值）
                variables = {"now": str(int(time.time()))}
                # 先从章节地址正则取变量（书音FM 的 id/movieId 都从地址里来）
                for k, pat in (a.get("urlVars") or {}).items():
                    mm = re.search(pat, ep["url"])
                    variables[k] = mm.group(1) if mm else ""
                # 只有写了 metaFrom 才需要先拉章节页
                if a.get("metaFrom"):
                    page = fetch(ep["url"], referer=host + "/", desktop=desktop)
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
                    st = value_at(a["statusField"], json.loads(strip_bom(resp) or "{}"))
                    if a.get("statusOK") and st != a["statusOK"]:
                        last = "接口状态 %s ≠ %s（可能被限流）" % (st or "?", a["statusOK"])
                        continue
                raw = ""
                obj = json.loads(strip_bom(resp) or "{}")
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




