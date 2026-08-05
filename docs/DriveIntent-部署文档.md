# DriveIntent 部署文档

**版本**：V1.4.4　**更新日期**：2026-08-05　**服务默认端口**：8000

本文档描述如何在一台**全新服务器**上从零启动 DriveIntent。提供两种方式：

- **方式一：Docker Compose 一键部署（推荐）** —— 自带 MySQL，无需在宿主机安装 Python 与数据库；
- **方式二：裸机部署** —— 直接用系统 Python 运行，需自行准备 MySQL。

服务是一个 FastAPI 单体应用，启动时自动建表、拉起两个后台 Worker（业务 Worker 与 API Worker），并对外提供 Web 页面与 V1 HTTP API。

---

## 1. 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux / Windows Server 均可（示例以 Linux 为主） |
| CPU / 内存 | 2 核 4G 起步；LLM 分析为 I/O 密集型，按并发量调整 |
| 磁盘 | 10G 以上（含 MySQL 数据卷与镜像）。**V1.4.4 起另需为截图暂存区预留空间**：峰值约「待处理作业数 × 单作业截图体积」，实测单作业平均 13MB，队列深度 500 时约 7G，建议总可用空间 ≥ 20G |
| 网络 | 若使用真实 LLM，需能访问 `LLM_BASE_URL` 指向的服务 |

**方式一额外要求**：Docker 20.10+ 与 Docker Compose v2（`docker compose` 命令）。

**方式二额外要求**：Python 3.11、MySQL 8.0、`pip`。

---

## 2. 获取代码

```bash
git clone <仓库地址> DriveIntent
cd DriveIntent
```

如无 git，可将项目目录整体拷贝到服务器。**必须包含 `app/`、`requirements.txt`、`Dockerfile`、`docker-compose.yml`、`.env.example`。**

---

## 3. 配置环境变量

两种方式都以 `.env` 文件驱动。复制模板后按需填写：

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

`.env` 完整配置项说明：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_PORT` | `8000` | 服务对外端口。**仅 Docker Compose 部署生效**（映射宿主机端口）；裸机部署由 `uvicorn --port` 参数指定 |
| `DB_HOST` | `127.0.0.1` | 数据库地址。**Compose 方式由 compose 覆盖为 `mysql`，无需改动** |
| `DB_PORT` | `3306` | 数据库端口 |
| `DB_USER` | `root` | 数据库用户 |
| `DB_PASSWORD` | `driveintent` | 数据库密码，**生产务必修改** |
| `DB_NAME` | `driveintent` | 数据库名，启动时若不存在需已由 DB 创建（Compose 自动创建） |
| `DB_POOL_SIZE` | `15` | 数据库连接池常驻连接数 |
| `DB_MAX_OVERFLOW` | `15` | 连接池溢出上限；并发连接上限 = `DB_POOL_SIZE + DB_MAX_OVERFLOW`，需覆盖两类 Worker 并发与 Web 请求峰值 |
| `DB_POOL_TIMEOUT` | `30` | 等待可用连接的超时（秒），超时报 `QueuePool limit reached` |
| `LLM_PROVIDER` | `mock` | `mock`（本地假数据，联调用）或 `openai_compat`（真实模型） |
| `LLM_BASE_URL` | 空 | OpenAI 兼容接口地址，**须含 `/v1` 前缀**，如 `https://api.example.com/v1` |
| `LLM_API_KEY` | 空 | 模型服务的 API Key |
| `LLM_MODEL` | `mock-model` | **文本模型**名；不使用多模态能力的节点（视频语境/评论初筛/用户分析）默认使用 |
| `LLM_MULTIMODAL_MODEL` | 空 | **V1.4.1** 多模态模型名；主页截图识别等需图像输入的节点默认使用，**留空则回退到 `LLM_MODEL`**。与文本模型共用 `LLM_BASE_URL` / `LLM_API_KEY`，仅模型名不同 |
| `LLM_ENABLE_THINKING` | `false` | **V1.4.1** 深度思考全局开关；`true` 时对 `openai_compat` 请求注入 `enable_thinking=true`。该字段为 Qwen/DashScope 等端点扩展项，严格校验未知参数的端点可能拒绝，默认 `false` 为安全路径 |
| `LLM_TIMEOUT_SECONDS` | `120` | 单次 LLM 调用超时（秒） |
| `LLM_MAX_RETRIES` | `3` | LLM 调用失败重试次数 |
| `API_KEYS` | `change-me-key1,change-me-key2` | **对外 API 的访问密钥**，逗号分隔多个，**生产务必修改** |
| `API_WORKER_ENABLED` | `true` | 是否启用 API 任务 Worker（关闭则 API 任务不执行） |
| `API_WORKER_CONCURRENCY` | `3` | API Worker 并发数 |
| `WORKER_ENABLED` | `true` | 是否启用业务 Worker（Web 端导入分析用） |
| `WORKER_CONCURRENCY` | `3` | 业务 Worker 并发数 |
| `WORKER_POLL_INTERVAL` | `1.0` | Worker 轮询任务间隔（秒） |
| `COMMENT_BATCH_SIZE` | `30` | 评论批处理条数 |
| `OUR_MODELS_CONFIG_PATH` | `config/our_models.json` | **V1.1** 我方在售车型配置文件路径（生成方式见 3.2 节） |
| `SCREENSHOT_STAGING_DIR` | `data/staging` | **V1.4.4** 截图暂存目录。base64 截图不入库，提交后暂存于此、worker 认领时读回识图、作业终态删除。**须为持久化目录**（Compose 已挂载 `./data:/app/data`），详见第 9 节 |
| `INTENT_DOWNGRADE_ENABLED` | `true` | **V1.1** 非我方车型意向降级总开关；`false` 完全跳过匹配与降级（快速回退用） |

**上线前至少修改三项**：`DB_PASSWORD`、`API_KEYS`、以及真实模型的 `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。

> 首次部署可先保持 `LLM_PROVIDER=mock` 跑通全链路，再切换到 `openai_compat` 联调真实模型。

### 3.1 生成 API Key

`API_KEYS` 中的密钥用 `scripts/generate_api_key.py` 生成（32 字节加密级随机熵，仅依赖 Python 标准库，无需安装项目依赖）：

```bash
# 生成 1 个 key，仅打印到终端（手动粘贴进 .env）
python scripts/generate_api_key.py

# 生成 2 个 key 并自动写入 .env 的 API_KEYS（追加；模板占位 key 自动剔除）
python scripts/generate_api_key.py -n 2 --write

# 替换 .env 中原有全部 key（如需轮换密钥）
python scripts/generate_api_key.py --write --replace
```

写入后**重启服务生效**（Compose：`docker compose up -d` 会重建 app 容器读取新变量；裸机：重启 uvicorn 进程）。生成的 key 需通过安全渠道分发给 API 调用方，格式形如 `di_xxxxxxxx...`。

### 3.2 生成我方车型配置（V1.1）

V1.1 的两项能力依赖"我方在售车型"配置：Agent 1 对非我方车型视频下的评论做**意向降级**，Agent 2 评级时**考量品牌匹配度**。配置文件默认为 `config/our_models.json`（**不入库**，每套部署自行生成；结构模板见 `config/our_models.example.json`）。

**未配置时服务正常运行**：启动仅记录一条警告日志，降级与匹配度考量自动跳过，API 字段契约不变（不会产生 `filter_type="model_mismatch"` 分类）。

#### 生成步骤

用转换脚本把自由文本的车型描述（车型介绍、配置单等）交给 LLM 抽取为结构化配置。脚本复用 `.env` 中的 LLM 配置，**需 `LLM_PROVIDER=openai_compat` 与可用的模型服务**，在装有项目依赖的机器上运行（服务器或本地开发机均可）：

```bash
# 1. 准备车型描述文本（一款或多款均可）
#    示例内容："方舟X7，中大型插混SUV，售价28.98-35.98万，主打家用越野兼顾……"

# 2. 预览抽取结果（只打印不写盘，人工核对结构与价格）
python scripts/build_our_models.py --input 车型描述.txt --dry-run

# 3. 确认无误后写入（默认 config/our_models.json，可用 --output 指定）
python scripts/build_our_models.py --input 车型描述.txt
```

脚本行为与注意事项：

- 输出经 Pydantic 校验，抽取/校验失败会**报错退出、不写坏文件**；目标文件已存在时先备份为 `our_models.json.bak`。
- 文本中缺失的价格等关键信息不会编造（留空），**价格单位为元**。
- **人工核对 `aliases` 别名列表**：别名是评论/视频车型匹配的关键，应尽量丰富（简称、口语叫法、英文名）；但需有区分度，避免"X7"这类通用短名误命中其他品牌同名车型。

#### 部署生效

配置在应用启动时加载，替换文件后需重启：

- **Docker Compose**：compose 已将宿主机 `./config` 目录只读挂载进容器（`./config:/app/config:ro`）。把生成的 `our_models.json` 放到服务器项目目录的 `config/` 下，执行 `docker compose restart app`。
- **裸机**：确认文件位于 `OUR_MODELS_CONFIG_PATH` 指向的路径（相对服务工作目录），重启 uvicorn 进程。


---

## 4. 方式一：Docker Compose 部署（推荐）

`docker-compose.yml` 定义了两个服务：`mysql`（8.0，数据持久化到 `mysql_data` 卷）和 `app`（由 `Dockerfile` 构建）。app 通过环境变量把 `DB_HOST` 指向容器 `mysql`，并带健康检查。对外端口取 `.env` 中的 `APP_PORT`（默认 8000），容器内固定监听 `0.0.0.0:8000`。

### 4.1 启动

```bash
docker compose up -d --build
```

首次会构建镜像、拉起 MySQL 并等待其健康（compose 已配置 `depends_on: service_healthy`），随后启动 app。

### 4.2 验证

```bash
# 查看容器状态，app 应为 healthy
docker compose ps

# 健康检查（无需认证）
curl http://localhost:8000/health
# 预期：{"status":"ok"}
```

浏览器打开 `http://<服务器IP>:8000` 可进入 Web 管理页面。

### 4.3 查看日志

```bash
docker compose logs -f app
```

正常应看到「数据库就绪」「Worker 已启动」「API Worker 已启动」等日志。

### 4.4 常用运维命令

```bash
docker compose restart app      # 重启应用
docker compose down             # 停止并移除容器（数据卷保留）
docker compose down -v          # 连同 MySQL 数据卷一并删除（清库，谨慎）
docker compose up -d --build    # 改代码后重新构建并启动
```

> 注意 `docker compose down -v` 会**删除数据库全部数据**，仅在确需清库时使用。

---

## 5. 方式二：裸机部署

适用于已有独立 MySQL、或不便使用 Docker 的环境。

### 5.1 准备 MySQL

安装 MySQL 8.0，创建数据库（字符集 utf8mb4）：

```sql
CREATE DATABASE driveintent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

确保 `.env` 中 `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` 指向该实例。表结构由应用启动时自动创建，无需手动建表。

### 5.2 安装依赖

建议使用虚拟环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

### 5.3 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

生产环境建议用进程管理器（systemd / supervisor）守护，并考虑多 worker：

```bash
# 示例：4 个进程。注意每个进程会各自启动后台 Worker，
# 若不希望重复执行任务，可在部分进程设 WORKER_ENABLED=false / API_WORKER_ENABLED=false，
# 仅由单一进程承担后台任务。
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

> **多进程注意**：应用的后台 Worker 随进程启动，多进程 + 全部启用 Worker 会有多个 Worker 竞争同一任务表。任务领取有状态保护，但为避免资源浪费，推荐「1 个进程跑 Worker + 其余进程仅服务 HTTP」的拆分，或单进程部署。

### 5.4 systemd 示例

`/etc/systemd/system/driveintent.service`：

```ini
[Unit]
Description=DriveIntent
After=network.target mysql.service

[Service]
WorkingDirectory=/opt/DriveIntent
ExecStart=/opt/DriveIntent/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
User=driveintent

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now driveintent
sudo systemctl status driveintent
```

---

## 6. 部署后验证清单

1. `curl http://localhost:8000/health` 返回 `{"status":"ok"}`；
2. 浏览器访问 `http://<IP>:8000` 打开管理页面；
3. 用配置的 API Key 调用 API（下例用 `mock` 也能跑通）：

```bash
curl -X POST http://localhost:8000/api/v1/comment-screening \
  -H "Authorization: Bearer <你的API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"comments":[{"comment_id":"c1","video_title":"测试","video_author":"@作者","comment_content":"这车多少钱","comment_author":"用户1","comment_author_uid":"u1","comment_time":"2026-07-24T10:00:00+08:00"}]}'
# 返回 202 与 job_id，再用 GET /api/v1/jobs/{job_id} 轮询结果
```

API 字段与轮询细节见 `docs/DriveIntent-V1-API对接文档.md`。

也可使用一键冒烟测试脚本（修改脚本顶部配置区的 `BASE_URL` 与 `API_KEY` 后，在任意装有 Python 3.10+ 的机器上运行，无需安装依赖）：

```bash
python scripts/api_smoke_test.py
```

脚本依次验证健康检查、认证拦截、Agent 1 评论初筛、Agent 2 账号画像共 4 项，全部通过退出码为 0。

### 6.1 V1.4.4 专项核对（升级到 V1.4.4 后必做）

V1.4.4 改变了截图的存储方式。以下三项**任意一项不满足，服务都会退化**（截图丢失、或继续以 MB 级 payload 写库并重新引发连接池耗尽），且退化是静默的——业务不报错，只是评级质量下降。故升级后必须逐项确认。

**① 确认容器跑的确实是 V1.4.4 代码**

`app/api/staging.py` 是 V1.4.4 新增模块，可作为版本探针：

```bash
docker compose exec app python -c "import app.api.staging; print('V1.4.4 OK')"
```

打印 `V1.4.4 OK` 即为新代码。若报 `ModuleNotFoundError`，说明容器仍在跑旧镜像——执行 `docker compose up -d --build` 重新构建（**仅 `restart` 不会重建镜像**）。

**② 确认 `./data:/app/data` 已挂载**

```bash
docker inspect $(docker compose ps -q app) --format '{{json .Mounts}}' | python -m json.tool
```

输出中必须存在 `Destination` 为 `/app/data`、`RW` 为 `true` 的条目：

```json
{
    "Type": "bind",
    "Source": "/opt/DriveIntent/data",
    "Destination": "/app/data",
    "RW": true
}
```

没有这条 = 挂载未生效，容器重启会丢失待处理作业的截图。（同时可看到 `Destination: /app/config` 的只读挂载，那是 V1.1 的车型配置。）

**③ 确认暂存目录容器内可写**

```bash
docker compose exec app python -c "import os; d='data/staging'; os.makedirs(d, exist_ok=True); print('writable:', os.access(d, os.W_OK))"
```

预期 `writable: True`。此外服务启动时会主动检查该目录，不可写会**直接启动失败**，故 `docker compose logs app` 中出现「截图暂存目录不可写」即为此问题。

**④ 端到端确认新作业不再写入 base64**

提交一个带截图的作业后，查库确认单行体积为 KB 级而非 MB 级：

```sql
SELECT id, status,
       ROUND(LENGTH(request_payload)/1024) AS payload_kb
FROM api_job
WHERE job_type = 'profile_analysis'
ORDER BY created_at DESC LIMIT 5;
```

V1.4.4 生效后新建作业的 `payload_kb` 应为几十到几百 KB。**若仍出现上万 KB（十几 MB），说明 ① 未生效**，请回到第 ① 步。这是判断升级是否真正落地最可靠的一条。

> **注意 `pending` 不会自行消失**：升级前积压的老作业其 payload 里仍内联着 base64，必须由 Worker 逐个消费完才会被剥离。若升级后观察到 `pending` 长期不下降，先确认 Worker 是否在运行（第 8 节「提交任务后一直 pending」），再看第 9.2 节的存量处置。

---

## 7. 生产加固建议

- **改默认密钥**：`DB_PASSWORD` 与 `API_KEYS` 必须替换为强随机值，`.env` 已在 `.gitignore` 中，勿提交。
- **反向代理与 HTTPS**：`8000` 端口建议置于 Nginx / 云负载均衡之后，启用 TLS，不要将明文 API 直接暴露公网。
- **网络隔离**：MySQL 端口不对公网开放；Compose 部署下 MySQL 仅在内部网络，无需映射到宿主机。
- **数据备份**：Compose 数据在 `mysql_data` 卷，定期 `docker exec` 执行 `mysqldump` 或对卷做快照。
- **并发调优**：按 LLM 服务的吞吐与限流调整 `WORKER_CONCURRENCY`、`API_WORKER_CONCURRENCY` 与 `COMMENT_BATCH_SIZE`。
- **MySQL `max_connections` 须与连接池匹配**：应用侧上限 = `DB_POOL_SIZE + DB_MAX_OVERFLOW`（默认 30），但多进程部署、运维脚本、其他接入方都会共用数据库连接。上线前对比这两个值确认有余量：

  ```sql
  SHOW VARIABLES LIKE 'max_connections';       -- 配置上限
  SHOW STATUS LIKE 'Max_used_connections';     -- 历史峰值
  ```

  峰值贴近甚至等于上限，说明数据库侧已被打满，此时**调大 `DB_POOL_SIZE` 无效**——只是把排队从连接池挪到数据库。MySQL 默认 `max_connections=151` 对本服务偏小，生产建议 ≥500。
- **日志**：应用日志输出到标准输出，Compose 下用 `docker compose logs`，systemd 下用 `journalctl -u driveintent`。

---

## 8. 常见问题

| 现象 | 排查方向 |
|------|---------|
| app 容器一直不 healthy | 查看 `docker compose logs app`；多为 MySQL 未就绪或 `.env` 配置错误 |
| 启动报数据库连接失败 | 核对 `DB_HOST/PORT/USER/PASSWORD/NAME`；裸机方式确认 MySQL 已启动且库已创建 |
| API 返回 401 | 请求头 `Authorization: Bearer <key>` 的 key 不在 `API_KEYS` 列表中 |
| 提交任务后一直 `pending` | 确认 `WORKER_ENABLED` / `API_WORKER_ENABLED` 为 `true`，查看日志是否有「Worker 已启动」。**多机部署时确认跑 Worker 的是哪台**——库里堆积 `pending` 只说明没有 Worker 在消费，不一定是提交端的问题 |
| 升级 V1.4.4 后 `pending` 长期不下降 | 这批多半是升级前提交的老作业（payload 内联 base64，单行十几 MB），必须由 Worker 逐个消费才会被剥离，V1.4.4 的新逻辑对存量不生效。按 6.1 节 ④ 确认新作业已是 KB 级；存量处置见 9.2 节 |
| 真实模型调用失败/超时 | 检查 `LLM_BASE_URL` 是否含 `/v1`、`LLM_API_KEY` 是否有效、网络是否可达；必要时调大 `LLM_TIMEOUT_SECONDS` |
| 主页截图识别不生效 | 确认多模态模型支持图像输入（`LLM_MULTIMODAL_MODEL`，留空则用 `LLM_MODEL`），且 `LLM_PROVIDER=openai_compat` |
| 端点报错拒绝 `enable_thinking` 参数 | 该端点不支持深度思考扩展字段；设 `LLM_ENABLE_THINKING=false`（默认值）即注入 `false`，若仍被拒需确认端点是否完全不接受该参数 |
| 意向降级不生效（从不输出 `filter_type="model_mismatch"`） | 确认 `config/our_models.json` 已生成且容器内可见（Compose 需 `./config` 挂载）、`INTENT_DOWNGRADE_ENABLED=true`；查启动日志是否有"车型配置不存在"警告 |
| 日志出现 `QueuePool limit ... reached` | 先确认版本 ≥ **V1.4.4**（该版本修复了真因：同步 DB 调用在事件循环内执行，读一条 13MB payload 会冻结整个循环约 3.2s，期间所有协程与 HTTP 请求停摆；V1.4.3 只修了会话生命周期，不足以消除该现象）。仍出现时按此顺序排查：① 检查是否有新增的同步端点在长耗时操作期间持有 `get_db()` 会话，或 async 函数内遗留未经 `asyncio.to_thread` 的同步 DB 调用；② 适当调低 `WORKER_CONCURRENCY` / `API_WORKER_CONCURRENCY`；③ **调大 `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` 前必须先确认 MySQL `max_connections` 有余量**（`SHOW STATUS LIKE 'Max_used_connections'` 对比 `SHOW VARIABLES LIKE 'max_connections'`），否则只是把排队从连接池挪到数据库侧 |
| 带截图的作业全部按"无截图"评级 | 检查截图暂存目录是否挂载且可写（compose 需 `./data:/app/data`，核对方法见 6.1 节 ②③）。启动日志会因目录不可写直接报错；若目录可写但作业仍降级，查日志中"截图暂存文件读取失败"或"主页截图识别失败"告警 |
| 升级后新作业 payload 仍是 MB 级 | 容器还在跑旧镜像。`docker compose restart` 不会重建镜像，须 `docker compose up -d --build`；用 6.1 节 ① 的探针确认 |

---

## 9. 截图暂存区（V1.4.4）

V1.4.4 起 **base64 原始截图不再入库**：`POST /api/v1/profile-analysis` 仍照常接收 base64（**对外契约不变**），但服务端会把截图抽到落盘暂存区，库中只保留识图后的纯文本。这使 `api_job` 单行从 MB 级降回 KB 级——存量库中该表 6408MB 里有 9520MB 是 payload，而 result 仅 78MB。

**部署要求**：compose 已挂载 `./data:/app/data`（可写）。**该挂载必须存在**，否则容器重启会丢失待处理作业的截图（丢失后作业降级为无截图继续，不会失败，但评级质量下降）。自建部署方式需保证 `SCREENSHOT_STAGING_DIR`（默认 `data/staging`）指向持久化目录。挂载与代码版本的核对方法见 6.1 节。

暂存文件在作业进入终态时自动删除，失败重试期间保留；进程崩溃遗留的孤儿文件在下次启动时自动回收。

### 9.1 容量与运维

- 峰值占用约「待处理作业数 × 单作业截图体积」，实测单作业平均 13MB。
- 该目录**不需要备份**：文件仅在作业待处理期间存在，终态即删；丢失只导致该作业降级为无截图。
- 目录内是普通 JSON（`<job_id>.json`），可直接查看与人工清理。停机期间清空整个 `data/staging` 是安全操作——待处理作业会降级为无截图继续，不会失败。

### 9.2 存量数据清理

升级到 V1.4.4 后，历史 base64 仍留在库中，需手动清理。**升级前提交的 `pending` 作业其 payload 里仍内联着 base64**，V1.4.4 的新逻辑对它们不生效——只有被 Worker 消费到终态，或被显式清空，这部分体积才会释放。

先按业务需要选择存量 `pending` 的处置方式：

**方式 A：让 Worker 跑完（保留业务数据）**

确认 Worker 正常运行后等待队列自然排空。注意这批老作业每行 13MB 左右，消费速度受识图与 LLM 吞吐限制，耗时以小时计。

**方式 B：直接清空待处理队列（放弃这批业务数据）**

当积压已过时效、不再需要处理时使用。**该操作删除 `pending` 行，不可恢复**：

```bash
python scripts/clear_pending_queue.py          # 预演，不写入
python scripts/clear_pending_queue.py --apply  # 确认后执行
```

脚本只删 `status='pending'` 的行，`running` 与各终态行一律不触碰（`running` 可能正被 Worker 处理，删除会导致 Worker 落状态时找不到行）。

> 升级实测：该批 `pending` 共 1807 行，其中 `profile_analysis` 652 行占 8240MB。

队列处置完成后，清理历史终态行：

```bash
python scripts/cleanup_api_job_payload.py          # 预演，不写入
python scripts/cleanup_api_job_payload.py --apply  # 确认后执行
```

脚本只清空 `profile_analysis` 终态行（success/partial/failed）payload 中的截图字段，**保留 `result`、`status`、时间戳、`progress_*`**（`/audit` 页面依赖这些列统计），`comment_screening` 的大 payload 是评论正文属业务数据不动。分批提交，默认 dry-run。

最后回收物理空间——**删除与清空都不会自动缩小表文件**，必须执行（**会锁表，选业务低峰**）：

```sql
OPTIMIZE TABLE api_job;
```

与补索引脚本同理，Docker 部署时应在宿主机运行这两个脚本，不要用 `docker compose exec app`（`scripts/` 不在镜像内）。

> **两个已知的库侧限制**（排查时会遇到）：`api_job` 单行可达 25MB，任何 `ORDER BY LENGTH(request_payload)` 都会触发 `(1038, Out of sort memory)`，故上述脚本均不排序；此外若数据库账号无 `PROCESS` 权限，`information_schema.innodb_trx` / `processlist` 不可见，属正常现象。

---

## 10. 存量库升级：补充索引脚本

`create_all` 只为新增表建索引，不会给已存在的表补充新增索引。若在**已有数据库**基础上升级到 V1.4（而非全新部署），需在宿主机手动执行一次审计聚合所需的补索引脚本：

```bash
python scripts/add_audit_indexes.py
```

该脚本为 `llm_call_log(created_at)` 补 `ix_llm_call_created`、为 `api_job(finished_at)` 补 `ix_api_job_finished`，幂等可重复执行。**注意**：Docker 部署时 `scripts/` 目录不在镜像内，应在宿主机（有 `.env` 与 Python 环境处）直接运行，不要用 `docker compose exec app` 在容器内执行。

全新部署无需执行此脚本，首次启动 `create_all` 会自动建出全部最新索引。
