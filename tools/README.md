# tools/

## reorganize_lists.py

重排 GitHub Stars 页面上的 **Lists**（不是 star 本身）。

### 为什么需要 `user` scope

读 List 用 `repo` scope 就够，但**写 List 必须有 `user` scope**。首次使用先跑一次：

```bash
gh auth refresh -h github.com -s user
```

（浏览器授权。原有的 `repo` / `workflow` / `gist` 等 scope 都会保留。）

### 用法

```bash
export GH_TOKEN=$(gh auth token)

python3 tools/reorganize_lists.py            # 空跑，只打印方案
python3 tools/reorganize_lists.py --apply    # 真正执行
```

**永远先空跑。** 空跑会告诉你：每个目标 List 有多少条目、来自哪些 List、
会删掉哪些、有没有仓库会变成孤儿、需要改动多少个仓库的归属。

### 怎么改方案

编辑脚本里的 `PLAN`：

```python
{
    "name":   "🍎 Swift / iOS",          # 目标 List 名
    "desc":   "Swift / iOS 开发与生态",   # 目标 List 描述
    "host":   "Swift",                   # 用哪个已存在的 List 改造（保留 ID）；None = 新建
    "absorb": ["SwiftUI", "Vapor"],      # 要被吸收并删除的 List
},
```

三个常见操作：

| 想做的事 | 怎么写 |
| --- | --- |
| **合并**（A + B → A） | `host: "A"`，`absorb: ["B"]` |
| **重命名 / 改描述** | `host: "旧名"`，`name` / `desc` 写新的，`absorb: []` |
| **新建一个 List** | `host: None`，`absorb: []`（或带上要吸收的） |

**没写进 `PLAN` 的 List 会原样保留**，不会被误删。

### 安全性

- **不会取消任何 star**。Lists 只是集合，仓库被移出 List 不影响 star 状态。
- **不会让仓库失去归属**。目标 List 的成员是「host + 所有 absorb」的并集。
- **多归属会被保留**。一个仓库如果同时在 A 和 B，合并后仍同时属于目标 A' 和 B'，
  不会被去重掉。
- 唯一无法通过 API 做的：**List 的显示顺序**，需要在页面上手动拖拽。

### 踩过的坑

- `updateUserListsForItem` 的 payload 字段是 `user`（不是 `list`），
  `deleteUserList` 同样是 `user`；`updateUserList` / `createUserList` 才是 `list`。
- GraphQL 的 `lists` 连接**不支持 `orderBy`**。
- 别在 WSL 里用 `setsid nohup gh ...` 跑 OAuth——进程会被丢进 Windows 的
  Session 0（服务会话），接不到授权结果；而 GitHub 在签发新 token 时会**立即吊销旧 token**，
  结果就是 `gh` 直接失效。要跑 OAuth 就在自己的终端里跑。

### 历史

| 日期 | 变化 |
| --- | --- |
| 2026-09-12 | 首次整理：32 个 List → 8 个（GitHub 侧栏不分页的上限）。完整映射见脚本里的 `PLAN_HISTORY_2026_09_12` |
