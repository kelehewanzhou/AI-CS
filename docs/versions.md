# 工程版本记录

记录日期：2026-11-08（Asia/Shanghai）

## 本机工具

| 工具 | 记录值 | 获取方式/状态 |
| --- | --- | --- |
| Python | 3.13.9 | `python --version` |
| pip-tools | 7.6.2 | `python -m pip install pip-tools==7.6.2` |
| Node.js | v24.22.1 | `node --version` |
| pnpm | 10.34.9 | Corepack，`corepack install --global pnpm@10.34.9` |
| Docker Engine | 未安装或不在 PATH | `docker --version` 未通过 |
| Docker Compose | 未安装或不在 PATH | `docker compose version` 未通过 |

## 项目锁定

| 项目 | 锁定值 |
| --- | --- |
| Python 顶层依赖 | `backend/requirements.in`，按任务0指定版本 |
| Python 锁文件 | `backend/requirements.lock`，由 pip-tools 7.6.2 生成并带 SHA256 哈希 |
| Node.js 包管理器 | `pnpm@10.34.9` |
| Node.js 锁文件 | `web/pnpm-lock.yaml`，由 pnpm 10.34.9 生成 |
| PostgreSQL | `postgres:17`，manifest digest 见 [镜像清单](images.md) |
| 锁文件生成日期 | 2026-11-08 |

## 验证限制

当前工作站缺少 Docker CLI，因此 PostgreSQL 容器启动、healthcheck 和本机 `psql` 连接尚未执行。镜像 digest 已从 Docker Registry manifest 读取并记录；安装 Docker Desktop 后应重新执行任务0的容器验收命令，并将结果补入本文件。

## 任务一实现记录

2026-11-09 完成公共设施和数据库迁移：

- `backend/common/` 提供 Pydantic Settings、同步 SQLAlchemy、请求级 `request_id` 和统一错误处理。
- `database/migrations/versions/0001_initial_schema.py` 创建任务一正文定义的 11 张 P0 业务表及约束、外键和索引。
- `GET /health/live`、`GET /health/ready` 和统一 404/422 错误响应已加入后端。
- `backend/tests/` 的公共设施契约测试通过；真实 PostgreSQL 迁移仍需在 Docker 可用的环境中执行。
