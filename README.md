# 每日摄影推荐 | Daily Photography

每天自动推荐 20 幅优秀摄影作品，通过 GitHub Pages 托管。由 Cursor Automation 定时触发生成。

## 项目结构

```
daily-photos/
├── .cursor/automations/          # Cursor Automation 配置
│   ├── daily-trigger.txt         # Automation 编辑器 prompt（一行触发指令）
│   └── daily-prompt.md           # Agent 完整执行逻辑
├── docs/                         # GitHub Pages 根目录
│   ├── index.html                # 今日推荐主页
│   ├── style.css                 # 全局样式
│   ├── archive/                  # 往期归档
│   └── .nojekyll                 # 禁用 Jekyll
├── scripts/
│   ├── generate.py               # 核心生成脚本（含抓取 + 页面生成）
│   └── fetch_photos.py           # 网络抓取脚本（Openverse / Wikimedia）
├── templates/
│   └── index.html                # 主页 HTML 模板
├── data/
│   ├── bank.json                 # 摄影作品库
│   └── history.json              # 推荐历史（gitignore）
└── .gitignore
```

## 使用方式

### 手动生成

```bash
python3 scripts/generate.py
```

### 自动生成（Cursor Automation）

1. 在 Cursor 中创建 Automation，trigger 设为 `cron: "0 9 * * *"`（每天 9:00）
2. Prompt 字段填入 `.cursor/automations/daily-trigger.txt` 的内容
3. Automation 触发时 Agent 自动执行 `generate.py` → commit → push

### 本地预览

```bash
cd docs && python3 -m http.server 8000
# 访问 http://localhost:8000
```

## 部署

1. 在 GitHub 创建仓库并推送代码
2. Settings → Pages → Source 选择 `main` 分支 + `/docs` 目录
3. 访问 `https://<username>.github.io/daily-photos/`

## 数据源

每日自动从网络抓取 CC 授权摄影作品（[Openverse](https://openverse.org/) 为主，[Wikimedia Commons](https://commons.wikimedia.org/) 为补充），覆盖 8 种风格：风景、街拍、肖像、纪实、建筑、自然、光影、黑白。

- 抓取结果合并到 `data/bank.json`，通过图片 URL 与 source_id **永久去重**
- 每期推荐 20 幅 freshly fetched 作品，确保与历史不重复
- 网络不可用时降级从作品库选取未推荐作品

```bash
# 仅测试网络抓取
python3 scripts/fetch_photos.py
```
