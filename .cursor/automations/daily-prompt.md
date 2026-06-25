# 每日摄影推荐 - Agent 完整 Prompt

## 执行步骤

### 1. 执行生成脚本
运行 `python3 scripts/generate.py`，该脚本会：
- 从 `data/bank.json` 读取摄影作品库
- 根据 `data/history.json` 排除近期已推荐作品，避免重复
- 随机选取 20 幅作品作为今日推荐
- 将选中作品记录到 `data/history.json`
- 使用 `templates/index.html` 模板生成 `docs/index.html`
- 归档旧的 `docs/index.html` 到 `docs/archive/YYYY-MM-DD.html`

### 2. 验证生成结果
- 确认 `docs/index.html` 已更新且文件非空
- 确认 `docs/archive/` 中有新的归档文件
- 确认 `data/history.json` 已更新

### 3. 提交并推送
```bash
git add -A
git diff --cached --stat
git commit -m "daily: $(date +%Y-%m-%d) 每日摄影推荐更新"
git push origin main
```

### 4. 验证部署
确认 GitHub Pages URL（`https://<username>.github.io/daily-photos/`）可正常访问，页面显示今日日期和最新推荐。

## 生成准则

- 每期 20 幅作品
- 覆盖至少 5 种不同风格（风景、街拍、肖像、纪实、建筑、自然、光影、黑白）
- 大师作品与新锐摄影师各占一定比例
- 描述文字需包含：构图亮点、光影运用、情感表达
- CSS 样式通过 `docs/style.css` 外链引入，不在 HTML 中内联

## 异常处理

| 问题 | 处理 |
|------|------|
| `generate.py` 执行失败 | 查看错误日志，修复后重试 |
| `bank.json` 作品不足 20 幅 | 放宽重复推荐限制，允许最近 30 天外的作品再次出现 |
| `git push` 失败 | 检查网络连接，重试一次；若仍失败则跳过推送并报告 |
| GitHub Pages 不更新 | 检查 Settings → Pages 是否指向 `main` 分支的 `/docs` 目录 |
| 图片链接失效 | 在 `bank.json` 中标记该作品为 `broken: true`，下次生成时排除 |
