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
│   ├── enrich_bank.py            # 多图床作品库扩充（仅外链，不下载图片）
│   └── generate.py               # 核心生成脚本
├── templates/
│   └── index.html                # 主页 HTML 模板
├── data/
│   ├── bank.json                 # 摄影作品库（多图床 HTTPS 外链）
│   └── history.json              # 推荐历史（gitignore）
└── .gitignore
```

## 使用方式

### 手动生成

```bash
# 首次或库不足时批量扩充
python3 scripts/enrich_bank.py --bootstrap

# 日常：增量拉取 + 生成
python3 scripts/enrich_bank.py
python3 scripts/generate.py
```

### 自动生成（Cursor Automation）

1. 在 Cursor 中创建 Automation，trigger 设为 `cron: "0 9 * * *"`（每天 9:00）
2. Prompt 字段填入 `.cursor/automations/daily-trigger.txt` 的内容
3. Automation 触发时 Agent 自动执行 `enrich_bank.py` → `generate.py` → commit → 直接 push 到 `main` 分支（不创建 PR）

### 本地预览

```bash
cd docs && python3 -m http.server 8000
# 访问 http://localhost:8000
```

## 部署

1. 在 GitHub 创建仓库并推送代码
2. Settings → Pages → Source 选择 `main` 分支 + `/docs` 目录
3. 访问 `https://<username>.github.io/daily-photos/`

## 数据源（多图床外链）

所有图片均为 **HTTPS CDN 外链**，仓库内不存放图片文件。

| source | 图床 | 认证 |
|--------|------|------|
| `openverse` / `flickr` | Openverse 聚合 | 免 Key |
| `wikimedia` | Wikimedia Commons | 免 Key |
| `nasa` | NASA Image Library | 免 Key |
| `met` | Met Museum Open Access | 免 Key |
| `rawpixel` | Rawpixel（经 Openverse） | 免 Key |
| `unsplash` | Unsplash | 免 Key |
| `pexels` | Pexels | 环境变量 `PEXELS_API_KEY` |
| `pixabay` | Pixabay | 环境变量 `PIXABAY_API_KEY` |
| `flickr` | Flickr API | 环境变量 `FLICKR_API_KEY` |

作品库 `data/bank.json` 由 `enrich_bank.py` 维护。每期从库中均衡选取 20 幅（风格 ≥ 5 种、图床 ≥ 4 种），30 天内不重复推荐同一幅作品。

### 可选 API Key

在 Cursor Automation 环境变量或本地 shell 中设置：

```bash
export PEXELS_API_KEY=your_key
export PIXABAY_API_KEY=your_key
export FLICKR_API_KEY=your_key
```

未配置时自动跳过对应图床，不影响免 Key 源正常运行。
