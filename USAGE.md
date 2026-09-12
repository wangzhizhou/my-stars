# 使用说明

一套「把 GitHub Stars 变成可搜索、可分类、自动更新仓库」的方案。

## 文件结构

```
awesome-stars/
├── categories.yml              # 分类规则（改这个）
├── notes.yml                   # 单仓库备注（改这个）
├── header.md                   # README 顶部内容（改这个）
├── sync_stars.py               # 同步脚本
├── data/stars.json             # 原始快照（自动生成）
├── README.md                   # 最终清单（自动生成，别手改）
└── .github/workflows/sync.yml  # 每天自动跑
```

## 本地跑一次

```bash
pip install -r requirements.txt
STARS_USER=wangzhizhou python sync_stars.py
```

可选：设置 `GH_TOKEN` 环境变量提高 API 限额（匿名每小时 60 次请求，够用但不保险）。

## 推到 GitHub

1. 在 GitHub 新建一个**公开**仓库，名字建议就叫 `awesome-stars`（已经在 `header.md` 里引用了这个路径，改名的话记得同步改）。
2. 推送代码：

   ```bash
   cd awesome-stars
   git init -b main
   git add .
   git commit -m "init"
   git remote add origin https://github.com/wangzhizhou/awesome-stars.git
   git push -u origin main
   ```

3. **打开写权限**：仓库 `Settings → Actions → General → Workflow permissions`，选 **Read and write permissions**，保存。
   （不加这步机器人无法把生成的 README 提交回来。）

4. 打开 `Actions` 标签页 → `Sync Stars` → `Run workflow` 手动跑一次验证。

之后就每天 UTC 20:10 自动更新了。

## 日常怎么用

| 想做的事 | 怎么做 |
| --- | --- |
| 搜索收藏 | 打开仓库按 `t` 全文搜索，或 GitHub 搜索 `repo:wangzhizhou/awesome-stars 关键词` |
| 调整分类 | 改 `categories.yml`，push 后自动重新生成 |
| 加备注 | 改 `notes.yml`，例如 `"owner/repo": "做 XX 时用它"` |
| 排除某些仓库 | 加到 `categories.yml` 的 `exclude` 列表 |
| 看原始数据 | `data/stars.json`（含 star 数、topics、语言、收藏时间） |

## 分类规则怎么调

匹配是**自上而下、先命中先算**。所以：

1. 先看生成的 README 里 **📦 未分类** 有多少。
2. 从里面挑出成规模的同类仓库，给 `categories.yml` 加一条新规则（放在合适位置）。
3. 重复几轮，未分类就会降到很低。

条件写法：

```yaml
- name: "🦀 Rust 生态"
  match_any:
    - topics_any: [rust, rust-lang]        # topics 精确命中任意一个
    - language: Rust                        # 或语言
    - name_regex: "(?i)(tokio|serde)"       # 或正则
```

`match` 是块内 AND，`match_any` 是列表内 OR；两者同时写则都要满足。

## 注意事项

- GitHub 的 schedule 工作流在仓库**连续 60 天无活动**后会被自动停用。本方案每次同步都会产生一次 commit（有变化时），足以保持活跃；万一被停了，去 Actions 页面点一下 Enable 即可。
- Stars 列表本身是公开数据，脚本走的是公开 API，不需要额外的 PAT。
- 想改成私有仓库也可以，只是就不能直接分享了。
