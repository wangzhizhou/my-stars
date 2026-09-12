#!/usr/bin/env python3
"""
把 GitHub Stars 同步成一个可全文搜索的 Awesome List。

用法：
    python sync_stars.py                       # 用户名从 GITHUB_REPOSITORY / STARS_USER 推断
    STARS_USER=wangzhizhou python sync_stars.py
    GH_TOKEN=xxx python sync_stars.py          # 可选，仅用来提高 API 限额

产出：
    README.md        分类后的收藏清单（自动生成，不要手改）
    data/stars.json  原始快照，方便 diff / 二次加工

配置：
    categories.yml   分类规则（按顺序匹配，先匹配到的分类生效）
    notes.yml        给单个仓库追加备注（会渲染成引用行，可被搜索）
    header.md        README 顶部自定义内容（可选）
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖，请先执行：pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent
API = "https://api.github.com"
PER_PAGE = 100

DEFAULT_HEADER = """# ⭐ Awesome Stars

> 自动同步的 GitHub 收藏索引。本文件由 `sync_stars.py` 生成，**请勿手动编辑**。
> 想调整分类请改 `categories.yml`，想加备注请改 `notes.yml`。
"""


def log(*args) -> None:
    print(*args, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #
def api_get(url: str, token: str | None):
    req = urllib.request.Request(url)
    # star+json 才会返回 starred_at 字段
    req.add_header("Accept", "application/vnd.github.star+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "awesome-stars-sync")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    last_err = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            last_err = f"HTTP {exc.code}: {body}"
            if exc.code in (403, 429) and attempt < 3:
                wait = 30
                reset = exc.headers.get("X-RateLimit-Reset")
                if reset and reset.isdigit():
                    wait = max(5, int(reset) - int(time.time()) + 2)
                wait = min(wait, 300)
                log(f"  ! 触发限额/被限流（{exc.code}），{wait}s 后重试…")
                time.sleep(wait)
                continue
            break
        except urllib.error.URLError as exc:
            last_err = f"网络错误: {exc.reason}"
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            break
    raise SystemExit(f"请求失败：{url}\n{last_err}")


def resolve_user() -> str:
    user = os.environ.get("STARS_USER", "").strip()
    if user:
        return user
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        return repo.split("/", 1)[0]
    raise SystemExit("请通过环境变量指定用户名，例如：STARS_USER=yourname python sync_stars.py")


def fetch_stars(user: str, token: str | None) -> list[dict]:
    stars: list[dict] = []
    page = 1
    while True:
        url = (
            f"{API}/users/{urllib.parse.quote(user)}/starred"
            f"?per_page={PER_PAGE}&page={page}&sort=created&direction=desc"
        )
        data = api_get(url, token)
        if not isinstance(data, list) or not data:
            break

        for item in data:
            repo = item.get("repo", item)
            starred_at = item.get("starred_at")
            stars.append(
                {
                    "full_name": repo["full_name"],
                    "name": repo["name"],
                    "owner": repo["owner"]["login"],
                    "url": repo["html_url"],
                    "description": (repo.get("description") or "").strip(),
                    "language": repo.get("language") or "",
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "topics": [t for t in (repo.get("topics") or []) if t],
                    "archived": bool(repo.get("archived")),
                    "fork": bool(repo.get("fork")),
                    "license": ((repo.get("license") or {}).get("spdx_id") or ""),
                    "created_at": repo.get("created_at"),
                    "pushed_at": repo.get("pushed_at"),
                    "starred_at": starred_at,
                }
            )

        log(f"  已抓取 {len(stars)} 个 star（第 {page} 页）")
        if len(data) < PER_PAGE:
            break
        page += 1

    if not stars:
        raise SystemExit(f"用户 {user} 没有任何 star，或该用户不存在。")
    return stars


# --------------------------------------------------------------------------- #
# 匹配规则
# --------------------------------------------------------------------------- #
def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _match_one(repo: dict, cond: dict) -> bool:
    """单个条件块内部是 AND 语义。"""
    if not isinstance(cond, dict):
        return False

    topics = {t.lower() for t in repo["topics"]}

    if "topics_any" in cond:
        want = {str(t).lower() for t in _as_list(cond["topics_any"])}
        if not (topics & want):
            return False

    if "topics_all" in cond:
        want = {str(t).lower() for t in _as_list(cond["topics_all"])}
        if not want.issubset(topics):
            return False

    if "language" in cond:
        want = {str(v).lower() for v in _as_list(cond["language"])}
        if repo["language"].lower() not in want:
            return False

    if "name_regex" in cond:
        pat = str(cond["name_regex"])
        if not (re.search(pat, repo["name"]) or re.search(pat, repo["full_name"])):
            return False

    if "description_regex" in cond:
        if not re.search(str(cond["description_regex"]), repo["description"], re.IGNORECASE):
            return False

    if "min_stars" in cond and repo["stars"] < int(cond["min_stars"]):
        return False

    if "max_stars" in cond and repo["stars"] > int(cond["max_stars"]):
        return False

    if "archived" in cond and repo["archived"] is not bool(cond["archived"]):
        return False

    return True


def category_matches(repo: dict, category: dict) -> bool:
    """
    match     : 单个条件块，内部 AND
    match_any : 条件块列表，任意命中即可（OR）
    两者同时存在时都要满足。
    """
    match = category.get("match")
    match_any = category.get("match_any")

    if match is not None and not _match_one(repo, match):
        return False
    if match_any is not None and not any(_match_one(repo, c) for c in _as_list(match_any)):
        return False
    return match is not None or match_any is not None


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def fmt_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%d")


def render_entry(repo: dict, note: str, show_topics: int) -> str:
    label = f"**{repo['name']}**"
    if repo["archived"]:
        label = f"~~{label}~~ `已归档`"

    parts = [f"⭐ {fmt_count(repo['stars'])}"]
    if repo["language"]:
        parts.append(f"`{repo['language']}`")
    if repo["license"] and repo["license"] != "NOASSERTION":
        parts.append(f"`{repo['license']}`")

    line = f"- [{label}]({repo['url']}) · " + " · ".join(parts)

    if repo["description"]:
        line += f" — {repo['description']}"

    if show_topics and repo["topics"]:
        chips = " ".join(f"`#{t}`" for t in repo["topics"][:show_topics])
        line += f" {chips}"

    if note:
        line += f"\n  > 💡 {note}"

    return line


def render_readme(
    stars: list[dict],
    categories: list[dict],
    buckets: dict[str, list[dict]],
    notes: dict[str, str],
    settings: dict,
    user: str,
    header: str,
) -> str:
    show_topics = int(settings.get("show_topics", 0) or 0)
    max_per = int(settings.get("max_per_category", 0) or 0)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = [header.rstrip(), ""]

    out.append("---")
    out.append("")
    out.append(
        f"📊 **{len(stars)}** 个仓库 · **{len(categories)}** 个分类 · "
        f"最后同步：`{now}` · [github.com/{user}?tab=stars](https://github.com/{user}?tab=stars)"
    )
    out.append("")

    # 目录（用显式锚点，避免中文/emoji 标题锚点不稳定）
    out.append("## 目录")
    out.append("")
    for idx, cat in enumerate(categories, start=1):
        count = len(buckets[cat["_name"]])
        if count:
            out.append(f"- [{cat['_name']}](#cat-{idx}) · {count}")
    out.append("")

    for idx, cat in enumerate(categories, start=1):
        items = buckets[cat["_name"]]
        if not items:
            continue

        out.append(f'<a id="cat-{idx}"></a>')
        out.append("")
        out.append(f"## {cat['_name']} ({len(items)})")
        out.append("")
        if cat.get("description"):
            out.append(f"> {cat['description']}")
            out.append("")

        shown = items[:max_per] if max_per else items
        for repo in shown:
            out.append(render_entry(repo, notes.get(repo["full_name"], ""), show_topics))
        if max_per and len(items) > max_per:
            out.append(f"- … 还有 {len(items) - max_per} 个（见 `data/stars.json`）")
        out.append("")

    out.append("---")
    out.append("")
    out.append("*由 [sync_stars.py](sync_stars.py) 自动生成。*")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def load_yaml(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return default if data is None else data


def main() -> int:
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip() or None
    user = resolve_user()

    config = load_yaml(ROOT / "categories.yml", {})
    settings = config.get("settings") or {}
    raw_categories = config.get("categories") or []
    exclude = {str(x).lower() for x in (config.get("exclude") or [])}
    notes_raw = (load_yaml(ROOT / "notes.yml", {}) or {}).get("notes") or {}
    notes = {str(k): str(v) for k, v in notes_raw.items()}

    if not raw_categories:
        raise SystemExit("categories.yml 里没有定义任何 categories，先补上再跑。")

    categories: list[dict] = []
    for cat in raw_categories:
        if not isinstance(cat, dict) or not cat.get("name"):
            continue
        cat = dict(cat)
        cat["_name"] = str(cat["name"])
        categories.append(cat)

    fallback_name = str(settings.get("fallback_name") or "📦 未分类")

    log(f"→ 用户：{user}（{'带 token' if token else '匿名，限额较低'}）")
    stars = fetch_stars(user, token)
    stars = [r for r in stars if r["full_name"].lower() not in exclude]
    log(f"→ 共 {len(stars)} 个仓库，开始分类…")

    buckets: dict[str, list[dict]] = {c["_name"]: [] for c in categories}
    buckets[fallback_name] = []

    for repo in stars:
        for cat in categories:
            if category_matches(repo, cat):
                buckets[cat["_name"]].append(repo)
                break
        else:
            buckets[fallback_name].append(repo)

    # 排序：默认按 star 数降序，可用 settings.sort 切换
    sort_mode = str(settings.get("sort", "stars")).lower()

    def sort_key(repo: dict):
        if sort_mode == "name":
            return repo["name"].lower()
        if sort_mode in ("starred", "starred_at"):
            return repo.get("starred_at") or ""
        if sort_mode == "updated":
            return repo.get("pushed_at") or ""
        return repo["stars"]

    reverse = sort_mode != "name"
    for name in buckets:
        buckets[name].sort(key=sort_key, reverse=reverse)

    if not settings.get("include_archived", True):
        for name in buckets:
            buckets[name] = [r for r in buckets[name] if not r["archived"]]

    # 未分类永远放最后
    ordered_categories = categories + [{"_name": fallback_name}]

    header_text = (ROOT / "header.md").read_text(encoding="utf-8") if (ROOT / "header.md").exists() else DEFAULT_HEADER
    readme = render_readme(stars, ordered_categories, buckets, notes, settings, user, header_text)

    (ROOT / "README.md").write_text(readme, encoding="utf-8")

    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    snapshot = {
        "user": user,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(stars),
        "categories": {c["_name"]: [r["full_name"] for r in buckets[c["_name"]]] for c in ordered_categories},
        "repos": stars,
    }
    (data_dir / "stars.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    log("")
    for cat in ordered_categories:
        log(f"  {cat['_name']:<24} {len(buckets[cat['_name']]):>4}")
    log(f"\n✅ 完成：README.md / data/stars.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
