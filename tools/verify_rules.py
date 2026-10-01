# -*- coding: utf-8 -*-
"""把 sources.json 里的每个规则走一遍完整链路：搜索 → 详情 → 章节 → 音频 → 真拉 1KB。

用法：python3 tools/verify_rules.py subscription/sources.json [关键词] [源id...]
"""
import json
import os
import sys
import urllib.request

# 让脚本在任何目录下都能 import 到 rule_engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rule_engine as R

sys.stdout.reconfigure(encoding="utf-8")


def check(rule, kw):
    print("=" * 68)
    print("【%s】%s" % (rule["name"], rule["host"]))

    b = None
    # 有站内搜索就走搜索；没有 / 明确 searchable:false 就走分类
    if rule.get("search") and rule.get("searchable") is not False:
        try:
            books = R.do_search(rule, kw)
        except Exception as e:
            print("   ⚠ 搜索失败（改走分类）：%s" % e)
            books = []
        print("   ① 搜索「%s」→ %d 条" % (kw, len(books)))
        if books:
            b = books[0]
    if b is None:
        try:
            menus = R.do_menus(rule)
        except Exception as e:
            print("   ❌ 分类导航失败：%s" % e)
            return False
        if not menus:
            print("   ❌ 既搜不到也没有分类导航")
            return False
        group, cat_title, cat_url = menus[0]
        try:
            books = R.do_category(rule, cat_url, 1)
        except Exception as e:
            print("   ❌ 分类列表失败：%s" % e)
            return False
        print("   ①' 分类「%s / %s」→ %d 本" % (group, cat_title, len(books)))
        if not books:
            return False
        b = books[0]

    print("      第一本：%s" % b["title"])
    print("      链接  ：%s" % b["url"])
    if b.get("artist"):
        print("      播音  ：%s" % b["artist"])

    try:
        eps = R.do_detail(rule, b)
    except Exception as e:
        print("   ❌ 详情/章节失败：%s" % e)
        return False
    print("   ② 章节 → %d 集" % len(eps))
    if not eps:
        return False
    print("      第一集：%s" % eps[0]["title"][:44])
    print("      链接  ：%s" % eps[0]["url"])

    # 音频：前几集都试一遍（有些站的第一集是主题曲/预告，站方单独保护会 403）
    import time
    problems = []
    for idx, ep in enumerate(eps[:5]):
        try:
            url, headers = R.do_audio(rule, ep)
        except Exception as e:
            problems.append("#%d 取地址失败 %s" % (idx + 1, str(e)[:50]))
            continue
        if not url:
            problems.append("#%d 空地址" % (idx + 1))
            continue
        last = ""
        for attempt in range(2):
            try:
                req = urllib.request.Request(url)
                req.add_header("Range", "bytes=0-1024")
                req.add_header("User-Agent", R.UA_D)
                for k, v in headers.items():
                    req.add_header(k, v)
                with R.OPENER.open(req, timeout=45) as r:
                    data = r.read(1025)
                    ct = r.headers.get("Content-Type") or ""
                    ok = (r.status in (200, 206)) and ("audio" in ct or "video" in ct or "octet" in ct)
                    if ok:
                        if idx > 0:
                            print("   （第 1 集站方保护/失效，跳过：%s）" % problems[:1])
                        print("   ③ 音频  ：%s" % url[:96])
                        print("      取自  ：第 %d 集 %s" % (idx + 1, ep["title"][:30]))
                        print("   ④ 试听  ：HTTP %s %s %d 字节  ✅" % (r.status, ct, len(data)))
                        return True
                    last = "HTTP %s %s" % (r.status, ct)
            except Exception as e:
                last = str(e)[:60]
                time.sleep(2)
        problems.append("#%d %s" % (idx + 1, last))
    print("   ❌ 前几集都取不到可播地址：%s" % "；".join(problems[:4]))
    return False


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "subscription/sources.json"
    kw = sys.argv[2] if len(sys.argv) > 2 else "三体"
    only = set(sys.argv[3:])
    data = json.load(open(path, encoding="utf-8"))
    rules = data.get("sources", []) if isinstance(data, dict) else data
    if only:
        rules = [r for r in rules if r["id"] in only]
    results = []
    for r in rules:
        try:
            results.append((r["id"], check(r, kw)))
        except Exception as e:
            print("   ❌ %s 异常：%s" % (r["id"], e))
            results.append((r["id"], False))
    print("=" * 68)
    for rid, ok in results:
        mark = "跳过" if ok is None else ("✅" if ok else "❌")
        print("  %-12s %s" % (rid, mark))
    bad = [r for r, ok in results if ok is False]
    print("全部通过" if not bad else "有失败：%s" % bad)
    sys.exit(1 if bad else 0)
