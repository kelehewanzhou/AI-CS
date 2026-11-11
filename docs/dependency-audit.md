# 依赖审计记录

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
