# 安装部署手册（INSTALL.md）

> **版本**：v1.0.0  
> **适用**：DNS Zone Manager 后端 + 前端 + 反向代理整体交付  
> **目标读者**：客户现场运维 / 实施工程师

本文档覆盖从「拿到代码 / 镜像」到「线上 HTTPS 访问」的全部步骤，并附升级、备份、迁移、扩容指引。

---

## 📑 目录

1. [部署前准备](#1-部署前准备)
2. [三种部署模式](#2-三种部署模式)
3. [方式 A：Docker Compose Lite（推荐单机）](#3-方式-adocker-compose-lite推荐单机)
4. [方式 B：Docker Compose Full（PostgreSQL + Redis）](#4-方式-bdocker-compose-fullpostgresql--redis)
5. [方式 C：Kubernetes（大规模生产）](#5-方式-ckubernetes大规模生产)
6. [SSL 证书配置](#6-ssl-证书配置)
7. [F5 设备连接配置](#7-f5-设备连接配置)
8. [首次登录与基础设置](#8-首次登录与基础设置)
9. [数据备份与恢复](#9-数据备份与恢复)
10. [升级流程](#10-升级流程)
11. [性能基线与扩容指引](#11-性能基线与扩容指引)
12. [卸载](#12-卸载)

---

## 1. 部署前准备

### 1.1 硬件 / 虚拟机最低要求

| 资源 | Lite 模式（< 50 区域） | Full 模式（> 50 区域） |
|------|------------------------|------------------------|
| CPU | 2 核 | 4 核 |
| 内存 | 2 GB（建议 4 GB） | 8 GB |
| 磁盘 | 20 GB（含镜像与备份） | 50 GB |
| 网络 | 1 GbE，能 SSH 到 F5 | 同左 |

### 1.2 软件前置条件

| 软件 | 最低版本 | 安装方式 |
|------|----------|----------|
| Docker Engine | 24.0 | [官方脚本](https://docs.docker.com/engine/install/) |
| Docker Compose | v2.20+ | `apt install docker-compose-plugin` |
| OpenSSL | 1.1.1+ | 系统自带 |
| Git（仅源码部署） | 2.30+ | `apt install git` |

### 1.3 网络与安全要求

| 项 | 要求 |
|----|------|
| 入站 TCP | 80（HTTP 重定向）、443（HTTPS）|
| 出站 TCP 22 | 到 F5 BIG-IP 的 SSH 端口（默认 22）|
| 出站 TCP 443 | 拉取 Docker Hub 镜像（若离线可跳过）|
| 防火墙策略 | 禁止暴露 8000、5432、6379 等内部端口 |

### 1.4 F5 BIG-IP 准备

在 F5 上确认以下信息（在部署本系统**之前**完成）：

1. **SSH 服务已启用**：F5 管理口 `mykeys` 已生成至少一对 SSH 密钥对，或允许密码登录
2. **named 路径可访问**（默认）：
   - `named.conf`：`/var/named/config/named.conf`（chroot 后路径 `/config/named.conf`）
   - zone 目录：`/var/named/config/namedb/`（chroot 后路径 `/config/namedb/`）
3. **建议为本系统创建专用 SSH 用户**：
   ```bash
   # F5 shell（tmsh 不直接支持，使用 bash 或 imish）
   useradd dnsmanager -m -s /bin/bash
   # 把 ssh 公钥加到 ~dnsmanager/.ssh/authorized_keys
   # 并给予 /var/named/config 的读取权限
   chmod -R a+r /var/named/config
   ```
4. **rndc key 已就位**：F5 默认会生成 `/var/named/config/rndc.key`，本系统会自动发现

---

## 2. 三种部署模式

| 模式 | 数据库 | 容器数 | 适用场景 |
|------|--------|--------|----------|
| **Lite** | SQLite（卷挂载） | 2 | 单机部署、PoC、小团队 |
| **Full** | PostgreSQL 15 | 4 | 多实例共享数据库、HA |
| **K8s** | PostgreSQL Operator | N | 大规模生产 |

> 默认推荐 **Lite**，零外部依赖，5 分钟上线。

---

## 3. 方式 A：Docker Compose Lite（推荐单机）

### 3.1 准备代码与配置

```bash
# 创建工作目录
mkdir -p /opt/dns-manager && cd /opt/dns-manager

# 二选一
# A.1 从源码部署（开发 / 内部使用）
git clone https://github.com/<owner>/dns-manager.git .
# A.2 从离线包部署（交付场景，跳过本步）
#    tar xzf dns-manager-v1.0.0-offline.tar.gz --strip-components=1
```

### 3.2 配置环境变量

```bash
cp .env.example .env

# 必须修改：
# 1. JWT 密钥（≥ 32 字节随机）
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# 2. F5 连接信息
vim .env
#   F5_ACTIVE_HOST=<F5 管理 IP>
#   F5_SSH_USER=dnsmanager
#   F5_SSH_PASSWORD=<password>      # 与 SSH 密钥二选一
#   F5_SSH_KEY_PATH=./ssh_keys/id_ed25519

# 3. （可选）修改 web 端口
#   HTTP_PORT=80
#   HTTPS_PORT=443
```

### 3.3 准备 SSH 私钥（推荐）

```bash
mkdir -p ssh_keys
# 把你生成的 F5 客户端私钥放进来
cp /path/to/f5_client_key ssh_keys/id_ed25519
chmod 600 ssh_keys/id_ed25519
```

### 3.4 生成 SSL 证书

**自签名（内网 PoC）**：

```bash
chmod +x generate-certs.sh
./generate-certs.sh your-server-ip
# 生成 nginx/certs/fullchain.pem 与 privkey.pem
```

**Let's Encrypt（生产）**：

```bash
# 使用 certbot 申请（一次性）
sudo apt install certbot
sudo certbot certonly --standalone -d dns.example.com
# 把证书拷贝到 nginx/certs/
sudo cp /etc/letsencrypt/live/dns.example.com/fullchain.pem nginx/certs/
sudo cp /etc/letsencrypt/live/dns.example.com/privkey.pem   nginx/certs/
sudo chown -R $USER:$USER nginx/certs/
# 之后证书自动续签可通过 cron + 复制脚本实现，参考 docs/OPERATIONS.md
```

### 3.5 启动

```bash
# 构建并后台启动
docker compose -f docker-compose.lite.yml up -d --build

# 查看状态
docker compose -f docker-compose.lite.yml ps
# NAME           STATUS                   PORTS
# dns-backend    Up 2 minutes (healthy)   8000/tcp
# dns-frontend   Up 2 minutes (healthy)   0.0.0.0:80->80, 0.0.0.0:443->443

# 实时日志
docker compose -f docker-compose.lite.yml logs -f
```

### 3.6 验证

```bash
# 1) 健康检查
curl -sk https://localhost/api/health
# {"status":"ok","version":"1.0.0","f5_active_host":"...","configured_devices":1}

# 2) 登录
curl -sk -X POST https://localhost/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
# 返回 access_token

# 3) 浏览器访问
echo "Open: https://<your-server-ip>/"
```

### 3.7 防火墙放行（云上环境必做）

| 平台 | 操作 |
|------|------|
| 腾讯云 CVM | 控制台 → 安全组 → 入站规则 → 添加 TCP:443 来源 0.0.0.0/0 |
| 阿里云 ECS | 控制台 → 安全组 → 入站规则 → 添加 TCP:443 来源 0.0.0.0/0 |
| AWS EC2 | Security Group → Inbound → Add Rule → Custom TCP 443 Anywhere |
| 自建机房 | `iptables -A INPUT -p tcp --dport 443 -j ACCEPT` 或防火墙策略 |

---

## 4. 方式 B：Docker Compose Full（PostgreSQL + Redis）

适用于多实例部署或需要横向扩展的场景。

```bash
# 使用 docker-compose.yml（Full 模式）
docker compose up -d --build

# 容器列表：
# - dns-backend      FastAPI 应用
# - dns-frontend     nginx 反向代理
# - dns-postgres     PostgreSQL 15
# - dns-redis        Redis 7（备用，预留扩展）
```

**关键配置**（`.env`）：

```bash
USE_SQLITE=false
POSTGRES_USER=dns_admin
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=dns_manager
```

数据持久化在 `postgres_data`、`dns_manager_db_data`、`redis_data` 三个命名卷。

---

## 5. 方式 C：Kubernetes（大规模生产）

> K8s manifests 在 [deploy/k8s/](deploy/k8s/) 下（占位，实际交付按客户环境调整）。

最小清单：

- 1 个 `Deployment`（backend，replicas ≥ 2）+ `Service`（ClusterIP）
- 1 个 `Deployment`（frontend，replicas ≥ 2）+ `Service`（LoadBalancer 或 Ingress）
- 1 个外部 PostgreSQL（或 CloudNativePG Operator）
- 1 个 `Secret`（JWT_SECRET、F5 私钥）
- 1 个 `PersistentVolumeClaim`（备份目录）

Ingress 示例（nginx-ingress + cert-manager）：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dns-manager
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts: [dns.example.com]
      secretName: dns-manager-tls
  rules:
    - host: dns.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend: { service: { name: dns-backend, port: { number: 8000 } } }
          - path: /
            pathType: Prefix
            backend: { service: { name: dns-frontend, port: { number: 80 } } }
```

---

## 6. SSL 证书配置

### 6.1 自签名证书（PoC / 内网）

`generate-certs.sh` 生成的证书：

- 包含 SAN IP/域名
- 825 天有效期
- 客户端首次访问需手动信任（浏览器会提示「不安全」）

### 6.2 Let's Encrypt 证书（生产）

1. 申请证书（DNS 验证更稳，避免 80 端口冲突）：

   ```bash
   certbot certonly --dns-cloudflare --dns-cloudflare-credentials ~/.secrets/cloudflare.ini \
     -d dns.example.com -d *.dns.example.com
   ```

2. 部署到容器：

   ```bash
   # 把证书挂载到 nginx 容器（修改 docker-compose.lite.yml）
   volumes:
     - ./nginx/certs/letsencrypt:/etc/nginx/certs:ro
   ln -sf letsencrypt/fullchain.pem nginx/certs/fullchain.pem
   ln -sf letsencrypt/privkey.pem   nginx/certs/privkey.pem
   ```

3. 自动续签（crontab）：

   ```cron
   0 3 * * * certbot renew --deploy-hook "/opt/dns-manager/scripts/renew-cert.sh"
   ```

   `scripts/renew-cert.sh` 复制新证书并 `docker compose restart frontend`。

### 6.3 商业 CA / 企业内部 CA

把 `fullchain.pem`（含中间证书）和 `privkey.pem` 放到 `nginx/certs/`，重启 frontend：

```bash
docker compose -f docker-compose.lite.yml restart frontend
```

---

## 7. F5 设备连接配置

### 7.1 单设备（环境变量）

`.env` 中的 `F5_*` 变量是「种子设备」，启动时自动写入数据库（`group_name=BQJ-01`）。

### 7.2 多设备（Web UI）

进入「设备管理」→ 「新增设备」：

| 字段 | 说明 |
|------|------|
| 设备名称（组名） | 例如 `SH-01`（上海数据中心） |
| 主机 | F5 管理 IP |
| SSH 端口 | 默认 22 |
| 用户名 | 推荐 `dnsmanager` 专用账号 |
| 认证方式 | SSH 密钥（推荐）或密码 |
| 私钥路径 | 容器内路径 `/app/keys/<id>` |
| named.conf 路径 | 默认即可 |
| zone 目录 | 默认即可 |

新增后**重启 backend** 使 SSH 连接器重新加载：

```bash
docker compose -f docker-compose.lite.yml restart backend
```

### 7.3 验证连通性

```bash
docker compose -f docker-compose.lite.yml exec backend python -c "
from app.services.ssh_connector import ssh_connector
import asyncio
async def t():
    devs = ssh_connector._devices
    for did, cfg in devs.items():
        ok, msg = await ssh_connector.test_connection(did)
        print(f'Device {did} ({cfg[\"host\"]}): {ok} - {msg}')
asyncio.run(t())
"
```

---

## 8. 首次登录与基础设置

### 8.1 默认账号（首次登录后**必须**修改）

| 用户名 | 密码 | 角色 |
|--------|------|------|
| `admin` | `admin123` | super_admin（全权限）|
| `ops` | `ops123456` | zone_operator（可写已授权区域）|
| `approver` | `appr123456` | approver（审批变更）|
| `viewer` | `view123456` | zone_viewer（只读）|

### 8.2 修改默认密码

「用户管理」→ 选中账号 → 「重置密码」→ 输入 ≥ 8 位含大小写字母与数字的强密码。

### 8.3 配置 SMTP（可选，用于变更审批通知）

进入 `.env`：

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=<password>
SMTP_FROM=DNS Manager <noreply@example.com>
```

重启 backend 后生效。

---

## 9. 数据备份与恢复

### 9.1 SQLite Lite 模式

**备份**（推荐每日定时）：

```bash
# 备份 SQLite 数据库
docker compose -f docker-compose.lite.yml exec backend \
  sqlite3 /app/data/dns_manager.db ".backup '/app/data/backup-$(date +%Y%m%d).db'"

# 拷贝到主机
docker cp dns-backend:/app/data/backup-20260904.db ./backups/
```

**恢复**：

```bash
# 停服
docker compose -f docker-compose.lite.yml stop backend
# 覆盖数据库
docker cp ./backups/backup-20260904.db dns-backend:/app/data/dns_manager.db
# 启动
docker compose -f docker-compose.lite.yml start backend
```

**zone 文件备份**：

DNS zone 文件位于 F5 上，由本系统每次写操作前自动备份到 F5 的 `/var/named/config/namedb/.backups/`。如需导出：

```bash
docker compose -f docker-compose.lite.yml exec backend \
  rsync -av dnsmanager@<f5-host>:/var/named/config/namedb/.backups/ /opt/dns-manager/backups/zones/
```

### 9.2 PostgreSQL Full 模式

```bash
# 备份
docker compose exec postgres pg_dump -U dns_admin dns_manager | gzip > backups/db-$(date +%Y%m%d).sql.gz

# 恢复
gunzip -c backups/db-20260904.sql.gz | docker compose exec -T postgres psql -U dns_admin dns_manager
```

---

## 10. 升级流程

### 10.1 标准升级（Lite）

```bash
# 1. 备份
./scripts/backup.sh  # 参见 docs/OPERATIONS.md

# 2. 拉取新镜像（或拉新代码）
git pull origin main
# 或
docker pull <owner>/dns-manager-backend:v1.1.0
docker pull <owner>/dns-manager-frontend:v1.1.0

# 3. 滚动升级（先 backend，再 frontend）
docker compose -f docker-compose.lite.yml up -d --no-deps backend
sleep 30  # 等待健康检查通过
docker compose -f docker-compose.lite.yml up -d --no-deps frontend

# 4. 验证
curl -sk https://localhost/api/health
```

### 10.2 回滚

```bash
# 把镜像 tag 切回上一个版本
docker tag <owner>/dns-manager-backend:v1.0.0 dns-manager-backend:latest
docker tag <owner>/dns-manager-frontend:v1.0.0 dns-manager-frontend:latest
docker compose -f docker-compose.lite.yml up -d
```

---

## 11. 性能基线与扩容指引

### 11.1 基线（Lite 模式，2C4G）

| 指标 | 值 |
|------|---|
| 首屏加载 | < 500 ms |
| API 平均响应 | < 50 ms |
| 并发用户 | 50 |
| 区域数 | ≤ 200 |
| 单区域记录数 | ≤ 5000 |
| F5 SSH 连接复用 | 长期 keepalive，无需频繁重连 |

### 11.2 扩容触发条件

| 信号 | 阈值 | 应对 |
|------|------|------|
| 内存使用率 | > 80% | 升级到 Full 模式 + 8G 内存 |
| API p99 响应 | > 500 ms | 增加 backend 副本数（Full / K8s） |
| SQLite 锁等待 | > 10 ms | 切换到 PostgreSQL |
| 备份时长 | > 5 min | 切换到 PostgreSQL + pg_dump 并行 |

---

## 12. 卸载

```bash
# 停服并删除容器、网络
docker compose -f docker-compose.lite.yml down

# 同时删除数据卷（⚠️ 不可逆）
docker compose -f docker-compose.lite.yml down -v

# 删除镜像（可选）
docker image prune -a
```

---

## 📞 获取帮助

| 渠道 | 用途 |
|------|------|
| GitHub Issues | Bug 报告、功能请求 |
| [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 常见问题自助排查 |
| [docs/OPERATIONS.md](OPERATIONS.md) | 日常运维、监控、应急 |

---

> **下一步**：安装完成后，请阅读 [docs/USER_GUIDE.md](USER_GUIDE.md) 学习日常使用，或 [docs/OPERATIONS.md](OPERATIONS.md) 配置监控告警。