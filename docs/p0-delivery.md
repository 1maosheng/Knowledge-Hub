# P0 交付与验收报告

> 范围：可私有部署的 RAG 垂直切片 —— 上传 → 解析/分块 → 向量化 → 混合检索 → LangGraph 多轮问答 → 引用校验 → 评测。
> 图谱/多智能体完整形态在 P1–P2；本报告只覆盖 P0 已落地并有证据的部分。

## 1. 验收结果（本机实测，2026-11-18）

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 单元/接口测试 | `PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q -p asyncio` | **18 passed**（分块 4、引用 5、Agent 路由 4、API/SSE 5） |
| 静态检查 | `.venv/bin/ruff check app tests` | **All checks passed** |
| 50 题评测（Memory） | `python eval/run_eval.py --seed` | answer 1.0 / citation 1.0 / recall 1.0 / refusal 1.0 |
| 50 题评测（Milvus） | 同上，`VECTOR_BACKEND=milvus` | **50/50**，p50 25ms / p95 42ms，0 degraded |
| 向量持久化 | 写入后重启 API 再检索 | 仍命中（Milvus collection `lms_chunks`） |
| 异步解析 | `TASK_BACKEND=arq` + arq worker | 上传后 `pending/queued → ready/done`，worker 日志 1.07s 完成 |
| 前端 | `npm run build` + FastAPI 挂载 | 构建成功；`/kbs`、`/chat`、`/graph` 无头浏览器渲染出关键 DOM |
| 编排文件 | `docker-compose config -q` | 通过 |
| 容器镜像 | `docker-compose build api web` | 两个镜像均构建成功（web 用 `npm ci` 固定 lock，规避 icons-vue 解析问题） |
| 容器联调 | api 镜像 + web/Nginx 镜像接入同一网络 | `/` 200、`/api/health` 经 Nginx 代理正常、SSE 14 个事件无缓冲 |

> pymilvus **2.6.18** 客户端 ↔ Milvus **2.5.10** standalone 已实测兼容。

## 2. 实现要点

### 2.1 Agent 图（`backend/app/agents/qa_graph.py`）

`router → retrieve → assess → (retry | answer) → verify → END`

- 节点第二参数必须是 `RunnableConfig`，否则 LangGraph v1 不注入（SSE 的 `emit`、DB session 都从这里取）。
- `QAState` 必须声明 `sufficient` 通道：LangGraph 会静默丢弃未声明键，曾导致"已充分仍再检索一轮"。
- 每次检索结果用 `Annotated[list, add]` 累积，`assess` 内按 `chunk_id` 去重。
- 终止条件：`sufficient` 或 `round >= max_retrieval_rounds(2)`；两者都在 `assess` 返回 `round`，否则死循环。
- 充分性阈值来自 `settings.sufficiency_threshold`（默认 0.35），不再硬编码。
- SSE 事件：`start → route → retrieve → assess → token* → verify → citations → done`，异常 `error`、降级 `degrade`。

### 2.2 检索与引用

- dense（Milvus / Memory）+ 关键词（PG ILIKE 匹配正文与 section）+ RRF(k=60)；可选 rerank（0.5/0.5 归一混合）。
- 引用契约：模型回答的每个事实句以 `[n]` 结尾；`verify_answer` 检查越界、无引用断言、拒答例外。
- 降级：向量库失败 → 仅关键词；rerank 失败 → 跳过；LLM 流中断 → 保留前缀 + `degrade` 事件；无证据 → 明确拒答。

### 2.3 解析与分块

- 支持 pdf（pypdf 逐页）、docx（保序、标题识别、表格转行）、md、txt、xlsx。
- 结构感知分块：标题只进 `section`；表格按行切且重复表头；长文按句界 + overlap。
- 扫描件空页写入 `meta.warning`，P2 接 MinerU/OCR。

### 2.4 多租户与清理

- 所有查询带 `tenant_id`（`X-Tenant-Id` 或 `default`）；跨租户 404。
- 删除顺序：向量 → PG → 对象存储；KB 删除级联到文档。
- `Document` 记录 `status/stage/progress/error/chunk_count`，前端 2s 轮询。

## 3. 运行态（本机演示）

| 组件 | 地址 | 说明 |
| --- | --- | --- |
| API | http://127.0.0.1:8101 | `uvicorn app.main:app`，当前 `VECTOR_BACKEND=milvus` |
| Web（构建产物） | 同 API `/` | FastAPI 挂载 `web/dist` |
| Web（开发） | http://127.0.0.1:5173 | `npm run dev`，`/api` 代理 8101 |
| PostgreSQL | 127.0.0.1:5432 | `lms/lms`，库 `lms`、`lms_test` |
| Redis | 127.0.0.1:6381 | arq 队列 |
| MinIO | 127.0.0.1:9000 | `minioadmin/minioadmin`，bucket `lms-docs` |
| Milvus | 127.0.0.1:19530 | 2.5.10 standalone，collection `lms_chunks` |
| Neo4j | 127.0.0.1:7687 / 7474 | 已随 compose 定义，P0 未接主链路 |

演示数据：`milvus-smoke`（1 篇）、`评测知识库-1794990796`（4 篇语料）。

## 4. 待接入（需要外部输入）

1. **内网 vLLM**：`LLM_BASE_URL` / `LLM_MODEL`，以及 embedding（`EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM`，bge-m3 为 1024）。拿到后重跑 50 题，替换 `eval/report-milvus.json` 作为真实基线。
2. 可选 rerank 服务（TEI `/rerank`），用于开启 hybrid 重排。
3. P1 图谱：LightRAG 抽取 → 实体对齐 → Neo4j（唯一图存储）→ 模板化 Cypher；`qa_graph.route.need_graph` 已预留。

## 5. 已知限制

- Docker 镜像在受限网络下需镜像站（如 `docker.m.daocloud.io`）预拉取；`docker-compose build` 需要可写的 `DOCKER_CONFIG`。
- Neo4j Community 无细粒度 RBAC；P0 仅按 `tenant_id` 属性隔离。
- Mock 向量库为进程内存储，重启丢失（Milvus 模式已解决）。
- 前端未做浏览器自动化，只做了构建 + 无头渲染冒烟。