# 依赖审计记录

## 2026-11-20 当前复核

本次 `python -m pip_audit -r backend/requirements.lock --format json` 检查28项生产Python依赖，`corepack pnpm audit --json` 检查62项前端依赖，均未发现已知漏洞。[Python结果](验收证据/opensource-20261120/python-audit.json)、[前端结果](验收证据/opensource-20261120/node-audit.json)。不涵盖完整开发工具、操作系统和容器镜像，不是安全保证。许可、数据去向和替换点见[允许清单](../ALLOWED_COMPONENTS.md)，完整过程见[逐步复核](开源复核/03-逐步验收结果.md)。以下保留2026-11-08历史记录。

记录日期：2026-11-08（Asia/Shanghai）

## Python

命令：

```bash
pip-audit -r backend/requirements.lock
```

结果：通过。`pip-audit 2.10.1 -r backend/requirements.lock` 返回 `No known vulnerabilities found`。

安装备注：本机全局 Anaconda 环境另有 `anaconda-cli-base 0.6.0`，它要求 `click<8.2`；任务锁文件要求 `click==8.5.1`。锁文件安装本身成功，后续开发应使用项目虚拟环境，避免全局环境的无关依赖冲突。

## Node.js

命令：

```bash
cd web
pnpm audit
```

结果：通过。`pnpm@10.34.9 audit --json` 返回 61 个依赖、0 个 info/low/moderate/high/critical 漏洞，actions 为空。
