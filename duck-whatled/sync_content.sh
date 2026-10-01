#!/bin/bash
# 同步工作区最新内容到本仓库 content/ 快照。
# 用法: ./sync_content.sh   (在仓库根目录执行)
set -euo pipefail
WS=/Volumes/dev/dev/microduck

cp -r "$WS/docs/course"       content/
cp -r "$WS/docs/deep-dive"    content/
mkdir -p content/research
cp "$WS/docs/research/physical-ai-robot-startup-research-2026-09-04.md" content/research/
cp "$WS/docs/新手学习文档.md" "$WS/docs/进阶学习文档-训练仿真与部署.md" \
   "$WS/docs/macOS舵机调试与图纸查看指南.md" "$WS/docs/HL-2915路线全流程教程.md" \
   "$WS/docs/HD1910仿真迁移与PPO训练教程.md" content/
cp "$WS/microduck-replica/docs/训练参数调整与新动作开发指南.md" content/
cp "$WS/docs/content-roadmap.md" content/

echo "content/ 已同步:$(find content -name '*.md' | wc -l | tr -d ' ') 个 md"
