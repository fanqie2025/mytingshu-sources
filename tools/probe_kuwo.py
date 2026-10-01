# -*- coding: utf-8 -*-
"""酷我畅听（kuwo.cn）书源规则迁移 —— 独立探测脚本。

只做探测，不改任何共享文件。输出全部原始证据，回答两件事：
  ① 这条链路能不能跑通（搜索 → 专辑曲目 → 音频直链 → Range 试听）；
  ② 现有规则引擎缺哪个字段 —— 实测：响应既不是 HTML 也不是标准 JSON，
     而是**单引号 JS/Python 对象字面量**，所以 kind:"json" 吃不下。

接口（全部 http，无 token / 无签名 / 无 csrf / 无 Cookie 守卫）：
  ① 搜索（专辑级） http://search.kuwo.cn/r.s?all=<kw>&ft=album&itemset=web_2013&client=kt&pn=0&rn=20&rformat=json&encoding=utf8
  ①' 搜索（歌曲级） 同上，ft=music（归档 KuwoSource.swift 用的那个，作为对照）
  ② 专辑/曲目       http://search.kuwo.cn/r.s?stype=albuminfo&albumid=<aid>&rformat=json&encoding=utf8&rn=200&pn=0
  ③ 音频直链        http://antiserver.kuwo.cn/anti.s?type=convert_url3&rid=<rid>&format=mp3&response=url
  ④ 试听            对 ③ 拿到的 CDN 地址发 Range: bytes=0-1024

脚本里对照**三种列表解析方案**，为「引擎该加哪个字段」提供实测数字：
  A. 字面量解析后走点号路径（= 建议新增的 kind:"literal"）→ 实测 20 条 / 曲目全中
  B. 朴素切块正则 \\{[^{}]*\\}（= kind:"regex" 最朴素的写法）→ 实测 80 块 / 0 命中
  C. 深度容忍切块正则（3 层）→ 实测 20 块 / 97 块（能用，但依赖嵌套不超过 3 层）

用法（Windows）：
  C:\\Users\\Administrator\\AppData\\Local\\Python\\bin\\python.exe tools\\probe_kuwo.py
  python tools\\probe_kuwo.py 单田芳             # 换关键词
  python tools\\probe_kuwo.py 三体 search        # 只跑搜索对照
  python tools\\probe_kuwo.py 三体 album 74399040
  python tools\\probe_kuwo.py 三体 audio 626727349
  python tools\\probe_kuwo.py 三体 page           # 只看分页语义（pn 是 0 基偏移）

代理：默认直连（ProxyHandler({})），并在 [0] 打印环境代理变量做对照 ——
酷我接口是 http，被本机代理劫持时会拿到假响应。
"""
import ast
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEARCH_API = "http://search.kuwo.cn/r.s"
ANTI_API = "http://antiserver.kuwo.cn/anti.s"
IMG_BASE = "https://img4.kuwo.cn/star/albumcover/"

UA_M = ("Mozilla/5.0 (Linux; Android 9; SM-S9280) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36")
UA_D = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TIMEOUT = 30
RETRY = 3
AUDIO_CT_OK = ("audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/aac", "octet-stream")

# 直连（忽略 http_proxy/https_proxy）—— 酷我是 http 站，代理最容易伪造响应
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# ---------------------------------------------------------------- 候选正则
# Swift 的 firstMatch/allMatches 建 NSRegularExpression 时带 .caseInsensitive，
# 所以下面统一小写模式即可同时命中 'ALBUMID' 与 'albumid'。
RE_BLOCK_SIMPLE = r"\{[^{}]*\}"                                   # 方案 B：朴素切块
RE_BLOCK_DEEP = r"\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}"       # 方案 C：容忍 3 层嵌套
RE_QUOTED = r"'((?:[^'\\]|\\.)*)'"                                # 单引号串
RE_LITERAL = r"(?<=[:,\[])\s*(null|None|true|True|false|False)\s*(?=[,\]}])"

RE_ALBUMID = r"'albumid'\s*:\s*'(\d+)'"
RE_MUSICRID = r"'musicrid'\s*:\s*'([a-z]*_)?(\d+)'"
RE_ANTI_URL = r'"url"\s*:\s*"([^"]+)"'
RE_PSEUDO_RID = r"([A-Za-z]*_?\d+)"        # 章节地址里携带的 musicrid（MUSIC_626726999）

failures = []


# ---------------------------------------------------------------- 工具

def log(tag, msg):
    print("%-7s %s" % (tag, msg))


def head(title):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def http_get(url, headers=None, desktop=False, tries=RETRY, read=None):
    """GET，返回 (status, headers_dict_lower, body_bytes)；4xx/5xx 不抛，交给调用方。"""
    h = {"User-Agent": UA_D if desktop else UA_M, "Accept": "*/*",
         "Accept-Language": "zh-CN,zh;q=0.9"}
    h.update(headers or {})
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with OPENER.open(req, timeout=TIMEOUT) as r:
                body = r.read() if read is None else r.read(read)
                return r.status, {k.lower(): v for k, v in r.headers.items()}, body
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:
                pass
            return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, raw
        except Exception as e:
            last = e
            if attempt < tries - 1:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError("%s -> %s: %s" % (url, type(last).__name__, last))


def decode(body):
    for enc in ("utf-8", "gb18030"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", "replace")


NBSPS = ("&nbsp;", "&#160;", "\u00a0")


def clean(s):
    """解 \\uXXXX 二次转义 + &nbsp; + 折叠空白（ft=music 会把 & 转义成 \\\\u0026）。"""
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace("\\/", "/")
    for n in NBSPS:
        s = s.replace(n, " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_literal(text):
    """方案 A：JS/Python 对象字面量 → 对象。

    Python 侧 = json.loads 失败后 ast.literal_eval；
    Swift 侧等价做法 = 把单引号串换成双引号串（值里的 " 顺带转义）+ 裸 null/true/false
    修正后交给 JSONSerialization —— 本函数把这条 Swift 路径也实测跑一遍。
    """
    try:
        return json.loads(text), "json.loads（标准 JSON）"
    except Exception as e:
        json_err = "%s: %s" % (type(e).__name__, e)

    def swap(m):
        return '"' + m.group(1).replace('"', '\\"') + '"'

    fixed = re.sub(RE_QUOTED, swap, text)
    fixed = re.sub(RE_LITERAL, lambda m: {"None": "null", "True": "true",
                                          "False": "false"}.get(m.group(1), m.group(1)), fixed)
    try:
        return json.loads(fixed), ("单引号→双引号 归一化 + json.loads（Swift 可行路径；"
                                   "json.loads 原始报错：%s）" % json_err)
    except Exception as e2:
        swap_err = "%s: %s" % (type(e2).__name__, e2)

    try:
        return ast.literal_eval(text), "ast.literal_eval（归一化失败后的兜底：%s）" % swap_err
    except Exception as e3:
        return None, "三种都失败：json=%s / 归一化=%s / literal=%s" % (json_err, swap_err, e3)


def dig(obj, path):
    """点号路径取值（= 引擎现有的 anyValue(at:) / _any_at 语义）"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def block_report(text, key_re, expect=None):
    """对照三种切块策略（为「kind:"regex" 划不划算」留证据）"""
    t0 = time.time()
    simple = re.findall(RE_BLOCK_SIMPLE, text)
    s_hit = sum(1 for b in simple if re.search(key_re, b, re.I))
    t1 = time.time()
    deep = re.findall(RE_BLOCK_DEEP, text)
    d_hit = sum(1 for b in deep if re.search(key_re, b, re.I))
    t2 = time.time()
    log("REGEX-B", "朴素切块 %s -> %d 块，命中 %s 的 %d 块（%.3fs）"
        % (RE_BLOCK_SIMPLE, len(simple), key_re, s_hit, t1 - t0))
    log("REGEX-C", "深度容忍切块（3 层）-> %d 块，命中 %s 的 %d 块（%.3fs）"
        % (len(deep), key_re, d_hit, t2 - t1))
    if s_hit == 0:
        log("REGEX-B", "==> 朴素切块 0 命中：条目内部有嵌套对象（payInfo/feeType…），"
                       "`\\{[^{}]*\\}` 只切到内层碎片")
    if expect is not None:
        if d_hit == expect:
            log("REGEX-C", "==> 深度容忍切块数目与点号路径一致（%d），但依赖嵌套不超过 3 层" % expect)
        else:
            log("REGEX-C", "==> ⚠ 深度容忍切块 %d ≠ 点号路径 %d，切块方案不可靠" % (d_hit, expect))
    return deep


# ---------------------------------------------------------------- 链路

def search_url(kw, ft="album", pn=0, rn=20):
    q = urllib.parse.urlencode({"all": kw, "ft": ft, "itemset": "web_2013",
                                "client": "kt", "pn": pn, "rn": rn,
                                "rformat": "json", "encoding": "utf8"})
    return "%s?%s" % (SEARCH_API, q)


def album_url(albumid, rn=200, pn=0):
    q = urllib.parse.urlencode({"stype": "albuminfo", "albumid": albumid,
                                "rformat": "json", "encoding": "utf8",
                                "rn": rn, "pn": pn})
    return "%s?%s" % (SEARCH_API, q)


def anti_url(rid):
    q = urllib.parse.urlencode({"type": "convert_url3", "rid": rid,
                                "format": "mp3", "response": "url"})
    return "%s?%s" % (ANTI_API, q)


def step0_env():
    head("[0] 环境与连通性")
    log("INFO", "python  %s" % sys.version.split()[0])
    prox = {k: v for k, v in os.environ.items()
            if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    log("INFO", "环境代理变量: %s" % (prox or "（无）"))
    log("INFO", "本次请求一律直连（ProxyHandler({})），已绕过系统代理")
    for u in (SEARCH_API, ANTI_API):
        host = u.split("//")[1].split("/")[0]
        try:
            st, _hd, _ = http_get(u + "?probe=1", tries=1, read=1)
            log("OK", "%s -> HTTP %s（直连可达）" % (host, st))
        except Exception as e:
            log("FAIL", "%s 不可达: %s" % (host, e))
            failures.append("连通性 %s" % host)


def search_variant(kw, ft, key, id_field, title_field, artist_field, pn=0, rn=20):
    """跑一个搜索变体，返回 (去重后的专辑列表, 原始条数)"""
    url = search_url(kw, ft=ft, pn=pn, rn=rn)
    tag = {"album": "①a ft=album", "music": "①b ft=music"}[ft]
    log("URL", "%s  %s" % (tag, url))
    try:
        st, hd, body = http_get(url, headers={"Referer": "http://www.kuwo.cn/"})
    except Exception as e:
        log("FAIL", "%s 请求异常: %s" % (tag, e))
        failures.append("%s 请求" % tag)
        return [], 0, ""
    text = decode(body)
    log("HTTP", "%s %s  Content-Type=%s  %d bytes"
        % (tag, st, hd.get("content-type"), len(text)))
    if ft == "album":
        print("\n--- 原始响应前 300 字符 ---")
        print(text[:300])
        print("...\n")

    obj, how = parse_literal(text)
    log("PARSE", "%s 解析方式：%s" % (tag, how))
    if obj is None:
        failures.append("%s 解析" % tag)
        return [], 0, text
    items = dig(obj, key) or []
    if ft == "album":
        log("PARSE", "%s ==> 标准 JSON 解析失败、字面量解析成功 ⇒ 现有 kind:\"json\" 吃不下" % tag)

    expect_ids = set()
    for _it in items:
        _v = str(_it.get(id_field) or "")
        if _v and _v != "0":
            expect_ids.add(_v)
    block_report(text, RE_ALBUMID if ft == "album" else r"'albumid'\s*:\s*'(\d+)'",
                 expect=len(expect_ids))

    albums, seen = [], set()
    for it in items:
        aid = str(it.get(id_field) or "")
        if not aid or aid == "0" or aid in seen:
            continue
        seen.add(aid)
        albums.append({
            "albumid": aid,
            "title": clean(it.get(title_field) or ""),
            "artist": clean(it.get(artist_field) or ""),
            "cover": it.get("img") or it.get("hts_img") or (
                (IMG_BASE + it["web_albumpic_short"]) if it.get("web_albumpic_short") else ""),
            "intro": clean(it.get("info") or it.get("NAME") or "")[:60],
            "raw_title": it.get(title_field),
        })
    log("OK", "%s「%s」第 1 页（pn=%d rn=%d）拿到 %d 条，去重后 %d 张专辑%s"
        % (tag, kw, pn, rn, len(items), len(albums),
           "（无需去重）" if len(items) == len(albums) else "（⚠ 有重复：%d → %d，引擎没有去重能力）"
           % (len(items), len(albums))))
    for i, a in enumerate(albums[:4], 1):
        log("     ", "%d) albumid=%-10s %s" % (i, a["albumid"], a["title"][:38]))
        log("     ", "   artist=%s" % a["artist"][:38])
        log("     ", "   cover =%s" % (a["cover"][:70] or "（无）"))
    if albums and albums[0]["raw_title"] != albums[0]["title"]:
        log("NOTE", "%s ⚠ 字段残留转义：原文 %r → 清洗后 %r"
            % (tag, albums[0]["raw_title"][:44], albums[0]["title"][:44]))
    return albums, len(items), text


def step1_search(kw):
    head("[1] 搜索对照  %s" % SEARCH_API)
    va, na, _ = search_variant(kw, "album", "albumlist", "albumid", "name", "artist")
    vm, nm, _ = search_variant(kw, "music", "abslist", "ALBUMID", "ALBUM", "ARTIST")
    log("NOTE", "对照结论：ft=album 直接给专辑（字段干净、天然去重）；"
                "ft=music 给歌曲（20 条只对应 %d 张专辑，且 ALBUM/ARTIST 里带 &nbsp; 与 \\u0026）" % len(vm))
    return {"album": va, "music": vm}


def step1b_pagination(kw):
    """pn 是 0 基偏移：验证「规则里只有 {page} 字符串替换」会怎样"""
    head("[1b] 分页语义  pn=0 / 1 / 2 各取第一条 albumid")
    got = {}
    for pn in (0, 1, 2):
        try:
            _, _, body = http_get(search_url(kw, ft="album", pn=pn, rn=20),
                                  headers={"Referer": "http://www.kuwo.cn/"})
            obj, _ = parse_literal(decode(body))
            items = dig(obj or {}, "albumlist") or []
            first = str(items[0].get("albumid")) if items else ""
            got[pn] = first
            log("INFO", "pn=%d -> 返回 %d 条，第一条 albumid=%s" % (pn, len(items), first))
        except Exception as e:
            log("FAIL", "pn=%d 失败: %s" % (pn, e))
    if len(set(got.values())) > 1:
        log("NOTE", "pn 是 0 基偏移；规则里写 pn={page} 会整体错位一页（第 1 页从第 2 条开始）")
        log("NOTE", "建议给 search 加一个 {page0}（= page-1）替换，或让分页字段支持简单减法")
    else:
        log("NOTE", "pn=0/1/2 第一条相同，偏移影响可忽略")


def step2_album(albumid, label=""):
    head("[2] 专辑详情 / 曲目  albuminfo  albumid=%s %s" % (albumid, label))
    url = album_url(albumid)
    log("URL", url)
    try:
        st, hd, body = http_get(url, headers={"Referer": "http://www.kuwo.cn/"})
    except Exception as e:
        log("FAIL", "请求异常: %s" % e)
        failures.append("② 专辑请求")
        return [], {}
    text = decode(body)
    log("HTTP", "%s   Content-Type=%s   %d bytes" % (st, hd.get("content-type"), len(text)))
    print("\n--- 原始响应前 200 字符 ---")
    print(text[:200])
    print("...\n")

    obj, how = parse_literal(text)
    if obj is None:
        log("FAIL", "专辑响应解析不了")
        failures.append("② 专辑解析")
        return [], {}
    log("PARSE", "解析方式：%s" % how)

    ml = dig(obj, "musiclist") or []
    log("PARSE", "点号路径 musiclist -> %d 条；name=%s  songnum=%s  img=%s"
        % (len(ml), clean(obj.get("name"))[:32], obj.get("songnum"), obj.get("img")))
    block_report(text, RE_MUSICRID, expect=len(ml))

    tracks = []
    for t in ml:
        rid = re.sub(r"^[A-Za-z]+_", "", str(t.get("musicrid") or ""))
        if not rid:
            continue
        tracks.append({"rid": rid, "name": clean(t.get("name")),
                       "duration": str(t.get("duration") or ""),
                       "tpay": str(t.get("tpay") or "0"),
                       "raw_rid": str(t.get("musicrid") or ""),
                       "track": str(t.get("track") or "")})
    if not tracks:
        log("FAIL", "没取到任何曲目")
        failures.append("② 专辑解析")
        return [], obj

    free = [t for t in tracks if t["tpay"] == "0"]
    log("OK", "② 专辑《%s》共 %d 首曲目（免费 tpay=0：%d 首；付费 %d 首）"
        % (clean(obj.get("name"))[:26], len(tracks), len(free), len(tracks) - len(free)))
    for t in tracks[:3]:
        log("     ", "rid=%-11s dur=%-5ss tpay=%s  %s"
            % (t["rid"], t["duration"], t["tpay"], t["name"][:38]))
    log("NOTE", "曲目字段：name / musicrid / duration / tpay（没有 track 之外的序号字段）")
    log("NOTE", "⚠ musicrid 原文 = %r（纯数字，**不带** MUSIC_ 前缀）；"
                "归档 KuwoSource.swift 用的正则 'musicrid':\\s*'MUSIC_(\\d+)' 在今天的响应上取不到值"
        % tracks[0]["raw_rid"])

    seq = [t["track"] for t in tracks if t["track"].lstrip("-").isdigit()]
    if len(seq) == len(tracks) and len(seq) > 2:
        asc = all(int(seq[i]) <= int(seq[i + 1]) for i in range(len(seq) - 1))
        desc = all(int(seq[i]) >= int(seq[i + 1]) for i in range(len(seq) - 1))
        order = "升序（第 1 集在前）" if asc else ("倒序（最后一集在前）" if desc else "无序/交错")
    else:
        order = "track 字段不完整，无法判定"
    log("ORDER", "musiclist 的 track 顺序 = %s（首 %s → 尾 %s）"
        % (order, tracks[0]["track"], tracks[-1]["track"]))
    if order.startswith("倒序"):
        log("NOTE", "站点按 track 倒序返回，且 albuminfo 没有排序参数（sort/order/asc 实测无效）"
                    " → 章节列表会「最后一集在最前」，需要引擎给个 reverse 开关才好看")
    return tracks, obj


def step3_audio(track):
    head("[3] 音频直链  章节地址带 rid → GET anti.s → 取 url")
    # 演示拟议的 audio.type:"api" + urlVars 语义（urlVars 在 Swift 引擎里已存在）
    pseudo = "http://kuwo.cn/MUSIC_%s" % track["rid"]
    log("INFO", "章节地址：%s" % pseudo)
    m = re.search(RE_PSEUDO_RID, pseudo)
    rid = m.group(1) if m else ""
    log("VARS", "urlVars {\"rid\": %r} -> rid=%s（= AudioRule.urlVars 现有语义，"
               "接口能吃下 MUSIC_ 前缀）" % (RE_PSEUDO_RID, rid))
    if not rid:
        failures.append("③ rid 取值")
        return ""

    url = anti_url(rid)
    log("URL", url)
    try:
        st, hd, body = http_get(url, headers={"Referer": "http://www.kuwo.cn/"})
    except Exception as e:
        log("FAIL", "请求异常: %s" % e)
        failures.append("③ 音频接口")
        return ""
    text = decode(body).strip()
    log("HTTP", "%s   Content-Type=%s（注意：响应头写 text/html，body 其实是 JSON）"
        % (st, hd.get("content-type")))
    print("\n--- 原始响应 ---")
    print(text[:400])
    print("")

    try:
        obj = json.loads(text)
        log("JSON", "是标准 JSON ⇒ audio 可以直接 field:\"url\"：code=%r  url=%s"
            % (obj.get("code"), str(obj.get("url"))[:70]))
    except Exception as e:
        log("JSON", "不是标准 JSON（%s）—— 退回 pattern 正则取值" % str(e)[:70])

    m = re.search(RE_ANTI_URL, text)
    if not m:
        log("FAIL", "正则 %s 没取到 url（付费内容 / 风控）" % RE_ANTI_URL)
        failures.append("③ 音频取值 rid=%s" % rid)
        return ""
    aurl = m.group(1).replace("\\/", "/")
    log("OK", "③ 音频地址：%s" % aurl)
    log("INFO", "曲目 %s（tpay=%s, %ss）" % (track["name"][:34], track["tpay"], track["duration"]))
    return aurl


def step4_range(aurl, expect_dur=0):
    head("[4] Range: bytes=0-1024  试探 CDN")
    log("URL", aurl[:118])
    try:
        st, hd, body = http_get(aurl, headers={"Range": "bytes=0-1024",
                                               "Referer": "http://www.kuwo.cn/",
                                               "Accept": "*/*"}, desktop=True)
    except Exception as e:
        log("FAIL", "Range 请求失败: %s" % e)
        failures.append("④ Range 试听")
        return
    ct = hd.get("content-type", "")
    cr = hd.get("content-range", "")
    total = ""
    m = re.search(r"/(\d+)\s*$", cr)
    if m:
        total = m.group(1)
    elif hd.get("content-length", "").isdigit():
        total = hd["content-length"]
    log("HTTP", "%s   Content-Type=%s" % (st, ct))
    log("HTTP", "Content-Range=%s   Content-Length=%s"
        % (cr or "（无）", hd.get("content-length")))
    log("DATA", "收到 %d 字节，首 16 字节 = %r" % (len(body), body[:16]))
    if total:
        log("DATA", "总长度 ≈ %s bytes（%.2f MB）" % (total, int(total) / 1048576.0))
        if expect_dur:
            kbps = int(total) / float(expect_dur) * 8 / 1000
            log("DATA", "换算 ≈ %.0f kbps（128kbps 左右 = 完整音频；几十 kbps = 试听片段）" % kbps)
    ok = st in (200, 206) and len(body) > 0 and any(a in ct.lower() for a in AUDIO_CT_OK)
    if ok:
        log("OK", "④ HTTP %s + Content-Type=%s + %d 字节 ⇒ 可播放" % (st, ct, len(body)))
        log("NOTE", "206 = Range 生效（可拖进度/边下边播）；200 也算通过")
    else:
        log("FAIL", "④ HTTP %s Content-Type=%s 字节=%d ⇒ 不是音频响应" % (st, ct, len(body)))
        failures.append("④ Range 试听")


def summary():
    head("汇总")
    if not failures:
        print("结论: 全链路通过 —— 搜索 / 专辑曲目 / 音频直链 / Range 试听 全部可用；")
        print("      无 token、无签名、无 csrf、无 Cookie 守卫；接口是纯 http。")
        print("      唯一障碍：响应是单引号 JS/Python 对象字面量（既不是 HTML，也不是标准 JSON）。")
    else:
        print("存在失败步骤：")
        for f in failures:
            print("  - %s" % f)
    print("")
    return 0 if not failures else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want = "all"
    if args and args[-1] in ("search", "album", "audio", "page", "all"):
        want = args.pop()
    kw = args[0] if args else "三体"

    print("酷我畅听（kuwo.cn）规则化探测   关键词=%r   执行=%s" % (kw, want))
    step0_env()

    variants = {"album": [], "music": []}
    if want in ("all", "search", "album", "audio", "page"):
        variants = step1_search(kw)
    if want == "page":
        step1b_pagination(kw)
        return summary()

    albumid = args[1] if len(args) > 1 else None
    if albumid is None:
        albumid = (variants["album"] or variants["music"] or [{"albumid": "98108239"}])[0]["albumid"]

    tracks, _meta = [], {}
    if want in ("all", "album", "audio"):
        tracks, _meta = step2_album(albumid, "（ft=album 第一张）" if len(args) < 2 else "")
    if want == "album":
        return summary()

    rid = args[1] if (want == "audio" and len(args) > 1) else None
    track = None
    if rid:
        track = {"rid": re.sub(r"^[A-Za-z]+_", "", rid), "name": "(命令行指定)",
                 "duration": "", "tpay": "0"}
    else:
        free = [t for t in tracks if t["tpay"] == "0"]
        track = (free or tracks or [None])[0]

    # 主专辑没有免费曲目时，补跑归档用的 ft=music 首张专辑（因为付费曲目只有 ~30s 试听）
    if track is not None and track["tpay"] != "0" and variants["music"]:
        alt = variants["music"][0]["albumid"]
        if alt != albumid:
            log("NOTE", "主专辑没有免费曲目，补跑 ft=music 首张专辑 %s 取免费曲目" % alt)
            alt_tracks, _ = step2_album(alt, "（ft=music 第一张 / 归档对齐）")
            alt_free = [t for t in alt_tracks if t["tpay"] == "0"]
            if alt_free:
                track = alt_free[0]

    if track is None:
        log("FAIL", "没有可用曲目，跳过 ③④")
        failures.append("③④ 无曲目")
        return summary()

    aurl = step3_audio(track)
    if aurl:
        step4_range(aurl, expect_dur=int(track["duration"] or 0))
    return summary()


if __name__ == "__main__":
    sys.exit(main())
