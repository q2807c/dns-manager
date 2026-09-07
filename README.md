# DNS Zone Manager

> **F5 BIG-IP DNS 区域管理平台** —— 通过 SSH 操作 F5 上的 BIND named 配置，提供 Web 化、可审计、可审批的 DNS 记录管理能力。

[![Backend](https://img.shields.io/badge/backend-FastAPI-009688)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/frontend-Vue3%20%2B%20TypeScript-42b883)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed)](https://www.docker.com/)
[![Docker Pulls](https://img.shields.io/docker/pulls/q2807c/dns-manager-backend?label=backend%20pulls)](https://hub.docker.com/r/q2807c/dns-manager-backend)
[![Docker Pulls](https://img.shields.io/docker/pulls/q2807c/dns-manager-frontend?label=frontend%20pulls)](https://hub.docker.com/r/q2807c/dns-manager-frontend)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

---

## ✨ 核心特性

- 🎯 **直连 F5 BIG-IP**：通过 SSH 操作 F5 上的 BIND `named.conf` 与 zone 文件，零中间层
- 🔐 **四角色权限模型**：`super_admin` / `zone_operator` / `zone_viewer` / `approver`，按区域细粒度授权
- 📋 **变更审批流**：所有写操作（新增 / 修改 / 删除记录）走「申请 → 审批 → 执行」三段式，可关闭审批加速环境
- 🗂️ **多设备 / 多区域**：支持管理多个 F5 设备，每个设备的 DNS 区域独立隔离
- 💾 **版本化备份**：每次写操作自动备份 zone 文件，支持一键回滚
- 📜 **完整审计**：所有用户行为（登录、查询、变更、审批）落库可追溯
- 🐳 **容器化交付**：单条 `docker compose up -d` 即可上线，无外部依赖（Lite 模式）
- 🚀 **零停机**：前端 nginx + 后端 FastAPI 双容器，支持滚动升级

---

## 📦 快速开始（5 分钟跑起来）

### 方式一：拉取预构建镜像（推荐，无需源码）

```bash
# 1. 准备环境变量（生成强随机 JWT 密钥）
cp .env.example .env
sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# 2. 生成自签名证书（替换 your-server-ip 为实际域名或 IP）
./generate-certs.sh your-server-ip

# 3. 拉镜像并启动（Lite 模式：SQLite + 单机双容器）
docker pull q2807c/dns-manager-backend:v1.0.0
docker pull q2807c/dns-manager-frontend:v1.0.0
docker compose -f docker-compose.lite.yml up -d

# 4. 访问
open https://your-server-ip/
# 默认账号: admin / admin123  (⚠️ 首次登录后立即修改)
```

> 预构建镜像为 **linux/amd64**（对应生产服务器主流架构）。离线环境可下载 Release 中的
> `dns-manager-images-v1.0.0.tar`，用 `docker load -i` 导入。

### 方式二：从源码构建

```bash
# 1. 克隆代码
git clone https://github.com/q2807c/dns-manager.git
cd dns-manager

# 2. 准备环境变量（生成强随机 JWT 密钥）
cp .env.example .env
sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env

# 3. 生成自签名证书（替换 example.com 为实际域名或 IP）
./generate-certs.sh your-server-ip-or-domain

# 4. 构建并启动（Lite 模式：SQLite + 单机双容器）
docker compose -f docker-compose.lite.yml up -d --build

# 5. 访问
open https://your-server-ip/
# 默认账号: admin / admin123  (⚠️ 首次登录后立即修改)
```

完整安装流程见 [docs/INSTALL.md](docs/INSTALL.md)。

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│ 浏览器（https://your-host/）                                │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS
                         ▼
              ┌──────────────────────┐
              │  nginx (容器)        │  ← 静态前端 + 反向代理 /api
              │  frontend container  │
              └──────────┬───────────┘
                         │ :8000
                         ▼
              ┌──────────────────────┐         ┌─────────────┐
              │  FastAPI (容器)      │  SSH   │ F5 BIG-IP   │
              │  backend container   │ ──────▶│ (BIND named) │
              │  - SQLAlchemy        │         └─────────────┘
              │  - SSH Connector     │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │ SQLite / PostgreSQL  │
              │ (卷挂载 / 独立库)    │
              └──────────────────────┘
```

详细架构、数据模型、扩展点见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 🖥️ 界面预览

| 登录 | 区域列表 | 记录管理 |
|------|----------|----------|
| ![](docs/screenshots/login.png) | ![](docs/screenshots/zones.png) | ![](docs/screenshots/records.png) |

> 截图待补：首次 `npm run build` 后通过前端界面截图填充。

---

## 📚 文档索引

| 文档 | 面向 | 说明 |
|------|------|------|
| [docs/INSTALL.md](docs/INSTALL.md) | 部署 / 运维 | 安装、升级、配置 SSL、备份恢复 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 开发 / 架构师 | 技术栈、模块划分、数据模型、API 设计 |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 最终用户 | 日常使用、变更审批、审计查询 |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 运维 | 监控、日志、扩容、应急响应 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 全员 | 常见问题与排查思路 |
| [CHANGELOG.md](CHANGELOG.md) | 全员 | 版本变更记录 |
| [DEPLOY.md](DEPLOY.md) | 部署 | 简版快速部署指引（保留历史） |

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia |
| 后端 | FastAPI + SQLAlchemy 2.0 (async) + Paramiko + APScheduler |
| 数据库 | SQLite (Lite 模式) / PostgreSQL 15 (Full 模式) |
| 反向代理 | nginx (TLS termination + static + reverse proxy) |
| 部署 | Docker Compose |
| CI/CD | 待接入 |

---

## 🤝 贡献

内部项目，欢迎提交 Issue 与 PR。提交前请阅读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 了解模块划分。

---

## 📄 许可证

[MIT](./LICENSE) — 可商用、可修改，需保留版权信息。

---

## 📞 联系方式

- **Issue**：本仓库 GitHub Issues
- **运维**：参见 [docs/OPERATIONS.md](docs/OPERATIONS.md) 末尾的值班信息

---

<div align="center">
<sub>v1.0.0 · 上线日期 2026-09 · 适配 F5 BIG-IP 13.x / 14.x / 15.x / 16.x</sub>
</div>