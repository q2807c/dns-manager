# 运维手册（OPERATIONS.md）

> **版本**：v1.0.0  
> **面向**：客户现场运维、SRE  
> **前置**：已完成 [INSTALL.md](INSTALL.md) 部署并通过基础验证

---

## 📑 目录

1. [日常检查](#1-日常检查)
2. [监控指标](#2-监控指标)
3. [日志管理](#3-日志管理)
4. [备份与恢复策略](#4-备份与恢复策略)
5. [性能优化](#5-性能优化)
6. [扩容指引](#6-扩容指引)
7. [安全加固](#7-安全加固)
8. [应急响应 Runbook](#8-应急响应-runbook)
9. [例行维护任务清单](#9-例行维护任务清单)

---

## 1. 日常检查

### 1.1 健康检查（建议每 4 小时一次）

```bash
# HTTP 健康端点
curl -sk https://localhost/api/health | jq .

# 期望返回：
# { "status": "ok", "version": "1.0.0", "f5_active_host": "...", "configured_devices": N }
```

### 1.2 容器状态（建议每 15 分钟巡检）

```bash
docker compose -f docker-compose.lite.yml ps

# 容器 Restart count 字段应为 0
# 容器 STATUS 应为 "(healthy)"
```

### 1.3 资源使用（每日一次）

```bash
# 主机
top -bn1 | head -20
df -h /
free -h

# 容器内
docker stats --no-stream
```

### 1.4 F5 连接保活（每日一次）

```bash
docker compose -f docker-compose.lite.yml exec backend python -c "
import asyncio
from app.services.ssh_connector import ssh_connector

async def t():
    for did, cfg in list(ssh_connector._devices.items()):
        ok, msg = await ssh_connector.test_connection(did)
        print(f'[{cfg[\"host\"]}] {\"OK\" if ok else \"FAIL\"}: {msg}')
asyncio.run(t())
"
```

---

## 2. 监控指标

### 2.1 推荐接入 Prometheus

容器已暴露 `/api/health`，可基于 nginx accesslog + backend stdout 自建指标。

**最小化 Prometheus 配置**（`prometheus.yml`）：

```yaml
scrape_configs:
  - job_name: 'dns-manager-frontend'
    static_configs:
      - targets: ['<server-ip>:9113']  # nginx-prometheus-exporter
  - job_name: 'dns-manager-backend'
    static_configs:
      - targets: ['<server-ip>:8000']
    metrics_path: /metrics  # 需后端启用 prometheus-fastapi-instrumentator
```

### 2.2 关键 SLI/SLO

| 指标 | 目标 | 测量方式 |
|------|------|----------|
| 可用性 | ≥ 99.9% | `/api/health` 5xx 比例 |
| API p99 延迟 | ≤ 1s | nginx access log 解析 |
| F5 SSH 失败率 | < 0.1% | `audit_log` action=test_connection |
| 数据库大小 | 增长 < 100 MB/月 | `du -sh` SQLite 文件 |
| 备份成功率 | ≥ 99% | 定时任务退出码 |

### 2.3 推荐告警规则

| 告警 | 阈值 | 严重程度 |
|------|------|----------|
| 容器 unhealthy | 持续 > 5 min | 高 |
| API p99 > 3s | 持续 > 10 min | 中 |
| 磁盘使用 > 85% | 持续 > 30 min | 中 |
| 内存使用 > 90% | 持续 > 15 min | 中 |
| F5 SSH 失败 | 连续 3 次 | 高 |
| 备份未生成 | 跨过预定时间 2h | 中 |
| JWT_SECRET 仍为占位值 | 启动时检查 | 高 |

### 2.4 接入告警渠道（示例）

可对接 Prometheus Alertmanager → 飞书 / 钉钉 / 邮件 / 企业微信。

---

## 3. 日志管理

### 3.1 日志位置

| 来源 | 路径 / 命令 |
|------|-------------|
| 后端 stdout | `docker compose logs backend` |
| 前端 nginx access | 容器内 `/var/log/nginx/access.log`（已配置 stdout） |
| 前端 nginx error | 同上 |
| F5 操作 | 写入 `audit_log` 表 |
| SSH 详细日志 | `app.services.ssh_connector` logger |

### 3.2 配置日志级别

`.env`：

```bash
LOG_LEVEL=INFO  # DEBUG / INFO / WARNING / ERROR
```

DEBUG 级别会输出所有 SSH 原始字节（敏感信息风险，**仅排查时短暂开启**）。

### 3.3 日志轮转

Docker 已配置 json-file driver：

```json
// /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
```

即每个容器最多 3 个 10 MB 日志文件，约 30 MB 滚动保留。

### 3.4 集中日志（可选）

将 `docker compose logs` 输出到 Loki / ELK：

```bash
docker compose -f docker-compose.lite.yml logs --no-color | \
  awk '{print $0}' | \
  curl -X POST http://loki:3100/loki/api/v1/push --data-binary @-
```

或使用 Promtail / Filebeat sidecar。

---

## 4. 备份与恢复策略

### 4.1 备份三件套

| 备份对象 | 频率 | 保留 | 工具 |
|----------|------|------|------|
| SQLite 数据库 | 每日 02:00 | 30 天 | cron + sqlite3 .backup |
| zone 文件 | 每次写操作前自动 | 90 天 | `zone_backups` 表 |
| F5 named.conf | 每次写操作前自动 | 30 天 | rsync |

### 4.2 自动备份脚本

部署目录 `scripts/backup.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR=/opt/dns-manager/backups
DATE=$(date +%Y%m%d-%H%M)
COMPOSE="docker compose -f /opt/dns-manager/docker-compose.lite.yml"

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/zones"

# 1. SQLite 备份
$COMPOSE exec -T backend \
  sqlite3 /app/data/dns_manager.db \
  ".backup '/app/data/backup-${DATE}.db'"
docker cp dns-backend:/app/data/backup-${DATE}.db \
  "$BACKUP_DIR/daily/"

# 2. F5 zone 备份（增量）
$COMPOSE exec -T backend rsync -az \
  dnsmanager@<f5-host>:/var/named/config/namedb/ \
  "$BACKUP_DIR/zones/${DATE}/" \
  || echo "WARN: zone rsync failed, will retry next run"

# 3. 清理 > 30 天
find "$BACKUP_DIR/daily" -name "*.db" -mtime +30 -delete
find "$BACKUP_DIR/zones" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +

echo "[$(date)] backup done: ${DATE}"
```

加入 crontab：

```cron
0 2 * * * /opt/dns-manager/scripts/backup.sh >> /var/log/dns-manager-backup.log 2>&1
```

### 4.3 异地备份（强烈建议）

```bash
# 增量 rsync 到异地（NFS / S3 / 备份服务器）
rsync -az --delete \
  /opt/dns-manager/backups/ \
  backup@backup-server:/srv/dns-manager/backups/
```

S3 示例（使用 AWS CLI）：

```bash
0 4 * * * aws s3 sync /opt/dns-manager/backups s3://my-bucket/dns-manager/ --delete
```

### 4.4 恢复演练（每季度 1 次）

详见 [INSTALL.md §9](INSTALL.md#9-数据备份与恢复)。建议：

1. 在测试环境用上周备份恢复
2. 验证可登录、记录可见
3. 记录 RTO / RPO

---

## 5. 性能优化

### 5.1 Lite 模式（SQLite）

```bash
# 启用 WAL 模式（提升并发读）
docker compose -f docker-compose.lite.yml exec backend \
  sqlite3 /app/data/dns_manager.db "PRAGMA journal_mode=WAL;"

# 调整缓存
docker compose -f docker-compose.lite.yml exec backend \
  sqlite3 /app/data/dns_manager.db "PRAGMA cache_size=-64000;"  # 64MB
```

### 5.2 nginx 调优

`frontend/nginx-docker.conf` 中可调：

```nginx
worker_processes auto;        # 默认即可
worker_connections 2048;

# gzip
gzip on;
gzip_types text/plain text/xml application/javascript application/json;
gzip_min_length 1024;

# 静态资源缓存
location ~* \.(js|css|woff2?)$ {
    expires 7d;
    add_header Cache-Control "public, immutable";
}
```

### 5.3 后端调优

`docker-compose.lite.yml`：

```yaml
backend:
  command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --loop uvloop --http httptools
```

### 5.4 F5 SSH 优化

`app/services/ssh_connector.py` 已实现：

- 单设备单长连接
- 自动重连（检测到断开后惰性重连）
- 命令批量执行（合并多次 SSH 调用为一次会话）

---

## 6. 扩容指引

### 6.1 何时扩容

| 信号 | 阈值 | 扩容方式 |
|------|------|----------|
| API p99 > 1s | 持续 | backend 多 worker / 多副本 |
| SQLite 写入慢 | > 50 ms | 切换到 Full 模式 |
| 备份耗时 > 30 min | 持续 | 并行备份 + 切换 PG |
| 区域数 > 200 | - | 切换到 Full 模式 |

### 6.2 Lite → Full 切换

```bash
# 1. 备份当前数据
docker compose -f docker-compose.lite.yml exec backend \
  sqlite3 /app/data/dns_manager.db ".dump" > backup.sql

# 2. 停止 Lite
docker compose -f docker-compose.lite.yml down

# 3. 启动 Full
docker compose up -d --build

# 4. 导入数据（先 psql 创建 schema）
cat backup.sql | docker compose exec -T postgres psql -U dns_admin dns_manager
```

### 6.3 Full → K8s 切换

参见 [INSTALL.md §5](INSTALL.md#5-方式-ckubernetes大规模生产) 的 K8s manifests。

---

## 7. 安全加固

### 7.1 必做（部署后立即）

- [ ] **修改默认密码**：`admin / admin123` 等
- [ ] **生成强 JWT_SECRET**：`openssl rand -hex 32`
- [ ] **使用 SSH 密钥认证 F5**：禁用密码登录
- [ ] **HTTPS 证书**：生产用 Let's Encrypt / 商业 CA
- [ ] **安全组 / 防火墙**：仅开放 80 / 443，关闭 22 入站
- [ ] **数据库加密备份**：异地备份启用 AES-256 加密

### 7.2 建议（生产环境）

- [ ] **开启 2FA**：对接 LDAP / OIDC（待 v1.1 支持）
- [ ] **审计日志外发**：复制 `audit_log` 到独立 SIEM
- [ ] **变更窗口限制**：通过 iptables / nginx 限制非工作时间访问
- [ ] **CSP / HSTS**：在 nginx 配置 `Strict-Transport-Security` 头
- [ ] **依赖扫描**：`pip-audit` / `npm audit` 接入 CI

### 7.3 nginx 安全头（推荐）

`frontend/nginx-docker.conf`：

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;" always;
```

---

## 8. 应急响应 Runbook

### 8.1 场景 1：服务完全不可用

```bash
# 1) 看容器状态
docker compose -f docker-compose.lite.yml ps

# 2) 看最近日志
docker compose -f docker-compose.lite.yml logs --tail=200

# 3) 常见根因：
#    - 磁盘满 → df -h
#    - OOM    → dmesg | grep -i oom
#    - 端口冲突 → ss -lntp | grep -E ':(80|443)'
#    - F5 不可达 → telnet <f5-host> 22

# 4) 重启
docker compose -f docker-compose.lite.yml restart
```

### 8.2 场景 2：能访问但 F5 同步失败

```bash
# 1) SSH 测试
docker compose -f docker-compose.lite.yml exec backend \
  ssh -vvv dnsmanager@<f5-host>

# 2) 检查 F5 上服务
ssh root@<f5-host> "rndc status | head -20"

# 3) 临时绕过：禁用该设备
#    Web UI → 设备管理 → 关闭「启用」
#    或 DB：UPDATE f5_devices SET is_active=false WHERE id=N;
```

### 8.3 场景 3：数据库损坏（Lite）

```bash
# 1) 备份当前（哪怕是坏的）
cp /opt/dns-manager/dns_manager.db /tmp/dns_manager.corrupt.db

# 2) 尝试恢复
docker compose -f docker-compose.lite.yml exec backend \
  sqlite3 /app/data/dns_manager.db ".recover" > /tmp/recover.sql

# 3) 重建数据库
docker compose -f docker-compose.lite.yml stop backend
rm /opt/dns-manager/dns_manager.db
docker compose -f docker-compose.lite.yml up -d backend
docker compose -f docker-compose.lite.yml exec -T backend \
  sqlite3 /app/data/dns_manager.db < /tmp/recover.sql

# 4) 重新 seed 默认账号
docker compose -f docker-compose.lite.yml exec backend python seed.py
```

### 8.4 场景 4：证书过期

```bash
# 1) 查看剩余有效期
echo | openssl s_client -connect localhost:443 2>/dev/null | \
  openssl x509 -noout -dates

# 2) 自签名：重新生成
cd /opt/dns-manager
./generate-certs.sh <server-ip>

# 3) Let's Encrypt：触发续签
certbot renew --force-renewal

# 4) 重启 frontend
docker compose -f docker-compose.lite.yml restart frontend
```

### 8.5 场景 5：误操作回滚

```bash
# Web UI：记录管理 → 选择区域 → 备份历史 → 回滚
# 或 CLI（紧急）：
docker compose -f docker-compose.lite.yml exec backend python -c "
import asyncio
from app.database import async_session_factory
from app.models import ZoneBackup, Zone
from app.services.ssh_connector import ssh_connector
async def t():
    # 找到最近的备份
    async with async_session_factory() as db:
        from sqlalchemy import select
        r = await db.execute(
            select(ZoneBackup).order_by(ZoneBackup.id.desc()).limit(1)
        )
        bk = r.scalar_one()
        # 推回 F5
        await ssh_connector.write_file(bk.zone_id, bk.content)
asyncio.run(t())
"
```

---

## 9. 例行维护任务清单

### 9.1 每日（5 min）

- [ ] 看巡检告警
- [ ] 检查容器状态
- [ ] 检查备份日志：`tail /var/log/dns-manager-backup.log`

### 9.2 每周（30 min）

- [ ] 查 F5 连接测试结果
- [ ] 审查本周审计（异常登录、失败操作）
- [ ] 检查磁盘使用

### 9.3 每月（2 h）

- [ ] 备份异地同步校验
- [ ] 备份恢复演练（任意一个区域）
- [ ] 系统更新：`apt upgrade` + 镜像 rebuild
- [ ] 审查「设备管理」清单是否仍有未用设备
- [ ] 审查「用户管理」是否仍有离职员工账号

### 9.4 每季度（半天）

- [ ] SSL 证书续期（Let's Encrypt 自动，手动 backup）
- [ ] 灾难恢复演练（重建主机 + 恢复备份）
- [ ] 容量规划评审
- [ ] 安全加固清单复核
- [ ] 文档更新（变更同步到 [docs/](.)）

### 9.5 每年（1 天）

- [ ] 升级到下一个 major 版本（评估向后兼容）
- [ ] F5 升级后兼容性验证
- [ ] 完整审计日志归档
- [ ] 用户培训 / 文档刷新

---

## 📎 附录

### 值班联系

| 角色 | 联系方式 |
|------|----------|
| 一线值班 | （填写客户值班电话） |
| 二线开发 | （填写开发团队邮箱） |
| 紧急升级 | （填写 PagerDuty / 飞书值班） |

### 相关文档

- 安装：[INSTALL.md](INSTALL.md)
- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)
- 使用：[USER_GUIDE.md](USER_GUIDE.md)
- 排错：[TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

> **下一步**：建立监控告警后，请填写 §2.3 告警阈值到实际告警系统。