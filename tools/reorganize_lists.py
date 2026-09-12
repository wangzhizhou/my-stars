#!/usr/bin/env python3
"""
重排 GitHub Stars Lists —— 合并 / 重命名 / 清理你的 List。

原理
----
一个「目标 List」= 一个 host（已存在的 List，会被重命名保留）+ 若干个被吸收的 List。
被吸收 List 里的仓库会并入目标 List，然后把空掉的 List 删掉。
被吸收 List 的类型、描述、ID 都不重要，只有仓库归属会被搬运。

**不会取消 star**，也不会让任何仓库失去归属。

用法
----
    gh auth refresh -h github.com -s user      # 首次需要：写 List 必须有 user scope
    export GH_TOKEN=$(gh auth token)

    python3 tools/reorganize_lists.py            # 空跑，只打印方案
    python3 tools/reorganize_lists.py --apply    # 真正执行

改 PLAN 就能调整方案。想把某个 List 拆开，就把它当 host、absorb 留空；
想新建一个 List，把 host 写成 None。

历史
----
2026-09-12  首次整理：32 个 List → 8 个（正好是 GitHub 侧栏不分页的上限）。
            方案见文件末尾 PLAN_HISTORY_2026_09_12。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com/graphql"


# ══════════════════════════════════════════════════════════════════════════
# 方案：想调整分类只改这里
#
#   name   : 目标 List 的名字
#   desc   : 目标 List 的描述
#   host   : 用哪个已存在的 List 改造成目标（保留其 ID）；写 None 表示新建
#   absorb : 要被吸收并删除的 List 名字列表
#
# 仓库可以同时属于多个 List —— 如果一个仓库在目标 A 和目标 B 里都有，
# 合并后它仍会同时属于 A 和 B（多归属会被保留，不会被去重掉）。
# ══════════════════════════════════════════════════════════════════════════
PLAN = [
    {
        "name": "🍎 Swift / iOS",
        "desc": "Swift / iOS / macOS 开发、架构与生态",
        "host": "🍎 Swift / iOS",
        "absorb": [],
    },
    {
        "name": "🖥️ Server-Side Swift",
        "desc": "服务端 Swift：Vapor、NIO、SSWG 生态",
        "host": "🖥️ Server-Side Swift",
        "absorb": [],
    },
    {
        "name": "🔌 硬件 / 嵌入式",
        "desc": "嵌入式、固件、树莓派、IoT",
        "host": "🔌 硬件 / 嵌入式",
        "absorb": [],
    },
    {
        "name": "⛏️ Minecraft",
        "desc": "Minecraft 插件、模组、服务端",
        "host": "⛏️ Minecraft",
        "absorb": [],
    },
    {
        "name": "🤖 AI / Agent",
        "desc": "大模型、Agent、MCP、本地推理",
        "host": "🤖 AI / Agent",
        "absorb": [],
    },
    {
        "name": "🛠️ Tools / CLI",
        "desc": "命令行工具、效率软件、自建服务、逆向与安全工具",
        "host": "🛠️ Tools / CLI",
        "absorb": [],
    },
    {
        "name": "📌 待读 / 灵感",
        "desc": "想读、想看、想做的东西，定期清空",
        "host": "📌 待读 / 灵感",
        "absorb": [],
    },
    {
        "name": "🧰 语言 / 生态",
        "desc": "Rust / Ruby / JavaScript / Python 生态",
        "host": "🧰 语言 / 生态",
        "absorb": [],
    },
]

PLAN_HISTORY_2026_09_12 = {
    "🍎 Swift / iOS": ["Swift", "SwiftUI", "Objective-C", "macOS", "App", "XR", "Archtecture", "TDD"],
    "🖥️ Server-Side Swift": ["Swift On Server", "Vapor"],
    "🔌 硬件 / 嵌入式": ["RaspberryPi", "Embedded Swift"],
    "⛏️ Minecraft": ["Minecraft"],
    "🤖 AI / Agent": ["AI", "MCP", "OpenClaw", "PersonalAI"],
    "🛠️ Tools / CLI": ["Tools", "CLI", "Visual Studio Code", "Docs", "Services", "逆向开发"],
    "📌 待读 / 灵感": ["✨ Inspiration", "ToDo", "科技前沿", "SoftSkill", "工作室"],
    "🧰 语言 / 生态": ["Rust", "Ruby", "js", "Python"],
}


# ── 认证 ─────────────────────────────────────────────────────────────────
def get_token() -> str:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    for gh in filter(None, [os.environ.get("GH_BIN"), "gh", "/mnt/c/Program Files/GitHub CLI/gh.exe"]):
        is_abs = os.path.sep in gh
        if is_abs and not os.path.exists(gh):
            continue
        if not is_abs and not shutil.which(gh):
            continue
        r = subprocess.run([gh, "auth", "token"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    sys.exit("找不到 token。请先 export GH_TOKEN=$(gh auth token)，或确认 gh 已登录。")


TOKEN = get_token()


def gql(query: str, variables: dict | None = None, retries: int = 4):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "reorganize-lists")
    last = ""
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            out = json.loads(e.read().decode() or "{}")
        except urllib.error.URLError as e:
            last = str(e)
            time.sleep(3)
            continue
        if "errors" in out:
            last = json.dumps(out["errors"], ensure_ascii=False)
            if "INSUFFICIENT_SCOPES" in last:
                sys.exit(f"token 缺少 user scope。请先执行：gh auth refresh -h github.com -s user\n{last[:200]}")
            time.sleep(2)
            continue
        return out["data"]
    sys.exit(f"GraphQL 请求失败：{last[:300]}")


# ── 读取 ─────────────────────────────────────────────────────────────────
LIST_META = """
query($after: String) {
  viewer {
    login
    lists(first: 100, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { id name slug isPrivate description items(first: 1) { totalCount } }
    }
  }
}
"""

LIST_ITEMS = """
query($listId: ID!, $after: String) {
  node(id: $listId) {
    ... on UserList {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { ... on Repository { id nameWithOwner } }
      }
    }
  }
}
"""


def fetch():
    metas, after = [], None
    while True:
        c = gql(LIST_META, {"after": after})["viewer"]["lists"]
        metas.extend(c["nodes"])
        if not c["pageInfo"]["hasNextPage"]:
            break
        after = c["pageInfo"]["endCursor"]

    lists, repos = {}, {}
    for m in metas:
        items, cursor = [], None
        while True:
            conn = gql(LIST_ITEMS, {"listId": m["id"], "after": cursor})["node"]["items"]
            items.extend(conn["nodes"])
            if not conn["pageInfo"]["hasNextPage"]:
                break
            cursor = conn["pageInfo"]["endCursor"]
        lists[m["name"]] = {**m, "repos": [i["id"] for i in items]}
        for i in items:
            repos.setdefault(i["id"], {"repo": i["nameWithOwner"], "lists": []})
            repos[i["id"]]["lists"].append(m["name"])
    return lists, repos


# ── 主流程 ───────────────────────────────────────────────────────────────
def main():
    apply_changes = "--apply" in sys.argv
    lists, repos = fetch()

    # 校验方案引用的 List 存在
    for p in PLAN:
        for n in filter(None, [p["host"], *p["absorb"]]):
            if n not in lists:
                sys.exit(f"方案里的 List “{n}” 在线上找不到。请检查是否已经执行过，或名字写错。")
        if p["host"] is None and p["name"] in lists:
            sys.exit(f"要新建的 “{p['name']}” 已经存在，请把它设成 host。")

    remap = {n: p["name"] for p in PLAN for n in filter(None, [p["host"], *p["absorb"]])}
    covered = set(remap)
    untouched = [n for n in lists if n not in covered]
    absorbed = {n for p in PLAN for n in p["absorb"]}

    # 计算迁移后每个目标 List 的成员
    target = {p["name"]: set() for p in PLAN}
    for rid, r in repos.items():
        for old in r["lists"]:
            target[remap[old]].add(rid)

    total_before = sum(len(v["repos"]) for v in lists.values())
    total_after = sum(len(v) for v in target.values())

    print("═" * 78)
    print(f"{'目标 List':<28}{'条目':>5}   ← 来源")
    print("═" * 78)
    for p in PLAN:
        src = " + ".join(filter(None, [p["host"] or "（新建）", *p["absorb"]]))
        print(f"{p['name']:<28}{len(target[p['name']]):>5}   ← {src}")
    print("─" * 78)
    print(f"{'合计':<28}{total_after:>5}   （迁移前 {total_before} 条归属）")
    print()
    print(f"List 数量: {len(lists)} → {len(lists) - len(absorbed)}" +
          (f"（另有 {sum(1 for p in PLAN if p['host'] is None)} 个新建）" if any(p["host"] is None for p in PLAN) else ""))
    print(f"将删除  : {len(absorbed)} 个 {sorted(absorbed) if absorbed else ''}")
    if untouched:
        print(f"方案未涉及、保持原样: {untouched}")

    orphans = [r["repo"] for r in repos.values() if not r["lists"]]
    print(f"未归属任何 List 的仓库: {len(orphans)}")

    old_id = {v["name"]: v["id"] for v in lists.values()}
    new_id = {p["name"]: old_id.get(p["host"]) for p in PLAN}
    changes = sum(
        1 for r in repos.values()
        if {old_id[x] for x in r["lists"]} != {new_id[remap[x]] for x in r["lists"]}
    )
    print(f"需要更新归属的仓库: {changes} / {len(repos)}")

    if not apply_changes:
        print("\n这是空跑。确认后加 --apply 执行。")
        return

    print("\n开始执行…")
    for p in PLAN:
        host_name = p["host"]
        if host_name is None:
            d = gql("""mutation($i: CreateUserListInput!) { createUserList(input: $i) { list { id name } } }""",
                    {"i": {"name": p["name"], "description": p["desc"]}})
            new_id[p["name"]] = d["createUserList"]["list"]["id"]
            print(f"  ＋ 新建 {p['name']}")
            continue
        host = lists[host_name]
        if host["name"] != p["name"] or (host.get("description") or "") != p["desc"]:
            gql("""mutation($i: UpdateUserListInput!) { updateUserList(input: $i) { list { id name } } }""",
                {"i": {"listId": host["id"], "name": p["name"], "description": p["desc"]}})
            print(f"  ✎ 重命名 {host_name} → {p['name']}")

    done = 0
    for rid, r in repos.items():
        before = {old_id[x] for x in r["lists"]}
        after = {new_id[remap[x]] for x in r["lists"]}
        if before == after:
            continue
        gql("""mutation($i: UpdateUserListsForItemInput!) { updateUserListsForItem(input: $i) { user { login } } }""",
            {"i": {"itemId": rid, "listIds": sorted(after)}})
        done += 1
        if done % 50 == 0:
            print(f"  … 已更新 {done} 个仓库")
    print(f"  ✓ 归属更新完成，共 {done} 个仓库")

    for n in sorted(absorbed):
        gql("""mutation($i: DeleteUserListInput!) { deleteUserList(input: $i) { user { login } } }""",
            {"i": {"listId": lists[n]["id"]}})
        print(f"  ✗ 删除 {n}")

    print("\n✅ 完成。注意：List 显示顺序无法通过 API 设置，需在页面上手动拖拽。")


if __name__ == "__main__":
    main()
