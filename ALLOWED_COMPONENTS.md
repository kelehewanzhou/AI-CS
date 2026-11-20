# 已有组件允许使用清单

复核日期：2026-11-20（Asia/Shanghai）。适用范围为当前 MVP 的已有组件，采用方式为安装包调用，不复制上游业务实现。备选不在此清单内。正式学校部署另需完成容器、内容和网络验收。

完整来源、版本、能核实的 commit、许可副本 SHA256 见 [组件机器清单](third_party/components.json)；原始查询见 [官方元数据](docs/验收证据/opensource-20261120/official-metadata.json)。间接依赖以 lock 为准；此清单不是完整镜像 SBOM。

机器清单的文本校验值统一 CRLF 为 LF，兼容 Git 在 Windows/Linux 的换行转换；官方元数据中的原始许可校验值保留采集时的字节结果。

发布配置会把许可副本和组件清单复制到后端镜像 /app/third_party，以及前端静态站点 /third-party-licenses/。本轮只检查复制声明和来源文件，镜像实际构建/内容验收仍待Docker目标机完成；分发前须补齐镜像内其他系统包与原生捆绑库的许可。

| 模块 | 项目/实际使用版本 | 许可证 | 实际用途、采用理由与替换位置 |
|---|---|---|---|
| 前端 | [Next.js](https://github.com/vercel/next.js) 16.4.5；[React/React DOM](https://github.com/facebook/react) 19.2.9 | MIT | 静态页面与交互，已有完整路径；替换影响 web/app 和组件，成本高 |
| 图谱 | [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) 3.34.4 | MIT | 小图、点击、方向/对称关系；入口 web/components/GraphVisualization.tsx，替换不迁移知识库 |
| 提交ID | [uuid](https://github.com/uuidjs/uuid) 11.1.1 | MIT | 答题重试幂等键；更换生成函数仍须保留服务端幂等规则 |
| API | [FastAPI](https://github.com/fastapi/fastapi) 0.162.0；[Uvicorn](https://github.com/Kludex/uvicorn) 0.54.0 | MIT；BSD-3-Clause | 路由/HTTP 服务；替换影响 API 层，业务规则留在 service |
| 导入/配置 | [Pydantic](https://github.com/pydantic/pydantic) 2.14.2；[pydantic-settings](https://github.com/pydantic/pydantic-settings) 2.10.1 | MIT | 严格字段校验与配置；跨文件引用规则保留 seed_import/validator.py，替换成本中高 |
| 数据访问 | [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) 2.0.57；[Alembic](https://github.com/sqlalchemy/alembic) 1.20.1 | MIT | 模型/事务/迁移，边界为各模块 repository 和 database/migrations；替换成本高 |
| PostgreSQL驱动 | [psycopg](https://github.com/psycopg/psycopg) 3.3.7，binary 3.3.7 | LGPL-3.0-only | 使用独立可替换安装包，不改驱动源码；保留许可、对应源码获取方式与重新安装能力。分发二进制包/镜像时须一并满足 LGPL 及捆绑原生库条款，镜像尚未验收 |
| 密码 | [argon2-cffi](https://github.com/hynek/argon2-cffi) 25.1.0 | MIT | 成熟 Argon2id 实现；AuthService 定义会话/权限。替换须兼容已有哈希，不直接重置密码 |
| 类型/构建 | [TypeScript](https://github.com/microsoft/TypeScript) 5.9.3；[React/Node类型](https://github.com/DefinitelyTyped/DefinitelyTyped) 19.3.0/24.19.2；[pnpm](https://github.com/pnpm/pnpm) 10.34.9 | Apache-2.0；MIT | 开发工具，包版本已固定，升级需重做类型/构建和浏览器验收 |
| 回归 | [pytest](https://github.com/pytest-dev/pytest) 9.2.0；[HTTPX](https://github.com/encode/httpx) 0.28.1 | MIT；BSD-3-Clause | 测试专用；当前 TestClient 有弃用告警，升级另行验证 |
| 浏览器验收 | [Playwright Python](https://github.com/microsoft/playwright-python) 1.56.0 | Apache-2.0 | 测试专用；保留 driver NOTICE，不随业务前端发布；浏览器分发条款另按所用浏览器检查 |
| 编排 | [Docker Compose](https://github.com/docker/compose) 2.40.3 | Apache-2.0 | 仅配置解析历史验证，当前无 CLI/daemon，不授予“已部署通过”状态；禁止据此替换部署方式 |

## 本地结果、风险和数据流

验收测试及结果见 [逐步验收结果](docs/开源复核/03-逐步验收结果.md)。Python 生产锁及前端依赖本次扫描无已知漏洞，结论仅限扫描源/时间/覆盖范围。开发测试依赖未做完整安全扫描，上游完整测试套件未运行；不声明“保证安全”。固定版本可复现，但不保证长期兼容。

运行时：浏览器默认请求同源 /api/v1，Nginx 转发后端，后端连接配置的 PostgreSQL；模板问答不调用 LLM。NEXT_PUBLIC_API_URL 是可配置出口，学校部署应保持同源或逐项确认目标。浏览器验收检查本次应用发出的 HTTP 请求；不能覆盖操作系统、浏览器自身及任意第三方包所有代码路径。

安装/构建/审计：npm registry、PyPI、GitHub、Docker Registry、漏洞数据库可能联网；pip-audit/pnpm audit 会提交依赖名称和版本进行查询，不提交教学正文。Playwright 安装浏览器可能额外下载资源；本机用已安装 Edge，CI 使用 Chromium。Next 构建遥测按 [官方说明](https://nextjs.org/telemetry) 以 NEXT_TELEMETRY_DISABLED=1 关闭，Dockerfile 已设置，本地构建命令也应设置。

基础设施：本次原生工具为 PostgreSQL 17.11、Nginx 1.30.6、Python 3.13.9、Node 24.22.1；Compose/Dockerfile 基础镜像以 sha256 digest 固定，见现有 images.md/versions 记录。原生结果不等于镜像结果；镜像及其所有系统包的漏洞/许可、学校 TLS/网关和 Docker Desktop 产品条款仍须在目标环境核查。

## 启动、升级、回滚、移除

1. 生产依赖安装：`python -m pip install --require-hashes -r backend/requirements.lock`；`cd web` 后 `corepack pnpm install --frozen-lockfile`。本机 corepack 可调用 pnpm，无需重装全局包管理器。生产启动/迁移/账号命令沿用 README 和部署指南，不能跳过正式内容审核。
2. 本轮原生验收复现命令及隔离测试环境见结果报告。检查清单：`python scripts/verify_components.py`。许可证原文见 third_party/licenses；MIT/BSD 署名不删，Apache NOTICE 适用部分保留。psycopg 对应源码可由 [官方版本源码包](https://pypi.org/pypi/psycopg/3.3.7/json) 的 sdist 获取，binary 构建与捆绑库见 [官方安装说明](https://www.psycopg.org/psycopg3/docs/basic/install.html)。
3. 升级：先候选比较/变更记录，更新直接版本和 lock，重新漏洞扫描、许可归档、清单检查及真实路径测试。新增架构/数据模型依赖需单独评估，不能因本清单自动获得授权。
4. 回滚：保留上一套 package.json、两个 lock、镜像 digest 与匹配清单，按运维手册停写/备份/发布；数据库不自动降级，涉及数据变更先按备份恢复演练。使用已有未提交修改时不可用 git reset 覆盖他人工作。
5. 移除：先消除上述调用入口和相关测试使用，卸载包并重建 lock/许可清单，再跑闭环；数据访问、哈希、迁移和部署工具更换须单独列迁移计划。没有独立第三方知识数据格式需要迁出。
