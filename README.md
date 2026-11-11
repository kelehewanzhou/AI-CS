# AI跨课程知识图谱学习系统

本仓库已实现任务九的部署代码：在原有认证、图谱、习题、学习状态和模板问答基础上，补齐五服务 Compose、Nginx、维护发布、最小数据库权限、备份恢复与验收工具。生产教学内容确认、目标机容器启动、生产TLS与最终签字仍须按验收报告完成。

系统面向学生与教师，后续 MVP 将支持浏览跨课程知识节点与关系、查看证据、完成练习并保存个人学习记录。当前知识图谱、关系、证据和学习规则仍按架构评审与教学专家确认流程推进；测试夹具不代表正式已核验教学内容。

技术方向为 Next.js/React/Cytoscape.js 前端、FastAPI 后端、PostgreSQL 数据库和 Docker Compose 本地环境。默认开发分支为 `dev`，架构、字段、接口和业务规则以 `docs/` 中的修订版设计文档及对应任务 SOP 为准。

## 环境要求

- Python 3.13+
- Node.js 24 LTS
- pnpm 10.34.9
- Docker Engine + Compose v2
- PostgreSQL 17（由 Docker Compose 提供）

## 任务九快速部署

在安装 Docker Engine、Compose v2 和 Python 3.13 的机器上运行；配置与种子预检还需安装已锁定的后端依赖。以下默认仅用于本地开发验收：

```bash
python -m pip install --require-hashes -r backend/requirements.lock
python scripts/manage.py init-env
python scripts/manage.py deploy v1.0.0
python scripts/manage.py status
python scripts/manage.py create-account student01 student
python scripts/manage.py create-account teacher01 teacher
```

访问 `http://localhost:8080/login/`。临时账号密码在受保护且不入库的 `credentials/` 目录，首次改密后重新登录。已有 `.env` 不会被覆盖。首次启动也可先 `python scripts/manage.py build v1.0.0` 再 `docker compose up -d`；已有数据的更新统一使用 deploy，不能跳过停写备份。

前端统一请求 `/api/v1/*`，Nginx移除 `/api/v1` 后转发到既有后端路由；健康检查同时支持 `/health/*` 和 `/api/v1/health/*`。三个常驻服务为 postgres、backend、nginx，migrate 与 seed-import 成功退出属于正常状态。数据库及8000端口不映射至宿主机。

完整步骤与限制见 [部署指南](docs/部署指南.md)、[运维手册](docs/运维手册.md)、[备份恢复手册](docs/备份恢复手册.md) 和 [AT-01至AT-09验收报告](docs/AT-01至AT-09验收报告.md)。正式部署须切换 production、HTTPS外部Origin、已由教学专家确认的 seeds/；不得把 fixtures/ 当作正式内容。

## 初始化

PowerShell、macOS/Linux shell 均可按下面步骤执行；Windows PowerShell 将 `cp` 替换为 `Copy-Item`。

```bash
# 1. 复制环境配置并修改密码和密钥
cp .env.example .env

# 2. 安装 Python 依赖
cd backend
python -m pip install -r requirements.lock

# 3. 安装 Node.js 依赖
cd ../web
pnpm install --frozen-lockfile

# 4. 启动 PostgreSQL
cd ..
docker compose up postgres -d

# 5. 查看健康状态
docker compose ps
```

PowerShell 示例：

```powershell
Copy-Item .env.example .env
```

## 基线与任务一验证

### 依赖和构建

```bash
python --version
node --version
pnpm --version

cd backend
python -c "import fastapi, pydantic, pydantic_settings, sqlalchemy, psycopg, uvicorn, alembic, argon2; print('Python imports: OK')"

cd ../web
pnpm install --frozen-lockfile
pnpm build
```

### 数据库连接和任务一迁移

```bash
docker compose up postgres -d
docker compose ps

cd backend
alembic upgrade head
```

容器启动依赖 `.env` 中的 `DB_PASSWORD`。迁移成功后数据库包含任务一正文定义的 11 张表。

### 结构夹具

四个夹具位于 `fixtures/`，可用 Python 标准库验证 JSON 格式和数量：

```bash
python -c "import json, pathlib; p=pathlib.Path('fixtures'); data={f.stem:json.loads(f.read_text(encoding='utf-8')) for f in p.glob('*.json')}; assert all(v['schema_version']==1 for v in data.values()); assert len(data['courses']['items'])==4; assert len(data['nodes']['items'])==5; assert len(data['edges']['items'])==3; assert len(data['exercises']['items'])==5; print('Fixtures: OK')"
```

夹具是结构测试数据，不能视为已经完成教学专家确认的正式内容。

## 目录

```text
backend/              FastAPI 后端、公共设施和 Python 锁文件
web/                  Next.js 静态导出前端、固定页面和前端依赖锁文件
database/             Alembic 迁移目录和任务一初始迁移
fixtures/             §4.6 四个结构测试夹具
docs/                 架构、SOP、版本和镜像记录
docker-compose.yml
.env.example
```

后续任务按 `docs/开发任务SOP/README.md` 的顺序实现。启动、迁移、导入、接口和测试命令见 [运行指南](docs/运行指南.md)。任务八从图谱页的“知识问答”面板进入，接口及验收步骤见 [AT-07 问答基线验收](docs/AT-07_问答基线验收.md)。

## 常见问题

- **5432 端口冲突**：停止占用端口的本地 PostgreSQL，或在本地开发配置中调整端口映射后重新执行 Compose。
- **依赖下载失败**：检查 PyPI/npm 源、代理和网络连接；安装时坚持使用 `requirements.lock` 与 `pnpm-lock.yaml`。
- **权限问题**：确认当前用户有 Docker Desktop 权限，并避免把 `.env`、密码、密钥或私有证书提交到仓库。
- **冻结安装失败**：确认 `package.json` 与 `pnpm-lock.yaml` 来自同一版本；使用 `pnpm@10.34.9` 重新生成锁文件。

## 记录

- [版本记录](docs/versions.md)
- [镜像清单](docs/images.md)
- [依赖审计](docs/dependency-audit.md)
