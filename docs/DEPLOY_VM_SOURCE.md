# DNS Zone Manager — 虚拟机（无 Docker）源码部署实录

> 目标服务器：`203.195.200.100`（腾讯云 CVM，Ubuntu 24.04.4 LTS，x86_64，2C4G，用户 `ubuntu`）
> 部署日期：2026-09-27　|　源码：`https://github.com/q2807c/dns-manager.git`（main 分支）
> 模式：**纯虚拟机直接运行，不使用 Docker**。后端 systemd + uvicorn，前端系统 nginx 托管构建产物，数据库 SQLite（无需 MySQL/PostgreSQL）。

---

## 1. 环境准备

| 项 | 版本 / 说明 |
|----|-------------|
| OS | Ubuntu 24.04.4 LTS（x86_64） |
| Python | 3.12.3（系统自带） |
| Node.js / npm | v18.19.1 / 9.2.0（apt 安装，满足 Vite 5 要求 ≥18） |
| nginx | 1.24.0（apt 安装） |
| git | 2.43.0 |
| 磁盘 | 40G（清理 Docker 后回收约 1.2GB） |

依赖安装：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip nginx nodejs npm
```

> Lite 模式默认使用 SQLite，**不需要安装 MySQL**；如后续切换 Full 模式（PostgreSQL），配置文件已预留参数。

## 2. 清理前的数据备份

清理前盘点结论：数据库为上线日初始化库（57KB，无增量业务数据），`ssh_keys/`、`backups/` 均为空，F5 连接为占位值。有保留价值的仅为 `.env` 与自签名证书。

```bash
# 备份 .env + SQLite 数据库
sudo tar czf /home/ubuntu/dns-manager-backup-20260927.tar.gz \
  -C /home/ubuntu/dns-manager .env \
  -C /var/lib/docker/volumes/dns-manager_db_data/_data dns_manager.db

# 备份 HTTPS 证书
sudo tar czf /home/ubuntu/dns-manager-certs-backup-20260927.tar.gz \
  -C /home/ubuntu/dns-manager nginx/certs
```

备份位置：`/home/ubuntu/dns-manager-backup-20260927.tar.gz`、`/home/ubuntu/dns-manager-certs-backup-20260927.tar.gz`（root 属主）。

## 3. 彻底清除 Docker 部署

```bash
cd /home/ubuntu/dns-manager
sudo docker compose -f docker-compose.lite.yml down --volumes --rmi all --remove-orphans
sudo docker rmi -f $(sudo docker images -aq)      # 删除全部镜像
sudo docker system prune -af --volumes            # 清理残余（本次回收 1.209GB）

# 验证清空
sudo docker images        # 空
sudo docker ps -a         # 空
sudo docker volume ls     # 空
sudo docker network ls    # 仅剩引擎内置 bridge/host/none

# 禁用 Docker 服务（纯 VM 运行不再需要）
sudo systemctl disable --now docker docker.socket containerd
```

验证：`systemctl is-active docker` → `inactive`，`docker images` 报 daemon 未运行。

## 4. 获取源码与配置

```bash
mv /home/ubuntu/dns-manager /home/ubuntu/dns-manager.bak-20260927   # 旧目录保留
git clone --depth 1 https://github.com/q2807c/dns-manager.git /home/ubuntu/dns-manager
cd /home/ubuntu/dns-manager

# 生成 .env
cp .env.example .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# VM 路径适配（与 Docker 版的关键差异）
sed -i "s|^SQLITE_DB_PATH=.*|SQLITE_DB_PATH=/home/ubuntu/dns-manager/backend/data/dns_manager.db|" .env
sed -i "s|^F5_SSH_KEY_PATH=.*|F5_SSH_KEY_PATH=/home/ubuntu/dns-manager/ssh_keys/id_ed25519|" .env
sed -i "s|^APP_HOST=.*|APP_HOST=127.0.0.1|" .env
mkdir -p backend/data ssh_keys backups

# 恢复 HTTPS 证书（沿用旧证书，浏览器无需重新信任）
sudo tar xzf /home/ubuntu/dns-manager-certs-backup-20260927.tar.gz -C .
sudo chown -R ubuntu:ubuntu nginx/certs
```

## 5. 后端部署（venv + systemd + uvicorn）

```bash
cd /home/ubuntu/dns-manager/backend
python3 -m venv venv
./venv/bin/pip install -U pip -i https://mirrors.cloud.tencent.com/pypi/simple
./venv/bin/pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
```

新增 `backend/init_db.py`（与 `entrypoint.sh` 逻辑等价：建表 + 无用户时执行 `seed.py`），文件内容见仓库。

systemd 服务 `/etc/systemd/system/dns-backend.service`：

```ini
[Unit]
Description=DNS Zone Manager Backend (FastAPI + uvicorn)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/dns-manager/backend
EnvironmentFile=/home/ubuntu/dns-manager/.env
ExecStartPre=/home/ubuntu/dns-manager/backend/venv/bin/python /home/ubuntu/dns-manager/backend/init_db.py
ExecStart=/home/ubuntu/dns-manager/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dns-backend
```

> 后端只监听 `127.0.0.1:8000`，外部流量统一经 nginx 443 进入。

## 6. 前端构建（Vite）

```bash
cd /home/ubuntu/dns-manager/frontend
npm install --registry=https://registry.npmmirror.com --no-audit --no-fund
npm run build        # 产物在 frontend/dist/，实测 13s
```

## 7. 系统级 nginx 配置

1. 证书安装：`sudo cp nginx/certs/server.{crt,key} /etc/nginx/certs/ && sudo chmod 600 /etc/nginx/certs/server.key`
2. 配置 `/etc/nginx/nginx.conf`（由 `frontend/nginx-docker.conf` 改写，关键差异）：

```nginx
upstream dns_backend { server 127.0.0.1:8000; }        # 原 backend:8000 → 本机
root /home/ubuntu/dns-manager/frontend/dist;           # 原 /usr/share/nginx/html → 源码构建产物

server {
    listen 443 ssl http2;                              # 注意写法，见问题 1
    ssl_certificate     /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;
    location /api/ { proxy_pass http://dns_backend; ... }
    location /   { try_files $uri $uri/ /index.html; }  # SPA fallback
}
server { listen 80; return 301 https://$host$request_uri; }
```

3. 启用：

```bash
sudo rm -f /etc/nginx/sites-enabled/default   # 移除默认站点，避免 80 端口冲突
sudo nginx -t && sudo systemctl restart nginx
```

## 8. 过程中遇到的问题与解决办法

| # | 问题 | 原因 | 解决 |
|---|------|------|------|
| 1 | `nginx -t` 报 `unknown directive "http2"` | 仓库配置用了 nginx 1.25+ 的独立 `http2 on;` 指令，Ubuntu 24.04 自带 nginx 1.24 不支持 | 改回旧语法 `listen 443 ssl http2;` 并删除独立指令行 |
| 2 | 前端页面 403，API 正常 | nginx worker 以 `www-data` 运行，`/home/ubuntu` 权限 750 无法穿越 | `chmod o+x /home/ubuntu`（仅放开穿越位，文件权限不变） |
| 3 | 80/443 未监听 | 替换 nginx.conf 后只执行了 `enable --now`，未重启已运行的 nginx | `systemctl restart nginx` 后恢复 |
| 4 | `nginx -t` 失败导致后端服务未被启用 | 链式命令中 `&&` 短路 | 单独执行 `systemctl enable --now dns-backend` |
| 5 | `sites-enabled/default` 占用 80 端口 | apt 安装的 nginx 自带默认站点 | 直接替换整个 `/etc/nginx/nginx.conf` 且不 include sites-enabled，并删除 default 软链 |
| 6 | 手动部署常见隐患（前人反馈） | 多为：未生成证书（nginx 起不来）、`.env` 缺失或 `JWT_SECRET` 保留默认值、Node 版本低于 18、80/443 被占用、Docker 版配置直接套用到系统 nginx（`backend:8000` 主机名不存在） | 本文档第 4/7 步已逐一规避 |

## 9. 部署验证结果（2026-09-27）

| 检查项 | 命令 | 结果 |
|--------|------|------|
| 后端服务 | `systemctl is-active dns-backend` | `active`（uvicorn 监听 127.0.0.1:8000） |
| nginx 服务 | `systemctl is-active nginx` | `active`（监听 80/443） |
| 后端健康 | `curl http://127.0.0.1:8000/api/health` | `{"status":"ok","version":"0.2.0",...}` |
| 经代理健康 | `curl -sk https://127.0.0.1/api/health` | `{"status":"ok","version":"0.2.0","configured_devices":1}` |
| 前端首页 | `curl -sk https://127.0.0.1/` | HTTP 200，返回 SPA HTML |
| SPA 路由回退 | `curl -sk https://127.0.0.1/zones` | HTTP 200 |
| 登录接口 | `POST /api/auth/login`（admin/admin123） | 返回 `access_token` ✓ |
| 外网访问 | `curl https://203.195.200.100/` | HTTP 200（0.20s） |
| 外网 API | `curl https://203.195.200.100/api/health` | `{"status":"ok",...}` |
| HTTP 跳转 | `curl http://203.195.200.100/` | 301 → https |
| Docker 清理 | `docker images / ps -a / volume ls` | 全空；docker/containerd 服务 `inactive` |

## 10. 日常运维（对比 Docker 版）

```bash
systemctl status|restart|stop dns-backend     # 后端（失败自动拉起 Restart=always）
systemctl status|restart|reload nginx         # 前端入口
tail -f /var/log/nginx/error.log              # nginx 日志
journalctl -u dns-backend -f                  # 后端日志
# 前端更新：git pull 后在 frontend/ 重跑 npm run build，无需重启任何服务
# 后端更新：git pull 后在 backend/ 重跑 pip install -r requirements.txt，systemctl restart dns-backend
# 数据库：/home/ubuntu/dns-manager/backend/data/dns_manager.db（SQLite，直接 cp 即为备份）
```

## 11. 遗留事项

1. **F5 连接仍为占位值**（`F5_ACTIVE_HOST=172.18.1.202`）：接入真实 F5 时修改 `/home/ubuntu/dns-manager/.env` 后 `sudo systemctl restart dns-backend`，或将 SSH 私钥放至 `ssh_keys/id_ed25519`。
2. **默认账号 admin/admin123**，首次登录后立即改密。
3. Docker 引擎已停用但未卸载；如需彻底移除：`sudo apt-get purge docker-ce docker-ce-cli containerd.io && sudo rm -rf /var/lib/docker`。
4. 清理前数据备份在 `/home/ubuntu/dns-manager-{,certs-}backup-20260927.tar.gz`，确认无需后可删除；旧目录备份 `/home/ubuntu/dns-manager.bak-20260927/`。
