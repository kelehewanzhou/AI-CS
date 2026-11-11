# 构建检查清单

## 构建前

- [ ] `pnpm install --frozen-lockfile`
- [ ] TypeScript类型检查通过：`pnpm tsc --noEmit`
- [ ] 环境变量正确：同源部署使用默认 `/api/v1`；开发直连FastAPI时设置 `NEXT_PUBLIC_API_URL=http://localhost:8000`

## 构建

- [ ] `pnpm build`成功
- [ ] 无Server Actions或Route Handlers警告
- [ ] `out/`目录生成
- [ ] `out/`目录大小合理
- [ ] `out/login/index.html`、`out/graph/index.html`、`out/node/index.html`、`out/edge/index.html`、`out/exercise/index.html`、`out/learning/index.html`、`out/teacher/acceptance/index.html`存在

## 部署前验证

- [ ] 本地预览：`pnpm serve out/`，或使用Nginx/静态文件服务器提供 `out/`
- [ ] 全部固定页面可访问，直接刷新带查询参数的页面正常
- [ ] API请求统一通过 `/api/v1`，由Nginx代理到FastAPI业务路由
- [ ] `credentials: include`已启用，Cookie正常工作
- [ ] POST请求由浏览器发送允许的Origin，服务端完成Origin校验

## 任务八问答面板

- [ ] `/graph/` 显示知识问答面板，空白问题禁用提交，输入最多500字符
- [ ] “什么是TLB”显示“已回答”，正文保留换行，引用 CO03/OS02、E001 可跳转
- [ ] “量子纠缠是什么”显示“暂未覆盖”和中文原因
- [ ] “页表是什么”显示“证据不足”和证据缺口，不展示肯定回答引用
- [ ] 查询期间按钮禁用，前一次结果清除，查询结束后恢复
- [ ] 422/500/503显示错误信息和请求编号，不当成业务答案
- [ ] 问答失败后，图谱查询和节点详情仍可使用
- [ ] 小屏幕下输入区、提交按钮、状态和引用正常换行
- [ ] Network 中同源请求为 `POST /api/v1/ask`，开发直连请求为 `POST http://localhost:8000/ask`；请求体只有 `question`
