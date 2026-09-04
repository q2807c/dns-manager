# DNS Zone Manager — Docker 部署指南

## 前置条件

- Docker 20.10+ 及 Docker Compose v2
- F5 BIG-IP DNS 设备的 SSH 访问权限（密钥或密码）

## 快速部署（一键脚本）

```bash
# 1. 克隆/解压项目
cd dns-manager

# 2. 放置 F5 SSH 密钥（如使用密钥认证）
cp ~/.ssh/id_ed25519 ssh_keys/

# 3. 一键部署
./deploy.sh
```

脚本会引导你选择部署模式，自动生成 `.env` 配置、SSL 证书，构建并启动服务。

## 部署模式

### Lite 模式（推荐）

| 项目 | 说明 |
|------|------|
| 数据库 | SQLite（文件持久化） |
| 容器数 | 2（frontend + backend） |
| 启动时间 | ~30 秒 |
| 适用场景 | 测试、小团队、PoC |

```bash
docker compose -f docker-compose.lite.yml up -d --build
```

### Full 模式

| 项目 | 说明 |
|------|------|
| 数据库 | PostgreSQL 15 |
| 容器数 | 3（frontend + backend + postgres） |
| 启动时间 | ~60 秒 |
| 适用场景 | 生产环境、多用户、高并发 |

```bash
docker compose up -d --build
```

## 配置说明

### 环境变量 (.env)

复制 `.env.example` 为 `.env`，修改关键配置：

```bash
# F5 连接（必填）
F5_ACTIVE_HOST=172.18.1.202
F5_SSH_USER=root
F5_SSH_KEY_PATH=/app/keys/id_ed25519  # 容器内路径

# JWT 密钥（生产环境必须修改）
JWT_SECRET=<openssl rand -hex 32>

# Web 端口（可选）
HTTPS_PORT=443
```

### SSH 密钥

将 F5 的 SSH 私钥放入 `ssh_keys/` 目录，容器会挂载到 `/app/keys/`：

```bash
mkdir -p ssh_keys
cp /path/to/f5-key ssh_keys/id_ed25519
chmod 600 ssh_keys/id_ed25519
```

### SSL 证书

默认使用自签名证书。如需替换为正式证书：

```bash
# 放入 nginx/certs/ 目录
cp your-cert.crt nginx/certs/server.crt
cp your-cert.key nginx/certs/server.key
```

## 访问

部署完成后：

- **URL**: `https://<服务器IP>` 或 `https://localhost`
- **默认账号**:

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | 超级管理员 |
| ops | ops123456 | DNS 操作员 |
| viewer | view123456 | 只读用户 |
| approver | appr123456 | 审批人 |

> ⚠️ 首次登录后请立即修改默认密码

## 常用命令

```bash
# 查看日志
docker compose -f docker-compose.lite.yml logs -f

# 查看状态
docker compose -f docker-compose.lite.yml ps

# 重启服务
docker compose -f docker-compose.lite.yml restart

# 停止服务
docker compose -f docker-compose.lite.yml down

# 停止并删除数据（⚠️ 不可恢复）
docker compose -f docker-compose.lite.yml down -v
```

## 数据持久化

### Lite 模式
- SQLite 数据库: Docker volume `db_data` → `/app/data/dns_manager.db`
- Zone 备份: `./backups/` 目录

### Full 模式
- PostgreSQL 数据: Docker volume `pg_data`
- Zone 备份: `./backups/` 目录

## 架构

```
                    ┌─────────────┐
  HTTPS :443  ─────►│  Frontend   │  (nginx: 静态文件 + /api 反代)
                    │  (nginx)    │
                    └──────┬──────┘
                           │ proxy /api/
                    ┌──────▼──────┐
                    │  Backend    │  (FastAPI + uvicorn)
                    │  :8000      │
                    └──────┬──────┘
                           │ SSH
                    ┌──────▼──────┐
                    │  F5 BIG-IP  │  (BIND named + DNS Express)
                    │  DNS        │
                    └─────────────┘
```

## 升级

```bash
# 拉取最新代码后
docker compose -f docker-compose.lite.yml build
docker compose -f docker-compose.lite.yml up -d
```

数据库 schema 变更会在 entrypoint 中自动执行 `create_all`。

## 故障排查

### 后端启动失败

```bash
# 查看后端日志
docker compose -f docker-compose.lite.yml logs backend

# 常见原因：
# 1. SSH 密钥未放置 → 检查 ssh_keys/ 目录
# 2. F5 不可达 → 检查网络和 F5_ACTIVE_HOST 配置
# 3. 端口冲突 → 修改 .env 中的 HTTP_PORT/HTTPS_PORT
```

### 前端访问 502

```bash
# 检查后端是否健康
docker compose -f docker-compose.lite.yml exec backend curl http://localhost:8000/api/health
```

### 数据库初始化失败

```bash
# 进入后端容器手动初始化
docker compose -f docker-compose.lite.yml exec backend python seed.py
```
