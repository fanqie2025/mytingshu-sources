# -*- coding: utf-8 -*-
"""把 sources.json 里的每个规则走一遍完整链路：搜索 → 详情 → 章节 → 音频 → 真拉 1KB。

用法：python3 tools/verify_rules.py subscription/sources.json [关键词] [源id...]
"""
import json
import sys
import urllib.request

import rule_engine as R

sys.stdout.reconfigure(encoding="utf-8")


def check(rule, kw):
    print("=" * 68)
    print("【%s】%s" % (rule["name"], rule["host"]))
    if not rule.get("search"):
        print("   （没有搜索规则，跳过）")
        return None

    try:
        books = R.do_search(rule, kw)
    except Exception as e:
        print("   ❌ 搜索失败：%s" % e)
        return False
    print("   ① 搜索「%s」→ %d 条" % (kw, len(books)))
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

    try:
        url, headers = R.do_audio(rule, eps[0])
    except Exception as e:
        print("   ❌ 音频失败：%s" % e)
        return False
    print("   ③ 音频  ：%s" % url[:100])

    try:
        last = ""
        for attempt in range(3):
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
                    print("   ④ 试听  ：HTTP %s %s %d 字节  %s" % (r.status, ct, len(data), "✅" if ok else "❌"))
                    return ok
            except Exception as e:
                last = str(e)
                if attempt < 2:
                    print("   ④ 试听  ：第 %d 次失败（%s），重试…" % (attempt + 1, last[:60]))
                    import time
                    time.sleep(3)
        print("   ④ 试听  ：❌ %s" % last)
        return False
    except Exception as e:
        print("   ④ 试听  ：❌ %s" % e)
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
