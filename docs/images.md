# 容器镜像清单

记录日期：2026-11-08（Asia/Shanghai）

以下 digest 是 2026-11-08 从 Docker Registry 对相应 tag 的 manifest 查询结果。当前工作站未安装 Docker CLI，尚未执行 `docker inspect` 或本地 pull；部署前应在目标环境重新校验 digest。

## PostgreSQL

- 镜像：`postgres:17`
- Digest：`sha256:ff87138949ad9a46f32ff23bd6852b52ce024a13dffe9b4087be98292cdd3b4f`
- 查询时间：2026-11-08

## Python 基础镜像（后续任务使用）

- 镜像：`python:3.13-slim`
- Digest：`sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90`
- 查询时间：2026-11-08

## Node.js 基础镜像（后续任务使用）

- 镜像：`node:24-alpine`
- Digest：`sha256:a34ab6d7f6f4813f4d0c5469d74685604b962fbdbf5793a7bc7b4998ecb867c8`
- 查询时间：2026-11-08

## 任务九 Nginx

- 镜像：`nginx:1.30.6`
- Digest：`sha256:42c68eab6f7e22611786a9fe1d1c019e275c50185bd54b8f75dc2b9184322703`
- 查询时间：2026-11-10，Docker Registry library/nginx manifest接口
- 原生Nginx配置与代理验收使用官方Windows 1.30.6包；Docker镜像尚未实际构建/运行。完整清单及验收状态见[版本清单](版本清单.md)。
