# DNS Zone Manager — 虚拟机（无 Docker）安装命令速查

> 纯虚拟机直接运行，不使用任何容器。后端 systemd + uvicorn，前端系统 nginx，数据库 SQLite（无需 MySQL）。
> 环境：Ubuntu 24.04（x86_64），Python 3.12+，Node.js ≥18，nginx 1.24+。
> 完整背景与排障记录见 `docs/DEPLOY_VM_SOURCE.md`。

## 1. 安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip nginx nodejs npm git
```

## 2. 获取源码并配置

```bash
git clone https://github.com/q2807c/dns-manager.git /home/ubuntu/dns-manager
cd /home/ubuntu/dns-manager

# 生成 .env
cp .env.example .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# VM 路径适配
sed -i "s|^SQLITE_DB_PATH=.*|SQLITE_DB_PATH=/home/ubuntu/dns-manager/backend/data/dns_manager.db|" .env
sed -i "s|^F5_SSH_KEY_PATH=.*|F5_SSH_KEY_PATH=/home/ubuntu/dns-manager/ssh_keys/id_ed25519|" .env
sed -i "s|^APP_HOST=.*|APP_HOST=127.0.0.1|" .env
mkdir -p backend/data ssh_keys backups

# F5 连接信息（按实际环境修改）
#   F5_ACTIVE_HOST / F5_SSH_USER / F5_SSH_PASSWORD
#   或将 SSH 私钥放置到 ssh_keys/id_ed25519
```

## 3. 生成 HTTPS 证书

```bash
./generate-certs.sh <服务器IP或域名>     # 自签名；有正式证书则放到 nginx/certs/
```

## 4. 部署后端（venv + systemd）

```bash
cd /home/ubuntu/dns-manager/backend
python3 -m venv venv
./venv/bin/pip install -U pip -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
```

安装 systemd 服务（模板在仓库 `deploy-vm/dns-backend.service`）：

```bash
sudo cp /home/ubuntu/dns-manager/deploy-vm/dns-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dns-backend
```

## 5. 构建前端

```bash
cd /home/ubuntu/dns-manager/frontend
npm install --registry=https://registry.npmmirror.com --no-audit --no-fund
npm run build        # 产物在 frontend/dist/
```

## 6. 配置系统 nginx

```bash
# 证书
sudo mkdir -p /etc/nginx/certs
sudo cp /home/ubuntu/dns-manager/nginx/certs/server.crt /home/ubuntu/dns-manager/nginx/certs/server.key /etc/nginx/certs/
sudo chmod 600 /etc/nginx/certs/server.key

# 配置文件（模板在仓库 deploy-vm/nginx-vm.conf：TLS 443 + SPA 回退 + 反代 /api 到 127.0.0.1:8000）
sudo cp /home/ubuntu/dns-manager/deploy-vm/nginx-vm.conf /etc/nginx/nginx.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

## 7. 验证

```bash
systemctl is-active dns-backend nginx              # 均应为 active
curl -s http://127.0.0.1:8000/api/health           # {"status":"ok",...}
curl -sk https://127.0.0.1/api/health              # 经 nginx 反代
curl -sk -o /dev/null -w "%{http_code}\n" https://127.0.0.1/   # 200
curl -sk -X POST https://127.0.0.1/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'  # 返回 access_token
```

浏览器访问 `https://<服务器IP>/`，默认账号 `admin / admin123`，**首次登录后立即改密**。

## 8. 日常运维

```bash
systemctl status|restart|stop dns-backend    # 后端（Restart=always，失败自动拉起）
systemctl status|restart|reload nginx        # 前端入口
journalctl -u dns-backend -f                 # 后端日志
tail -f /var/log/nginx/error.log             # nginx 日志

# 升级：git pull 后
#   后端有依赖变更 → backend/ 下 pip install -r requirements.txt，再 systemctl restart dns-backend
#   前端有变更 → frontend/ 下 npm run build（无需重启服务）

# 备份：直接拷贝 SQLite 文件
cp /home/ubuntu/dns-manager/backend/data/dns_manager.db /backup/path/
```

## 9. 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `nginx -t` 报 `unknown directive "http2"` | 用了 1.25+ 的 `http2 on;` 独立指令 | 仓库模板已用 `listen 443 ssl http2;` 旧语法，确认配置来自 `deploy-vm/nginx-vm.conf` |
| 前端 403，API 正常 | nginx worker 无法穿越 `/home/ubuntu`（750） | `chmod o+x /home/ubuntu` |
| 80/443 未监听 | 替换配置后未重启 nginx | `sudo systemctl restart nginx` |
| 80 端口被占 | apt 版 nginx 自带 default 站点 | `sudo rm -f /etc/nginx/sites-enabled/default` 后重启 |
| 接口偶发全部超时 | 旧版本 SSH 调用阻塞事件循环 | 升级到 v1.0.1+（commit `0a87e6d`）已修复 |
| 添加设备后"测试"报错 | 现在会返回真实原因（如 F5 tmsh 受限 shell） | 按提示将设备账号 shell 设为 bash，或检查 `.env`/设备记录中的 key_path |
