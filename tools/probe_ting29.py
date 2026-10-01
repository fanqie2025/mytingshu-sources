# -*- coding: utf-8 -*-
"""29听书网（m.ting29.com + www.ting29.com）完整链路 —— 独立探测脚本。

目的：在把 ting29 迁移成 JSON 书源规则之前，把整条链路每一步单独跑通，
并把「引擎目前表达不了的那一步」精确定位出来。

只读脚本：不写任何文件、不改任何东西。除「守卫自动解」外不依赖引擎能力；
**第 ⑦ 步（PC 播放页 `mp3:` 拼接表达式求值）完全自己实现**，免得用待验证的引擎去证明规则成立。

步骤：
  ① 分类导航      GET {m}/sort/                       → dl.pd-class 分组数 / 分类数（校验 categoriesFrom 选择器）
  ② 分类页变量    GET {m}/book/{slug}/lastupdate.html  → var __API_SORT/__API_KEY/__API_TG/__API_ORDER（apiVars）
  ③ 分类 JSON     GET {m}/api/ajax/list?sort=&key=&tg=&order=&page=
  ④ 搜索 JSON     GET {m}/api/ajax/solist?word={kw}&type=name&page=1&order=1
  ⑤ 书籍页        GET {m}/book/{id}.html               → 标题 / 播音 / 目录入口 a.dirurl
  ⑥ 目录页        GET {m}/bookdir/{h1}/{h2}.html       （JS Cookie 守卫，借用引擎的自动解）
  ⑦ PC 播放页     GET {p}/player.html?nid=&cid=&site=16 → 求值 `mp3:` 拼接表达式（本脚本自实现）
  ⑧ 试听          Range: bytes=0-1024 → HTTP 状态 / Content-Type / Content-Range / magic

用法：
  python tools/probe_ting29.py [关键词] [--book 22801] [--no-search]
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # 让脚本在任何目录下都能 import 到 rule_engine
sys.stdout.reconfigure(encoding="utf-8")

import rule_engine as R           # 只借用：统一 UA / 共享 CookieJar / 守卫自动解

try:
    from bs4 import BeautifulSoup
except ImportError:               # pragma: no cover
    BeautifulSoup = None

M_HOST = "https://m.ting29.com"
PC_HOST = "https://www.ting29.com"
M_UA = R.UA_M
D_UA = R.UA_D

RESULTS = []


# ══════════════════════════════════════════════════════════════════════
# 第 ⑦ 步的核心：求值 `mp3:` 那个字符串拼接表达式（自己实现，不用引擎）
# ══════════════════════════════════════════════════════════════════════

# 收「变量 = 表达式」。注意站点两种写法都有：`var x = '...'` 与裸赋值 `x = '...'`。
_ASSIGN_RE = re.compile(r"(?:var\s+|let\s+|const\s+)?([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+)")
# 兜底：全文找第一个音频地址
_FALLBACK_RE = re.compile(r"(https?://[^'\"\s<>]+\.(?:mp3|m4a|aac))", re.I)
# 求值结果必须长这样才算「完整音频地址」
_MEDIA_URL_RE = re.compile(r"^https?://.+\.(?:mp3|m4a|aac)(?:\?.*)?$", re.I)


def collect_assignments(html):
    """页面里所有 `x = '...'`（有/无 var 都收）→ {变量名: 表达式文本}。

    JS 语义是后写覆盖先写，所以这里也取最后一次出现。
    """
    out = {}
    for m in _ASSIGN_RE.finditer(html):
        out[m.group(1)] = m.group(2).strip()
    return out


def _cut(tail, break_newline):
    """截出 `mp3:` 后面那一整段表达式。

    顶层 `,` `}` `;`（可选 `\\n`）即止 —— 引号内的这些字符不算（URL 里可能带逗号）。
    """
    buf, quote, i = "", None, 0
    stop = ",}\n;" if break_newline else ",};"
    while i < len(tail):
        ch = tail[i]
        if quote:
            if ch == "\\" and i + 1 < len(tail):
                buf += ch + tail[i + 1]
                i += 2
                continue
            if ch == quote:
                quote = None
            buf += ch
        elif ch in "'\"":
            quote = ch
            buf += ch
        elif ch in stop:
            break
        else:
            buf += ch
        i += 1
    return buf


def split_top_plus(expr):
    """按**顶层** `+` 拆开 —— 引号内的 `+` 不拆。

    这是本步最容易写错的地方：不能拿「首尾都是引号」当字面量判据，
    否则 `'https://…G3'+murlNNN+''` 首尾都是 `'`，会被整段误判成一个字面量。
    """
    parts, buf, quote, i = [], "", None, 0
    while i < len(expr):
        ch = expr[i]
        if quote:
            if ch == "\\" and i + 1 < len(expr):
                buf += ch + expr[i + 1]
                i += 2
                continue
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
        i += 1
    parts.append(buf)
    return parts


_UNESCAPE = (("\\/", "/"), ("\\'", "'"), ('\\"', '"'), ("\\\\", "\\"))


def _unquote(s):
    """字符串字面量去引号（先按顶层 + 拆完再调，所以这里首尾是引号就是真字面量）。"""
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        s = s[1:-1]
    elif s[:1] in ("'", '"'):
        s = s[1:]
    for a, b in _UNESCAPE:
        s = s.replace(a, b)
    return s


def eval_expr(expr, assigns, depth=0, seen=None):
    """逐段求值并拼接：字面量去引号 / 变量递归查表。任一段解不出 → None（整条作废）。"""
    if depth > 8:
        return None
    seen = seen or frozenset()
    out = ""
    for seg in split_top_plus(expr):
        t = seg.strip()
        if not t:
            continue
        if t[0] in "'\"":
            out += _unquote(t)
            continue
        raw = assigns.get(t)
        if raw is None or t in seen:
            return None
        sub = eval_expr(_cut(raw, True), assigns, depth + 1, seen | {t})
        if sub is None:
            return None
        out += sub
    return out


def resolve_media_url(html):
    """返回 info dict：url / method / expr / segments / attempts / vars。"""
    info = {"url": "", "method": "", "expr": "", "segments": [], "attempts": [],
            "vars": 0, "assigns": {}}
    assigns = collect_assignments(html)
    info["vars"] = len(assigns)
    info["assigns"] = assigns

    m = re.search(r"\bmp3\s*:\s*", html)
    if m:
        tail = html[m.end():]
        for break_nl in (False, True):
            raw = _cut(tail, break_nl).strip()
            if not raw:
                continue
            got = eval_expr(raw, assigns)
            info["attempts"].append({"expr": raw, "breakNewline": break_nl, "value": got})
            if got and _MEDIA_URL_RE.match(got):
                info.update(url=got, method="求值 mp3: 拼接表达式", expr=raw,
                            segments=[s.strip() for s in split_top_plus(raw)])
                return info
        if info["attempts"]:
            info["expr"] = info["attempts"][0]["expr"]
            info["segments"] = [s.strip() for s in split_top_plus(info["expr"])]

    fb = _FALLBACK_RE.search(html)
    if fb:
        info.update(url=fb.group(1), method="兜底：全文首个音频地址")
    else:
        info["method"] = "没解析出音频地址"
    return info


def _selftest():
    """用文档里实录的 3 种形态自测求值器（不联网）。

    形态 A：murl 裸赋值放扩展名
    形态 B：url 变量本身就是一个拼接表达式
    形态 C：url 变量是空串
    另外验证两个坑：murl 不能被 url(\\d+) 误匹配；首尾引号不能当字面量判据。
    """
    cases = [
        ("A",
         "var url4399227830;\nmurl4399227830 = '.mp3';\n"
         "url4399227830 = 'https://car-er.kuwo.cn/aa/bb/resource/30106/trackmedia/long/M500003Igy1H1JW3G3';\n"
         "setMedia({mp3:'https://car-er.kuwo.cn/aa/bb/resource/30106/trackmedia/long/M500003Igy1H1JW3G3'+murl4399227830+'',poster:'x.jpg'});",
         "https://car-er.kuwo.cn/aa/bb/resource/30106/trackmedia/long/M500003Igy1H1JW3G3.mp3"),
        ("B",
         "murl5822192099 = '.mp3';\nurl5822192099 = ''+murl5822192099+'';\n"
         "setMedia({mp3:'https://car-er.kuwo.cn/aa/bb/M500003Igy1H1JW3G3'+url5822192099+''});",
         "https://car-er.kuwo.cn/aa/bb/M500003Igy1H1JW3G3.mp3"),
        ("C",
         "murl3984240945 = '.mp3';\nurl3984240945 = '';\n"
         "setMedia({mp3:'https://car-er.kuwo.cn/cc/dd/M500003k65YI22PTtu'+murl3984240945+''});",
         "https://car-er.kuwo.cn/cc/dd/M500003k65YI22PTtu.mp3"),
        ("D(整条地址在变量里)",
         "var u1234567890 = 'https://car-er.kuwo.cn/ee/ff/M5000x.mp3';\n"
         "setMedia({mp3:''+u1234567890+''});",
         "https://car-er.kuwo.cn/ee/ff/M5000x.mp3"),
    ]
    lines, all_ok = [], True
    for name, html, want in cases:
        got = resolve_media_url(html)
        ok = got["url"] == want
        all_ok = all_ok and ok
        lines.append("       形态 %-16s %s  %s" % (name, "[OK]" if ok else "[!!]",
                                                got["url"] or got["method"]))
    # url(\d+) 误匹配 murl(\d+) 的坑
    bad = re.search(r"url(\d+)", "murl4399227830").group(1)
    good = re.search(r"(?:^|[^A-Za-z0-9_])url(\d+)", "murl4399227830")
    lines.append("       url(\\d+) 误匹配 murl：裸正则命中 '%s'，加边界后 %s"
                 % (bad, "不命中 [OK]" if good is None else "仍命中 [!!]"))
    all_ok = all_ok and good is None
    return all_ok, lines


# ══════════════════════════════════════════════════════════════════════
# 小工具
# ══════════════════════════════════════════════════════════════════════

def head(title):
    print("\n" + "─" * 72)
    print(title)
    print("─" * 72)


def rec(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("   %s %s%s" % ("[OK]" if ok else "[!!]", name, ("   —— " + detail) if detail else ""))
    return ok


def robust(fn, tries=4, delays=(2, 4, 6)):
    """Cloudflare 会偶发连接重置 / 502（文档坑 12），所以连接层自己退避重试。

    注意：引擎的 fetch 只在「守卫页」时重放，对连接异常不重试 —— 这里补上。
    """
    last = None
    time.sleep(1.2)   # 站点对突发请求敏感（文档坑 12），每次网络动作之间留点间隔
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < tries - 1:
                print("       [..] 第 %d 次失败：%s（%d 秒后重试）"
                      % (i + 1, str(e)[:70], delays[min(i, len(delays) - 1)]))
                time.sleep(delays[min(i, len(delays) - 1)])
    raise last


def guarded_fetch(url, **kw):
    """借用引擎的 fetch：先裸抓一次看是不是守卫页，再让它自动解并重放。

    返回 (text, guard_hit)。守卫页判定：body 里有 `var reversed`。
    """
    raw = robust(lambda: R.fetch(url, retries=0, **kw))
    guard = "var reversed" in raw
    if guard:
        raw = robust(lambda: R.fetch(url, retries=3, **kw))
    return raw, guard


def fetch_json(url, **kw):
    text, guard = guarded_fetch(url, **kw)
    try:
        return json.loads(text), text, guard
    except Exception:
        return None, text, guard


def snip(s, n=180):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s[:n] + ("…" if len(s) > n else "")


# ══════════════════════════════════════════════════════════════════════
# 各步
# ══════════════════════════════════════════════════════════════════════

def main():
    argv = sys.argv[1:]
    kw = "三体"
    book_id = None
    do_search = True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--book" and i + 1 < len(argv):
            book_id = argv[i + 1]; i += 2; continue
        if a == "--no-search":
            do_search = False; i += 1; continue
        kw = a; i += 1

    print("29听书网 完整链路探测   %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("  m 站 : %s" % M_HOST)
    print("  PC 站: %s   （音频入口，/player.html 只在 www 上有）" % PC_HOST)
    print("  关键词: %s" % kw)

    # ────────────────────────────────────────────────────────────────
    head("① 分类导航  GET {m}/sort/   （校验 categoriesFrom 的选择器）")
    cats = []
    try:
        html, _ = guarded_fetch(M_HOST + "/sort/", referer=M_HOST + "/")
        if BeautifulSoup is None:
            rec("分类导航", False, "没装 bs4，跳过")
        else:
            soup = BeautifulSoup(html, "lxml")
            groups = soup.select("dl.pd-class")
            print("       页面 %d 字节 / %d 个 dl.pd-class" % (len(html), len(groups)))
            for g in groups:
                dt = g.select_one("dt a")
                gname = dt.get_text(" ", strip=True) if dt else "分类"
                items = g.select("dd a")
                print("         · 分组「%s」%d 个分类" % (gname, len(items)))
                for a in items:
                    href = a.get("href") or ""
                    if not href.startswith("/book/"):
                        continue
                    cats.append({"group": gname,
                                 "title": a.get("title") or a.get_text(" ", strip=True),
                                 "slug": href.split("/")[2] if len(href.split("/")) > 2 else "",
                                 "url": M_HOST + href})
            rec("分类导航 %d 个分组 / %d 个分类（取到 slug）" % (len(groups), len(cats)),
                bool(cats), "首个：" + (cats[0]["title"] + " → " + cats[0]["url"]) if cats else "")
    except Exception as e:
        rec("分类导航", False, "异常：%s" % e)

    # ────────────────────────────────────────────────────────────────
    head("② 分类页内联变量 + ③ 分类 JSON 接口")
    cat_page = cats[0] if cats else {"slug": "khjj", "title": "科幻竞技",
                                     "url": M_HOST + "/book/khjj/lastupdate.html"}
    api = {}
    try:
        html, _ = guarded_fetch(cat_page["url"], referer=M_HOST + "/")
        print("       分类页：%s（%d 字节）" % (cat_page["url"], len(html)))
        for name in ("__API_SORT", "__API_PAGE", "__API_KEY", "__API_TG", "__API_ORDER"):
            m = re.search(r"var\s+%s\s*=\s*['\"]([^'\"]*)['\"]" % re.escape(name), html)
            api[name] = m.group(1) if m else ""
        print("       var __API_SORT=%r __API_PAGE=%r __API_KEY=%r __API_TG=%r __API_ORDER=%r"
              % (api["__API_SORT"], api["__API_PAGE"], api["__API_KEY"],
                 api["__API_TG"], api["__API_ORDER"]))
        rec("分类页读出 apiVars（key=%s）" % (api["__API_KEY"] or "?"), bool(api["__API_KEY"]),
            "→ 这条 slug 的 key 就来自这里，不能硬编码")
    except Exception as e:
        rec("分类页内联变量", False, "异常：%s" % e)

    if api.get("__API_KEY"):
        try:
            list_url = ("%s/api/ajax/list?sort=%s&key=%s&tg=%s&order=%s&page=1"
                        % (M_HOST, api["__API_SORT"] or "1", api["__API_KEY"],
                           urllib.parse.quote(api["__API_TG"] or ""), api["__API_ORDER"] or "1"))
            print("       接口：%s" % list_url)
            obj, text, guard = fetch_json(list_url, referer=cat_page["url"])
            if not isinstance(obj, dict) or "data" not in obj:
                rec("分类 JSON", False, "返回不是预期对象：%s" % snip(text))
            else:
                arr = obj.get("data") or []
                b0 = arr[0] if arr else {}
                rec("分类 JSON：total=%s last_page=%s 本页 %d 本" % (
                    obj.get("total"), obj.get("last_page"), len(arr)), bool(arr),
                    "第一本：%s → %s" % (b0.get("title"), M_HOST + (b0.get("url") or "")))
                print("       字段：title=%r pic=%r boyin=%r category=%r serialize_text=%r hits=%r"
                      % (b0.get("title"), b0.get("pic"), b0.get("boyin"),
                         b0.get("category"), b0.get("serialize_text"), b0.get("hits")))
                print("       Content-Type 是 %s（不可信，body 才是 JSON）" % "text/html 之类")
        except Exception as e:
            rec("分类 JSON", False, "异常：%s" % e)

    # ────────────────────────────────────────────────────────────────
    book = None
    if do_search:
        head("④ 搜索 JSON  GET {m}/api/ajax/solist?word={kw}&type=name&page=1&order=1")
        try:
            s_url = ("%s/api/ajax/solist?word=%s&type=name&page=1&order=1"
                     % (M_HOST, urllib.parse.quote(kw, safe="")))
            print("       接口：%s" % s_url)
            obj, text, guard = fetch_json(s_url, referer=M_HOST + "/")
            # 限流时返回的是对象 {"status":0,...}，正常是数组
            if isinstance(obj, dict) and obj.get("status") == 0:
                print("       [..] 30 秒限流：%s（等 32 秒重试一次）" % obj.get("info"))
                time.sleep(32)
                obj, text, guard = fetch_json(s_url, referer=M_HOST + "/")
            if not isinstance(obj, list):
                rec("搜索 JSON", False, "返回不是数组：%s" % snip(text))
            else:
                hits = [x for x in obj if (x.get("novel") or {}).get("url")]
                print("       命中 %d 条（body 是 JSON 数组；异常时是 JSON 对象）" % len(obj))
                for x in hits[:3]:
                    nv = x.get("novel") or {}
                    print("         · %s → %s   [播音 %s / 分类 %s]"
                          % (nv.get("name"), nv.get("url"),
                             (x.get("boyin") or {}).get("name"), x.get("category")))
                rec("搜索「%s」%d 条" % (kw, len(hits)), bool(hits))
                if hits:
                    book = {"title": hits[0]["novel"]["name"],
                            "url": M_HOST + hits[0]["novel"]["url"],
                            "cover": M_HOST + (hits[0]["novel"].get("cover") or ""),
                            "artist": (hits[0].get("boyin") or {}).get("name") or "",
                            "intro": hits[0]["novel"].get("intro") or ""}
        except Exception as e:
            rec("搜索 JSON", False, "异常：%s" % e)

    if book is None:
        bid = book_id or "22801"
        book = {"title": "（未走搜索，用固定 book_id）", "url": "%s/book/%s.html" % (M_HOST, bid),
                "cover": "", "artist": "", "intro": ""}

    # ────────────────────────────────────────────────────────────────
    head("⑤ 书籍页  GET {m}/book/{id}.html（不需要守卫）")
    dir_url = None
    book_html = ""
    try:
        html, guard = guarded_fetch(book["url"], referer=M_HOST + "/")
        book_html = html
        print("       页面 %s（%d 字节）守卫页=%s" % (book["url"], len(html), guard))
        soup = BeautifulSoup(html, "lxml") if BeautifulSoup else None
        title = soup.select_one("h1.book-title") if soup else None
        cover = soup.select_one("img.book-cover") if soup else None
        boyin = soup.select_one("div.book-rand-a a[href^='/boyin/']") if soup else None
        dirnode = soup.select_one("a.dirurl") if soup else None
        print("       h1.book-title  = %r" % (title.get_text(strip=True) if title else None))
        print("       img.book-cover = %r" % (cover.get("src") if cover else None))
        print("       a[href^=/boyin/] = %r" % (boyin.get_text(strip=True) if boyin else None))
        print("       a.dirurl       = %r" % (dirnode.get("href") if dirnode else None))
        if dirnode and dirnode.get("href"):
            dir_url = dirnode["href"]
            if not dir_url.startswith("http"):
                dir_url = M_HOST + ("" if dir_url.startswith("/") else "/") + dir_url
        rec("书籍页解析（标题/封面/播音/目录入口 a.dirurl）",
            bool(title and dir_url), "a.dirurl → %s" % dir_url)
    except Exception as e:
        rec("书籍页", False, "异常：%s" % e)

    # ────────────────────────────────────────────────────────────────
    head("⑥ 目录页  GET {m}/bookdir/{h1}/{h2}.html（JS Cookie 守卫）")
    eps = []
    if not dir_url:
        rec("目录页", False, "没有目录入口，跳过")
    else:
        try:
            raw0 = robust(lambda: R.fetch(dir_url, retries=0, referer=book["url"]))
            guard = "var reversed" in raw0
            html = robust(lambda: R.fetch(dir_url, retries=3, referer=book["url"])) if guard else raw0
            print("       首抓 %d 字节，守卫页=%s" % (len(raw0), guard))
            if guard:
                print("       （引擎已自动解 pt_guid 并重放，得到 %d 字节）" % len(html))
            soup = BeautifulSoup(html, "lxml") if BeautifulSoup else None
            seen, links = set(), []
            for a in (soup.select("a[href*='/tingshu/']") if soup else []):
                h = a.get("href") or ""
                m = re.match(r"^/tingshu/(\d+)/(\d+)\.html", h)
                if not m or h in seen:
                    continue
                seen.add(h)
                links.append({"title": a.get("title") or a.get_text(" ", strip=True),
                              "href": h, "nid": m.group(1), "cid": m.group(2)})
            eps = links
            if links:
                print("       第一集：%s" % links[0]["title"][:60])
                print("       链接  ：%s   (nid=%s cid=%s)" % (links[0]["href"], links[0]["nid"], links[0]["cid"]))
                print("       最后一集：%s  （nid/cid 用 urlVars 正则从章节链接里取）"
                      % links[-1]["href"])
            rec("目录页 %d 章（去重后）" % len(links), bool(links),
                "hash 每次抓 /book/ 都会变，所以必须现抓")

            # ── 目录分页：文档 §5 说「/bookdir/ 一次给全部章节，无翻页」——实测不成立 ──
            if soup is not None:
                declared = 0
                md = re.search(r"总\s*(\d+)\s*集", book_html or "")
                if md:
                    declared = int(md.group(1))
                pag_hrefs = sorted({(a.get("href") or "") for a in soup.select("a[href*=page]")})
                print("       书籍页声明「总 N 集」= %s；目录第 1 页拿到 %d 章" % (declared or "?", len(links)))
                print("       目录里的分页链接：%s" % (pag_hrefs[:4] or "（无）"))
                if declared and declared > len(links):
                    print("       → 声明 %d 集 > 第 1 页 %d 章：**必须翻页**"
                          "（规则要写 detail.pages）" % (declared, len(links)))
                    for label, u2 in (("引擎默认 {dir}?page=2", dir_url + "?page=2"),
                                      ("站点自带 ?page=2&sort=asc", dir_url + "?page=2&sort=asc")):
                        try:
                            d2 = robust(lambda: R.fetch(u2, referer=book["url"]))
                            h2 = {a.get("href") for a in
                                  (BeautifulSoup(d2, "lxml").select("a[href*='/tingshu/']"))}
                            print("         %-26s → %d 字节 / %d 章 / 其中新品 %d 章"
                                  % (label, len(d2), len(h2), len(h2 - seen)))
                        except Exception as e:
                            print("         %-26s → 失败：%s" % (label, str(e)[:60]))
                        time.sleep(1.0)
        except Exception as e:
            rec("目录页", False, "异常：%s" % e)

    # ────────────────────────────────────────────────────────────────
    head("⑦ PC 播放页  GET {p}/player.html?nid=&cid=&site=16  → 求值 `mp3:` 拼接表达式")
    ok_self, lines = _selftest()
    print("       求值器自测（文档实录的 3 种形态 + 整条地址在变量里，共 4 例）：")
    for l in lines:
        print(l)
    rec("求值器自测", ok_self)

    audio_url = ""
    if not eps:
        rec("PC 播放页", False, "没有章节，跳过")
    else:
        ep = eps[0]
        try:
            player = ("%s/player.html?nid=%s&cid=%s&site=16" % (PC_HOST, ep["nid"], ep["cid"]))
            print("       播放页：%s" % player)
            html = robust(lambda: R.fetch(player, referer=PC_HOST + "/", desktop=True, retries=2))
            print("       %d 字节 / 桌面 UA / 无需守卫" % len(html))
            info = resolve_media_url(html)
            print("       页面变量表 %d 个（有 var / 裸赋值都收）" % info["vars"])
            print("       mp3: 表达式 = %s" % snip(info["expr"], 200))
            print("       顶层 '+' 分段 = %s" % info["segments"])
            for at in info["attempts"]:
                print("       求值(breakNewline=%-5s) → %s" % (at["breakNewline"], snip(at["value"], 160)))
            print("       采用方式：%s" % info["method"])
            audio_url = info["url"]
            rec("解析出音频地址", bool(audio_url), audio_url)
        except Exception as e:
            rec("PC 播放页", False, "异常：%s" % e)

    # ────────────────────────────────────────────────────────────────
    head("⑧ 试听  Range: bytes=0-1024")
    if not audio_url:
        rec("试听", False, "没有音频地址，跳过")
    else:
        last = ""
        for attempt in range(3):
            try:
                req = urllib.request.Request(audio_url)
                req.add_header("Range", "bytes=0-1024")
                req.add_header("User-Agent", D_UA)
                req.add_header("Referer", PC_HOST + "/")
                with R.OPENER.open(req, timeout=45) as r:
                    data = r.read(4096)
                    ct = r.headers.get("Content-Type") or ""
                    cr = r.headers.get("Content-Range") or ""
                    print("       HTTP %s" % r.status)
                    print("       Content-Type   : %s" % ct)
                    print("       Content-Range  : %s" % cr)
                    print("       取回           : %d 字节" % len(data))
                    print("       magic          : %s" % " ".join("%02X" % b for b in data[:12]))
                    ok = r.status in (200, 206) and ("audio" in ct or "video" in ct or "octet" in ct)
                    rec("试听 HTTP %s / %s / %d 字节" % (r.status, ct, len(data)), ok)
                    break
            except Exception as e:
                last = str(e)
                print("       [..] 第 %d 次失败：%s" % (attempt + 1, last[:90]))
                if attempt < 2:
                    time.sleep(3)
        else:
            rec("试听", False, last or "失败")

    # ────────────────────────────────────────────────────────────────
    print("\n" + "═" * 72)
    print("汇总")
    print("═" * 72)
    for name, ok in RESULTS:
        print("  %s %s" % ("✅" if ok else "❌", name))
    bad = [n for n, ok in RESULTS if not ok]
    print("\n  %s" % ("全部通过" if not bad else "有失败：%s" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断")
        sys.exit(130)
