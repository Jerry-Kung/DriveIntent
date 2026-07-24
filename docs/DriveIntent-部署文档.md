# DriveIntent 部署文档

**版本**：V1.0　**更新日期**：2026-07-24　**服务默认端口**：8000

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
| 磁盘 | 10G 以上（含 MySQL 数据卷与镜像） |
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
| `LLM_PROVIDER` | `mock` | `mock`（本地假数据，联调用）或 `openai_compat`（真实模型） |
| `LLM_BASE_URL` | 空 | OpenAI 兼容接口地址，**须含 `/v1` 前缀**，如 `https://api.example.com/v1` |
| `LLM_API_KEY` | 空 | 模型服务的 API Key |
| `LLM_MODEL` | `mock-model` | 模型名；启用主页截图识别需模型支持图像输入 |
| `LLM_TIMEOUT_SECONDS` | `120` | 单次 LLM 调用超时（秒） |
| `LLM_MAX_RETRIES` | `3` | LLM 调用失败重试次数 |
| `API_KEYS` | `change-me-key1,change-me-key2` | **对外 API 的访问密钥**，逗号分隔多个，**生产务必修改** |
| `API_WORKER_ENABLED` | `true` | 是否启用 API 任务 Worker（关闭则 API 任务不执行） |
| `API_WORKER_CONCURRENCY` | `3` | API Worker 并发数 |
| `WORKER_ENABLED` | `true` | 是否启用业务 Worker（Web 端导入分析用） |
| `WORKER_CONCURRENCY` | `3` | 业务 Worker 并发数 |
| `WORKER_POLL_INTERVAL` | `1.0` | Worker 轮询任务间隔（秒） |
| `COMMENT_BATCH_SIZE` | `30` | 评论批处理条数 |

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

---

## 7. 生产加固建议

- **改默认密钥**：`DB_PASSWORD` 与 `API_KEYS` 必须替换为强随机值，`.env` 已在 `.gitignore` 中，勿提交。
- **反向代理与 HTTPS**：`8000` 端口建议置于 Nginx / 云负载均衡之后，启用 TLS，不要将明文 API 直接暴露公网。
- **网络隔离**：MySQL 端口不对公网开放；Compose 部署下 MySQL 仅在内部网络，无需映射到宿主机。
- **数据备份**：Compose 数据在 `mysql_data` 卷，定期 `docker exec` 执行 `mysqldump` 或对卷做快照。
- **并发调优**：按 LLM 服务的吞吐与限流调整 `WORKER_CONCURRENCY`、`API_WORKER_CONCURRENCY` 与 `COMMENT_BATCH_SIZE`。
- **日志**：应用日志输出到标准输出，Compose 下用 `docker compose logs`，systemd 下用 `journalctl -u driveintent`。

---

## 8. 常见问题

| 现象 | 排查方向 |
|------|---------|
| app 容器一直不 healthy | 查看 `docker compose logs app`；多为 MySQL 未就绪或 `.env` 配置错误 |
| 启动报数据库连接失败 | 核对 `DB_HOST/PORT/USER/PASSWORD/NAME`；裸机方式确认 MySQL 已启动且库已创建 |
| API 返回 401 | 请求头 `Authorization: Bearer <key>` 的 key 不在 `API_KEYS` 列表中 |
| 提交任务后一直 `pending` | 确认 `WORKER_ENABLED` / `API_WORKER_ENABLED` 为 `true`，查看日志是否有「Worker 已启动」 |
| 真实模型调用失败/超时 | 检查 `LLM_BASE_URL` 是否含 `/v1`、`LLM_API_KEY` 是否有效、网络是否可达；必要时调大 `LLM_TIMEOUT_SECONDS` |
| 主页截图识别不生效 | 确认 `LLM_MODEL` 支持图像输入，且 `LLM_PROVIDER=openai_compat` |
