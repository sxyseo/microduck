# duck-whatled · 什么鸭 WhatDuck

<https://duck.whatled.com> 的完整源码与内容:Microduck 复刻项目的公开学习站。

## 内容

| 板块 | 规模 | 源目录 |
|---|---|---|
| 学习手册 | 4 份 | `content/*.md` |
| 什么鸭公开课 | 30 课 | `content/course/` |
| 深读 Microduck | 200 篇 · 16 辑 | `content/deep-dive/` |
| 实体 AI 创业调研 | 1 篇 | `content/research/` |

## 构建与发布

```bash
./sync_content.sh                 # 1. 从工作区同步最新内容到 content/(可选,仓库内快照即可独立构建)
python3 -m venv /tmp/mdenv && /tmp/mdenv/bin/pip install markdown   # 首次
/tmp/mdenv/bin/python build_learn.py    # 2. content/ → public/learn/*.html(自动发现课程与解读篇目)
npx wrangler deploy                     # 3. 发布到 duck.whatled.com(Cloudflare)
```

- `build_learn.py` 优先读取仓库内 `content/` 快照,因此本仓库自包含、可独立构建;
  content 与 `/Volumes/dev/dev/microduck/docs/` 原稿的一致性由 `sync_content.sh` 保证。
- 课程与解读文章按文件名自动发现(`NN-*.md` → `/learn/course-NN`、`/learn/deep-NN`),新篇目零登记。
- 内容规划见 `content/content-roadmap.md`;每月例行校对由自动化任务执行(数据一致性 → 链接体检 → 构建 → 部署 → 推送)。

## 声明

非官方个人学习与研究项目,与 Pollen Robotics 无关;Microduck 的设计与相关资料版权归其权利人所有。
