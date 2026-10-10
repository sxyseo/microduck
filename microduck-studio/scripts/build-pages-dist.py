"""Assemble pages-dist/ for static hosting (Cloudflare Pages, or any static file server).

Frontend only: the API, SQLite database, serial ports, SSH and training stay with the local
service. The output maps web/index.html to the site root and keeps /assets/... paths working;
the Color Studio build (3D iframe + guide model) is included wholesale when present.

Usage: uv run python scripts/build-pages-dist.py
Deploy: npx wrangler login && npx wrangler pages deploy
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "pages-dist"


def main() -> int:
    web = ROOT / "web"
    color = ROOT / "microduck-color-studio" / "dist"
    if not (web / "index.html").is_file():
        print("缺少 web/index.html", file=sys.stderr)
        return 1
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copy2(web / "index.html", DIST / "index.html")
    shutil.copytree(web, DIST / "assets", ignore=shutil.ignore_patterns("index.html"))
    if (color / "index.html").is_file():
        shutil.copytree(color, DIST / "color-studio")
        included_color = True
    else:
        included_color = False
        print("注意:未找到 microduck-color-studio/dist,3D 视图与安装教程模型将在 Pages 上不可用。")
    files = sum(1 for _ in DIST.rglob("*") if _.is_file())
    size = sum(_.stat().st_size for _ in DIST.rglob("*") if _.is_file())
    print(f"pages-dist 就绪:{files} 个文件,共 {size / 1_048_592:.1f} MiB;3D 模型包含:{included_color}")
    print("下一步:")
    print("  1) npx wrangler login")
    print("  2) npx wrangler pages deploy   # 首次会创建 Pages 项目")
    print("  3) 在运行本机服务时设置 MICRODUCK_STUDIO_ALLOWED_ORIGINS 为 Pages 地址(逗号分隔),")
    print("     例如 MICRODUCK_STUDIO_ALLOWED_ORIGINS=https://microduck-studio.pages.dev uv run python -m microduck_studio")
    print("  4) 打开 Pages 地址,在『项目与设置 → 云端与本机』核对服务检测状态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
