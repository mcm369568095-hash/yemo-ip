#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包排除表（作者发版用，不进买家包）。

本技能是「模式 A 服务端代出」：买家装到的只有付费客户端。
服务端生产代码（身份分析 + 生图网关调用）部署在作者服务端，
位于 scripts/server/，绝不进包。
"""
import os
import shutil

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXCLUDE_FILES = {
    "scripts/server",                 # 服务端代出模块，部署到作者服务端
    "dist",                           # 打包产物自身
    "ARCHITECTURE.md",                # 作者内部架构文档（含生图渠道等），不随技能发布
    ".ip_payment_state.json",         # 本地付款状态
    "LOCAL_DEV.md",                  # 作者本地开发手册
    ".git", "__pycache__", "node_modules",
}


def should_exclude(rel):
    parts = rel.split(os.sep)
    for ex in EXCLUDE_FILES:
        ex_parts = ex.split("/")
        if parts[: len(ex_parts)] == ex_parts:
            return True
    return False


def build(dist_dir):
    out = os.path.join(SKILL_DIR, dist_dir)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    count = 0
    for root, dirs, files in os.walk(SKILL_DIR):
        rel_root = os.path.relpath(root, SKILL_DIR)
        if should_exclude(rel_root):
            continue
        for f in files:
            rel = os.path.join(rel_root, f) if rel_root != "." else f
            if should_exclude(rel):
                continue
            dst = os.path.join(out, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(root, f), dst)
            count += 1
    print(f"✓ 打包完成：{out}（{count} 个文件）")
    print("  进包：SKILL.md / references/* / scripts/pay_generate.py / scripts/package_skill.py")
    print("  排除：ARCHITECTURE.md / scripts/server/ / dist / 本地状态文件")


if __name__ == "__main__":
    build("dist")
