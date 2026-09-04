# 故障排查手册（TROUBLESHOOTING.md）

> **版本**：v1.0.0  
> **面向**：全员（用户、运维、开发）  
> **组织方式**：按问题症状分类 → 排查步骤 → 解决方案

---

## 📑 目录

- [A. 部署阶段](#a-部署阶段)
- [B. 启动 / 容器](#b-启动--容器)
- [C. 登录 / 认证](#c-登录--认证)
- [D. Web 访问](#d-web-访问)
- [E. F5 连接](#e-f5-连接)
- [F. DNS 变更操作](#f-dns-变更操作)
- [G. 性能 / 资源](#g-性能--资源)
- [H. 备份 / 恢复](#h-备份--恢复)
- [I. 日志线索速查](#i-日志线索速查)

---

## A. 部署阶段

### A.1 `docker compose up -d` 报错 "permission denied" / "Cannot connect to Docker daemon"

**原因**：当前用户不在 `docker` 组。

**解决**：

```bash
# 临时
sudo docker compose -f docker-compose.lite.yml up -d

# 永久（推荐）
sudo usermod -aG docker $USER
newgrp docker  # 或重新登录
```

---

### A.2 `docker compose build` 时前端 npm install 失败

**症状**：

```
npm ERR! code EAI_AGAIN
npm ERR! errno EAI_AGAIN
```

**原因**：无法访问 npm 官方镜像。

**解决**：

```bash
# 方案 1：配置 npm 国内镜像
mkdir -p ~/.npm
echo 'registry=https://registry.npmmirror.com' > ~/.npmrc

# 方案 2：在项目 frontend/.npmrc 中加入
echo 'registry=https://registry.npmmirror.com' > frontend/.npmrc
docker compose -f docker-compose.lite.yml build frontend

# 方案 3：构建时透传
docker build --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  -f frontend/Dockerfile frontend/
```

---

### A.3 后端 pip install 失败

**症状**：

```
ERROR: Could not find a version that satisfies the requirement ...
```

**解决**：

```bash
# 编辑 backend/Dockerfile，临时切换 pip 源
# 在 pip install 前加：
# RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
# 然后重新 build
```

---

### A.4 生成自签名证书失败

**症状**：`./generate-certs.sh` 报错 openssl 配置缺失。

**解决**：

```bash
# Ubuntu/Debian
sudo apt install openssl

# 验证
openssl version
# 应 >= 1.1.1
```

---

## B. 启动 / 容器

### B.1 容器反复重启（restart 计数 > 5）

```bash
# 看具体错误
docker compose -f docker-compose.lite.yml logs --tail=200 backend
```

**常见原因**：

| 日志关键字 | 原因 | 解决 |
|-----------|------|------|
| `Address already in use` | 80/443 被占用 | `ss -lntp \| grep -E ':(80\|443)'` 找到占用进程，停掉或改端口 |
| `JWT_SECRET is required` | .env 缺失或未生效 | 检查 `.env` 在部署目录根 |
| `database is locked` | SQLite 权限或路径问题 | `ls -la /opt/dns-manager/dns_manager.db` |
| `ModuleNotFoundError: app` | 工作目录错误 | 确保在 docker-compose.yml 同级执行 |
| `Permission denied: /app/keys/` | SSH 密钥权限问题 | `chmod 600 ssh_keys/*` |

---

### B.2 容器显示 `unhealthy`

```bash
# 手动跑健康检查命令
docker compose -f docker-compose.lite.yml exec frontend \
  wget --no-verbose --tries=1 --no-check-certificate --spider https://127.0.0.1/
echo "exit: $?"

docker compose -f docker-compose.lite.yml exec backend \
  curl -sf http://localhost:8000/api/health
echo "exit: $?"
```

**frontend unhealthy 常见原因**：

- 容器内 `localhost` 解析为 IPv6（nginx 只 listen IPv4）→ 健康检查必须用 `https://127.0.0.1/`（已在 v1.0 Dockerfile 修复）
- nginx 配置语法错误 → `docker compose exec frontend nginx -t`
- 证书文件缺失或损坏 → `ls -la /etc/nginx/certs/`

**backend unhealthy 常见原因**：

- 应用启动失败 → 看日志
- 数据库连接失败 → 见 [§C.3](#c3-后端-apihealth-返回-503)
- 端口未监听 → `docker compose exec backend netstat -lntp`

---

### B.3 容器无法访问 F5

```bash
# 测试出站连通性
docker compose -f docker-compose.lite.yml exec backend \
  ping -c 3 <f5-host>

# 测试 SSH
docker compose -f docker-compose.lite.yml exec backend \
  ssh -vvv dnsmanager@<f5-host> 'echo OK'
```

如果 SSH 失败，检查：

1. F5 上 SSH 服务是否开启
2. F5 防火墙是否允许 22 入站
3. 本机出口 IP 是否被 F5 ACL 限制
4. 私钥权限：`docker compose exec backend ls -la /app/keys/`

---

## C. 登录 / 认证

### C.1 登录返回 401

```bash
# 手动测试
curl -sk -X POST https://localhost/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```

**排查**：

1. **用户名密码错误**：确认大小写、特殊字符
2. **JWT_SECRET 不一致**：重启后 JWT 解码失败 → 检查 `.env` 是否与之前一致
3. **用户被禁用**：DB 中 `users.is_active=false`

### C.2 登录后立刻掉线

**症状**：登录成功，但刷新页面提示「请重新登录」。

**排查**：

1. 浏览器 DevTools → Application → Local Storage → 检查 token 是否被存储
2. 检查前端 axios 拦截器（`frontend/src/api/index.ts`）

### C.3 后端 `/api/health` 返回 503

```bash
curl -sk https://localhost/api/health
```

可能响应：

```json
{"status": "error", "detail": "F5 SSH not initialized"}
```

**排查**：

1. F5 是否可达（[§B.3](#b3-容器无法访问-f5)）
2. SSH 密钥是否挂载：

   ```bash
   docker compose -f docker-compose.lite.yml exec backend ls -la /app/keys/
   # 应该能看到你的私钥文件
   ```

3. 数据库是否可写：

   ```bash
   docker compose -f docker-compose.lite.yml exec backend \
     sqlite3 /app/data/dns_manager.db "SELECT COUNT(*) FROM users;"
   ```

---

### C.4 忘记 admin 密码

参见 [USER_GUIDE §Q4](USER_GUIDE.md#q4忘记了-admin-密码)。

---

## D. Web 访问

### D.1 浏览器提示「您的连接不是私密连接」

**原因**：自签名证书未被信任。

**生产环境**：使用正式 CA 签发证书（参见 [INSTALL §6](INSTALL.md#6-ssl-证书配置)）。

**PoC / 内网**：

- Chrome：地址栏输入 `thisisunsafe`（注意：在错误页面上直接键盘输入，不点鼠标）
- Firefox：高级 → 接受风险并继续

### D.2 页面无限 502 / 504

```bash
# 看 frontend nginx 错误日志
docker compose -f docker-compose.lite.yml logs frontend --tail=50
```

常见：

- `connect() failed (111: Connection refused) while connecting to backend` → backend 容器没启动
- `upstream timed out` → backend 响应慢 → 检查 [§G](#g-性能--资源)

### D.3 静态资源 404

**症状**：页面布局乱了，CSS/JS 加载失败。

**排查**：

```bash
# 检查 frontend 容器内 dist 是否存在
docker compose -f docker-compose.lite.yml exec frontend ls -la /usr/share/nginx/html/
# 应有 assets/ 目录与 index.html
```

如缺失 → 重新 build：`docker compose build frontend && docker compose up -d frontend`

### D.4 HTTPS 重定向循环

**症状**：浏览器 ERR_TOO_MANY_REDIRECTS。

**原因**：nginx 同时 listen 80 和 443，强制跳转 https，但客户端访问的是 https。

**排查**：`frontend/nginx-docker.conf` 中是否有错误的双重跳转。

---

## E. F5 连接

### E.1 SSH 认证失败

```bash
# 详细日志
docker compose -f docker-compose.lite.yml exec backend \
  python -c "
import asyncio, logging
logging.basicConfig(level=logging.DEBUG)
from app.services.ssh_connector import ssh_connector
async def t():
    for did in ssh_connector._devices:
        ok, msg = await ssh_connector.test_connection(did)
        print(f'[{did}] {ok}: {msg}')
asyncio.run(t())
"
```

**常见**：

| 错误 | 解决 |
|------|------|
| `Permission denied (publickey)` | 检查 `~/.ssh/authorized_keys`、私钥路径 |
| `Permission denied (password)` | F5 禁用了密码登录 → 改用密钥 |
| `No such file or directory` | 私钥文件不存在于容器内 `/app/keys/` |
| `Bad passphrase` | `F5_SSH_KEY_PASSPHRASE` 未设置 |

### E.2 设备「已加载」但同步区域列表为空

```bash
# 看 SSH 是否能读取 named.conf
docker compose -f docker-compose.lite.yml exec backend \
  ssh dnsmanager@<f5-host> 'cat /var/named/config/named.conf'
```

**可能**：

- 路径不对：`F5_NAMED_CONF` 与实际不一致
- 用户权限不足：无 `cat` 权限
- named.conf 中无 zone 定义

### E.3 多个 F5 设备时切换缓慢

**原因**：SSH 长连接未复用。

**解决**：

1. 检查 `app/services/ssh_connector.py` 中连接池逻辑
2. 升级到 v1.1+（[CHANGELOG](../CHANGELOG.md)）

---

## F. DNS 变更操作

### F.1 提交变更一直「待审批」

1. 进入「变更申请」→ 「待审批」看是否真有人待审批
2. 检查是否有 approver 账号存在且启用
3. 看 `change_requests` 表状态

### F.2 审批通过后执行失败

```bash
# 看后端日志关键字
docker compose -f docker-compose.lite.yml logs backend --tail=200 | \
  grep -E "execute|FAILED|rndc|change_request"
```

| 错误信息 | 原因 | 解决 |
|----------|------|------|
| `rndc: connect failed` | rndc 套接字权限或路径问题 | F5 上 `ls -la /var/named/config/rndc.key` |
| `Permission denied` | ssh 用户无写权限 | F5 上 `chmod a+w /var/named/config/namedb/` |
| `No space left on device` | F5 磁盘满 | F5 上 `df -h` |
| `rndc: reload failed: permission denied` | rndc.key 权限 | F5 上 `chmod a+r /var/named/config/rndc.key` |

### F.3 SOA serial 未自动增加

**原因**：zone 文件中 SOA serial 行格式不规范。

**排查**：

```bash
ssh dnsmanager@<f5-host> \
  'grep SOA /var/named/config/namedb/db.external.ppv2.com.'
# 应为：@ IN SOA ns1.ppv2.com. admin.ppv2.com. 2026090401 3600 1800 604800 3600
# serial 格式 YYYYMMDDnn
```

若格式错误，手工修正或联系实施工程师。

---

## G. 性能 / 资源

### G.1 内存占用高

```bash
docker stats --no-stream
```

**优化**：

1. SQLite 缓存调小：`PRAGMA cache_size=-32000;`（32MB）
2. backend worker 数减少：`--workers 1`
3. 切到 Full 模式 + 单独 Postgres 容器

### G.2 磁盘增长快

```bash
du -sh /opt/dns-manager/* | sort -h | tail
```

**常见大文件**：

- `backups/` 备份堆积 → 调整保留策略
- `zone_backups` 表过大 → 清理 90 天前的备份
- nginx access log → 检查 `/etc/docker/daemon.json` log-opts

### G.3 API 响应慢

```bash
# 看具体慢在哪
curl -sk -w "Time: %{time_total}s\n" -o /dev/null \
  https://localhost/api/zones
```

**排查**：

1. **DB 查询慢**：开启 SQLite `.timer`，看慢查询
2. **F5 SSH 慢**：`time ssh dnsmanager@<f5-host> 'rndc status'`
3. **网络丢包**：`mtr <f5-host>`

---

## H. 备份 / 恢复

### H.1 备份脚本失败

```bash
# 看具体错误
bash -x scripts/backup.sh 2>&1 | tail -50
```

常见：

- SQLite 数据库被锁 → 改用 `.backup` 命令（已在脚本中）
- F5 SSH 失败 → 检查密钥
- 磁盘满 → 检查 `df -h`

### H.2 恢复后无法登录

**原因**：恢复的 SQLite 不包含用户表。

**解决**：

```bash
docker compose -f docker-compose.lite.yml exec backend python seed.py
# 会创建默认账号但不会覆盖已有
```

### H.3 备份数据不完整

**症状**：备份能跑，但内容明显偏少。

**排查**：

```bash
docker compose -f docker-compose.lite.yml exec -T backend \
  sqlite3 /app/data/dns_manager.db ".dump" | wc -l
# 应 > 1000（含 schema + data）
```

---

## I. 日志线索速查

| 关键字 | 含义 |
|--------|------|
| `ERROR` | 应用错误，需查 `traceback` |
| `WARNING.*ssh` | SSH 重连或异常关闭 |
| `rndc.*permission` | F5 权限问题 |
| `JWT.*expired` | 客户端 token 过期（正常） |
| `F5.*unreachable` | F5 网络问题 |
| `IntegrityError` | 数据库唯一约束冲突 |
| `OperationalError.*database is locked` | SQLite 写锁（高并发） |
| `change_request.*failed` | 变更执行失败，看 detail |
| `audit.*write_failed` | 审计写入失败（通常因 DB 故障） |

**获取完整 traceback**：

```bash
docker compose -f docker-compose.lite.yml logs backend --tail=1000 | \
  grep -A 30 "Traceback"
```

---

## 📞 仍然无法解决？

1. 收集以下信息提交 Issue：
   - 完整错误日志（`docker compose logs > all.log`）
   - `.env`（脱敏后的）
   - 复现步骤
   - 期望 vs 实际

2. 紧急情况联系运维值班。

3. 已知问题列表：[GitHub Issues](../../issues)

---

> **下一步**：排查后请把解决方案补充到本手册，帮助后来人。