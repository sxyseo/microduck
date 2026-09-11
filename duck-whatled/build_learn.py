#!/usr/bin/env python3
"""把工作区里最近几天写的学习文档转成 duck.whatled.com 风格的静态页面。

用法: /tmp/mdenv/bin/python build_learn.py
"""
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "public" / "learn"
OUT.mkdir(parents=True, exist_ok=True)

DOCS = [
    {
        "src": "/Volumes/dev/dev/microduck/docs/course/README.md",
        "out": "course.html",
        "title": "什么鸭公开课 · 从零看懂一只机器鸭",
        "desc": "写给什么都不懂的新手的系列课:借一只机器鸭的复刻,把机器人、强化学习、硬件、部署一路学通,最后迁移到你自己的领域。六个阶段 30 课。",
        "tag": "COURSE · 系列公开课",
        "date": "2026-09-11",
    },
    {
        "src": "/Volumes/dev/dev/microduck/docs/course/00-导学-这只鸭子是什么.md",
        "out": "course-00.html",
        "title": "第 00 课 · 导学:这只鸭子是什么",
        "desc": "在投入时间之前弄清:这是什么项目、你能学到什么、30 课怎么走。含 6 个关键数字与两个 5 分钟练习。",
        "tag": "LESSON 00 · 阶段 A · 认识它",
        "date": "2026-09-11",
    },
    {
        "src": "/Volumes/dev/dev/microduck/docs/course/01-先让它动起来-浏览器仿真.md",
        "out": "course-01.html",
        "title": "第 01 课 · 先让它动起来:浏览器里开鸭子",
        "desc": "零安装建立两个核心直觉:运行不等于训练;你发目标、策略管过程。",
        "tag": "LESSON 01 · 阶段 A · 认识它",
        "date": "2026-09-11",
    },
    {
        "src": "/Volumes/dev/dev/microduck/docs/research/physical-ai-robot-startup-research-2026-09-04.md",
        "out": "research.html",
        "title": "深度调研 · 低成本实体 AI 机器人创业方向",
        "desc": "如果用开源软件和通用配件自制一台桌面机器人,选哪个产品方向更容易拿到真实反馈?四条创业路线对比、竞品地图、8 周验证方案与风险清单。",
        "tag": "RESEARCH · 深度调研",
        "date": "2026-09-04",
    },
    {
        "src": "/Volumes/dev/dev/microduck/docs/新手学习文档.md",
        "out": "newbie.html",
        "title": "新手学习文档 · 硬件零基础把鸭子做出来",
        "desc": "写给电路、结构、硬件小白:项目地图、十个核心概念、电路图读图五步法、结构入门与 30 天学习计划。",
        "tag": "MANUAL 01 · 新手篇",
        "date": "2026-09-11",
    },
    {
        "src": "/Volumes/dev/dev/microduck/docs/进阶学习文档-训练仿真与部署.md",
        "out": "advanced.html",
        "title": "进阶篇 · 训练模型、仿真与 Rust 部署",
        "desc": "全链路实操:一个下午搭起 MuJoCo 仿真、训练自己的策略、用官方脚本导出 ONNX,再把 Rust 运行时部署到 Radxa Zero 3W。",
        "tag": "MANUAL 02 · 进阶篇",
        "date": "2026-09-11",
    },
    {
        "src": "/Volumes/dev/dev/microduck/microduck-replica/docs/训练参数调整与新动作开发指南.md",
        "out": "training-guide.html",
        "title": "训练参数调整与新动作开发指南",
        "desc": "61 维输入、14 维输出是不能随便动的契约;按目标查文件改参数,用单变量 A/B 实验从走路一步一步做出跑步。",
        "tag": "MANUAL 03 · 训练篇",
        "date": "2026-09-10",
    },
    {
        "src": "/Volumes/dev/dev/microduck/docs/macOS舵机调试与图纸查看指南.md",
        "out": "servo-debug.html",
        "title": "macOS 舵机调试、ID 设置与图纸查看手册",
        "desc": "SG90 过树莓派的四课实验、总线舵机的供电与共地、Dynamixel Wizard 改 ID 的精确操作,以及 CAD 与电路图在 macOS 上用什么软件看。",
        "tag": "MANUAL 04 · 调试篇",
        "date": "2026-09-11",
    },
]


def gh_slug(value: str, separator: str = "-") -> str:
    """GitHub 风格锚点:文档里手写的目录链接是按 GitHub 规则写的。"""
    value = value.strip().lower()
    value = re.sub(r"[^\w\s\u4e00-\u9fff\-]", "", value)
    value = re.sub(r"[\s_]+", separator, value)
    return value


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title} · 什么鸭 WhatDuck</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="什么鸭 WhatDuck">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="https://duck.whatled.com/learn/{slug}">
<meta name="theme-color" content="#f6f1e7">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="canonical" href="https://duck.whatled.com/learn/{slug}">
<style>
  :root{{
    --paper:#f6f1e7; --paper2:#efe7d6; --ink:#211a11; --ink-soft:#6b6151;
    --line:rgba(33,26,17,.16); --grid:rgba(33,26,17,.05);
    --orange:#e8590c; --orange-deep:#c64908; --yellow:#f0b429;
    --dark:#191309; --paper-on-dark:#f2ead9;
    --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
    --sans:"PingFang SC","Hiragino Sans GB","Source Han Sans SC","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
  }}
  *{{margin:0;padding:0;box-sizing:border-box}}
  html{{scroll-behavior:smooth}}
  body{{
    font-family:var(--sans); color:var(--ink); background-color:var(--paper);
    background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
    background-size:28px 28px; line-height:1.85; -webkit-font-smoothing:antialiased;
  }}
  ::selection{{background:var(--orange);color:var(--paper)}}
  .wrap{{max-width:900px;margin:0 auto;padding:0 24px}}
  .mono{{font-family:var(--mono)}}
  .topbar{{padding:22px 0;display:flex;align-items:center;justify-content:space-between;gap:16px}}
  .brand{{display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit}}
  .brand svg{{width:30px;height:30px;color:var(--orange)}}
  .brand b{{font-size:18px;letter-spacing:.02em}}
  .brand span{{font-family:var(--mono);font-size:11px;color:var(--ink-soft);letter-spacing:.14em;display:block;line-height:1.3}}
  .back-link{{font-family:var(--mono);font-size:12.5px;text-decoration:none;border:1.5px solid var(--ink);padding:7px 14px;border-radius:999px;background:var(--paper);transition:.18s;white-space:nowrap}}
  .back-link:hover{{background:var(--ink);color:var(--paper)}}
  .doc-head{{padding:34px 0 8px}}
  .kicker{{font-family:var(--mono);font-size:12px;letter-spacing:.22em;color:var(--orange-deep);text-transform:uppercase;display:flex;align-items:center;gap:12px}}
  .kicker::before{{content:"";width:34px;height:2px;background:var(--orange)}}
  .doc-head .meta{{font-family:var(--mono);font-size:12px;color:var(--ink-soft);margin-top:10px}}
  .doc-card{{
    background:rgba(255,255,255,.82); border:1.5px solid var(--line); border-radius:14px;
    padding:36px clamp(20px,5vw,52px) 44px; margin:22px 0 40px; box-shadow:8px 8px 0 rgba(33,26,17,.08);
  }}
  /* ---- markdown body ---- */
  .doc-body{{font-size:15.5px}}
  .doc-body h1{{font-size:clamp(26px,4.6vw,38px);line-height:1.3;font-weight:800;margin:6px 0 8px;letter-spacing:.01em}}
  .doc-body h2{{
    font-size:22px;font-weight:800;margin:44px 0 14px;padding-top:18px;border-top:1.5px solid var(--line);
    display:flex;align-items:baseline;gap:10px;
  }}
  .doc-body h2::before{{content:"§";font-family:var(--mono);font-size:15px;color:var(--orange-deep)}}
  .doc-body h3{{font-size:17.5px;font-weight:700;margin:28px 0 10px}}
  .doc-body h3::before{{content:"▸ ";color:var(--orange-deep)}}
  .doc-body h4{{font-size:15.5px;font-weight:700;margin:20px 0 8px}}
  .doc-body p{{margin:10px 0}}
  .doc-body strong{{font-weight:700}}
  .doc-body ul,.doc-body ol{{margin:10px 0 10px 1.4em}}
  .doc-body li{{margin:4px 0}}
  .doc-body li::marker{{color:var(--orange-deep)}}
  .doc-body a{{color:var(--orange-deep);text-decoration:none;border-bottom:1px dashed rgba(198,73,8,.5)}}
  .doc-body a:hover{{border-bottom-style:solid}}
  .doc-body hr{{border:none;border-top:1.5px dashed var(--line);margin:34px 0}}
  .doc-body blockquote{{
    margin:16px 0;padding:12px 18px;border-left:3px solid var(--orange);background:var(--paper2);
    border-radius:0 10px 10px 0;color:var(--ink-soft);font-size:14.5px;
  }}
  .doc-body blockquote p{{margin:6px 0}}
  .doc-body code{{
    font-family:var(--mono);font-size:.86em;background:var(--paper2);border:1px solid var(--line);
    border-radius:5px;padding:1px 6px;word-break:break-word;
  }}
  .doc-body pre{{
    background:var(--dark);color:var(--paper-on-dark);border-radius:10px;padding:16px 18px;
    overflow-x:auto;margin:14px 0;line-height:1.7;font-size:13px;
  }}
  .doc-body pre code{{background:none;border:none;padding:0;color:inherit;font-size:inherit;word-break:normal}}
  .doc-body table{{
    width:100%;border-collapse:collapse;margin:16px 0;font-size:13.5px;display:block;overflow-x:auto;
  }}
  .doc-body th,.doc-body td{{border:1px solid var(--line);padding:7px 11px;text-align:left;vertical-align:top}}
  .doc-body th{{background:var(--paper2);font-weight:700;white-space:nowrap}}
  .doc-body tr:nth-child(even) td{{background:rgba(255,255,255,.5)}}
  .doc-foot{{
    margin-top:44px;padding-top:18px;border-top:1.5px dashed var(--line);
    display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;
    font-family:var(--mono);font-size:12px;color:var(--ink-soft);
  }}
  .doc-foot a{{color:var(--orange-deep);text-decoration:none}}
  footer{{border-top:1.5px solid var(--line);background:var(--paper2)}}
  .foot-inner{{padding:20px 0 26px;font-family:var(--mono);font-size:11.5px;color:var(--ink-soft);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}}
  .foot-inner a{{color:var(--orange-deep);text-decoration:none}}
  @media (max-width:600px){{ .doc-card{{padding:26px 18px 32px}} }}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <g id="foot">
      <ellipse cx="12" cy="18.2" rx="3.4" ry="3.6"/>
      <ellipse cx="5.6" cy="9.4" rx="2.7" ry="5" transform="rotate(-30 5.6 9.4)"/>
      <ellipse cx="12" cy="7.2" rx="2.7" ry="5.4"/>
      <ellipse cx="18.4" cy="9.4" rx="2.7" ry="5" transform="rotate(30 18.4 9.4)"/>
    </g>
  </defs>
</svg>
<div class="wrap">
  <nav class="topbar">
    <a class="brand" href="/">
      <svg viewBox="0 0 24 28" fill="currentColor"><use href="#foot"/></svg>
      <span>什么鸭<br><b style="font-size:15px;color:var(--ink)">WHATDUCK</b></span>
    </a>
    <a class="back-link" href="/#learn">← 返回进度主页</a>
  </nav>
  <header class="doc-head">
    <p class="kicker">{tag} · LEARN NOTES</p>
    <p class="meta">收进学习手册 · {date} · duck.whatled.com</p>
  </header>
  <main class="doc-card doc-body">
{body}
    <div class="doc-foot">
      <span>什么鸭 WHATDUCK · 复刻学习笔记</span>
      <span><a href="/#learn">← 全部手册</a> · <a href="/">首页</a></span>
    </div>
  </main>
</div>
<footer>
  <div class="wrap foot-inner">
    <span>© 2026 WHATDUCK · 非官方个人学习与研究项目</span>
    <span><a href="https://github.com/fanhao375/microduck-replica" target="_blank" rel="noopener">github.com/fanhao375/microduck-replica</a></span>
  </div>
</footer>
</body>
</html>
"""

def rewrite_course_links(text: str) -> str:
    """课程目录内的相对 .md 链接 → 站内 /learn/course-*;映射不到的相对链接去掉链接只留文字,避免线上 404。"""

    def repl(m):
        name = m.group(1)
        if name == "README.md":
            return "](/learn/course)"
        if re.match(r"^\d\d-", name):
            return "](/learn/course-" + name[:2] + ")"
        return "](" + name + ")"

    text = re.sub(r"\]\(((?!http)[^)]+\.md)\)", repl, text)
    # 形如 docs/xxx.md、../yyy.md 的工作区相对链接:留文字去链接
    return re.sub(r"\]\(((?:\.\./|docs/|microduck-replica/|open-microduck/)[^)]+)\)", r"\1", text)


def rewrite_deep_links(text: str) -> str:
    """解读系列内的 NN-xxx.md 相对链接 → /learn/deep-NN;工作区路径留文字去链接。"""
    text = re.sub(r"\]\(\d\d-[^)]*\.md\)", lambda m: "](/learn/deep-" + m.group(0)[2:4] + ")", text)
    return re.sub(r"\]\(((?:\.\./|docs/|microduck-replica/|open-microduck/|bam/|xiaozhi-esp32/)[^)]+)\)", r"\1", text)


def stage_tag(n: int) -> str:
    if n <= 2:
        return "阶段 A · 认识它"
    if n <= 7:
        return "阶段 B · 软件与仿真"
    if n <= 12:
        return "阶段 C · 硬件入门"
    if n <= 17:
        return "阶段 D · 训练进阶"
    if n <= 22:
        return "阶段 E · 集成部署"
    return "阶段 F · 迁移与扩展"


def deep_stage_tag(n: int) -> str:
    if n <= 12:
        return "第一辑 · 运动控制核心"
    if n <= 20:
        return "第二辑 · 感知与系统服务"
    if n <= 32:
        return "第三辑 · 训练代码"
    if n <= 40:
        return "第四辑 · 结构"
    if n <= 50:
        return "第五辑 · 电路"
    return "第六辑 · 舵机与执行器"


# 课程正文按文件名自动发现(00/01 已在上面手工登记,这里跳过)
_seen = {d["out"] for d in DOCS}
for f in sorted(Path("/Volumes/dev/dev/microduck/docs/course").glob("[0-9][0-9]-*.md")):
    nn = f.name[:2]
    out = f"course-{nn}.html"
    if out in _seen:
        continue
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^# (.+)$", text, re.M)
    title = m.group(1).strip() if m else f.stem
    dm = re.search(r">\s*\*\*这一课解决什么问题\*\*[::](.+)", text)
    desc = re.sub(r"\*\*", "", dm.group(1)).strip()[:90] if dm else title
    DOCS.append(
        {
            "src": str(f),
            "out": out,
            "title": title,
            "desc": desc,
            "tag": f"LESSON {nn} · {stage_tag(int(nn))}",
            "date": "2026-09-11",
        }
    )

# 解读系列:总纲 hub + 60 篇文章,按文件名自动发现
DEEP_DIR = Path("/Volumes/dev/dev/microduck/docs/deep-dive")
DOCS.append(
    {
        "src": str(DEEP_DIR / "README.md"),
        "out": "deep.html",
        "title": "深读 Microduck · 代码 / 结构 / 电路 / 舵机 解读系列",
        "desc": "60 篇深度解读:逐文件拆解 duck-control 与 robotd 的 Rust 控制栈、mjlab 训练配置、机械结构反推、电路设计与舵机执行器,每篇都钉在真实源文件上。",
        "tag": "DEEP-DIVE · 解读系列",
        "date": "2026-09-11",
    }
)
for f in sorted(DEEP_DIR.glob("[0-9][0-9]-*.md")):
    nn = f.name[:2]
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^# 解读 \d\d · (.+)$", text, re.M)
    title = f"解读 {nn} · {m.group(1).strip()}" if m else f.stem
    dm = re.search(r">\s*\*\*解读对象\*\*[::](.+)", text)
    desc = re.sub(r"[`\*]", "", dm.group(1)).strip()[:90] if dm else title
    DOCS.append(
        {
            "src": str(f),
            "out": f"deep-{nn}.html",
            "title": title,
            "desc": desc,
            "tag": f"DEEP {nn} · {deep_stage_tag(int(nn))}",
            "date": "2026-09-11",
        }
    )

md = markdown.Markdown(
    extensions=["tables", "fenced_code", "toc", "sane_lists", "nl2br"],
    extension_configs={"toc": {"slugify": gh_slug, "separator": "-", "toc_depth": "2-4"}},
)

for doc in DOCS:
    text = Path(doc["src"]).read_text(encoding="utf-8")
    if "/course/" in doc["src"]:
        text = rewrite_course_links(text)
    elif "/deep-dive/" in doc["src"]:
        text = rewrite_deep_links(text)
    md.reset()
    body = md.convert(text)
    html = TEMPLATE.format(body=body, slug=doc["out"][:-5], **doc)
    (OUT / doc["out"]).write_text(html, encoding="utf-8")
    print(f"OK {doc['out']:>22}  {len(html):>7} bytes  headings-with-id: {len(md.toc_tokens)}")
