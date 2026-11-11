# 正式种子候选包

本目录提供与既有导入器一致的四文件 schema_version=1 候选包，包含4门课程、5个节点、3条关系、5道题。它是结构夹具的审阅起点，尚未形成正式教学内容。全部关系均标记为“待补充”，不将夹具中的书目、页码和“已核验”状态冒充真实证据。问答17条验收基线仍使用 fixtures/，两者目的不同。

教学专家需逐条核对课程书目、节点范围与摘要、关系方向/机制/等级/边界、教材版本和页码、题干/选项/答案及关联节点。只有核验完整书目、版本、章节、页码后才可将对应关系改为“已核验”。按实际范围补齐所需教学内容。

在安装后端依赖的环境计算待确认包的规范化 checksum：

```bash
cd backend
python -c "from pathlib import Path; from cli.release_seed import verify_package; print(verify_package(Path('../seeds'), production=False).checksum)"
```

审核完成后，在 approval.json 填写真实 reviewer、reviewed_at（YYYY-MM-DD）、checksum，status 改为 approved，并留存项目签字记录。修改任何实质内容均需重新确认 checksum。生产 ENVIRONMENT=production 的 seed-import 会核对上述字段，未确认或校验失败即退出非零，后端不会开放。

正式部署将 .env 中 SEED_DIR 改为 ./seeds。fixtures/ 仅用于 development 验收，不能作为正式已确认教学数据。
