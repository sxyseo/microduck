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
   "$WS/docs/URT2-HL2915接线组装与测试指南.md" "$WS/docs/URT2-HD1910接线组装与测试指南.md" \
   "$WS/docs/IMU集成教程-I2C直读与imu_to_dxl.md" "$WS/docs/microduck-community-kit使用教程.md" \
   "$WS/docs/飞特官方BAM发布解读.md" \
   "$WS/docs/HD1910仿真迁移与PPO训练教程.md" "$WS/docs/ToF集成教程-I2C识别与tofd验收.md" content/
cp "$WS/microduck-replica/docs/训练参数调整与新动作开发指南.md" content/
cp "$WS/docs/content-roadmap.md" content/
mkdir -p public/learn/images
cp "$WS/docs/images/hd1910-pinout.png" "$WS/docs/images/tof-bus-map.png" \
   "$WS/docs/images/tof-ds-cover-module.png" "$WS/docs/images/tof-ds-fig1-fov.png" \
   "$WS/docs/images/tof-ds-8x8-zones.png" "$WS/docs/images/tof-ds-block-diagram.png" \
   "$WS/docs/images/tof-st-xnucleo-53l5a1.jpg" public/learn/images/

echo "content/ 已同步:$(find content -name '*.md' | wc -l | tr -d ' ') 个 md"
