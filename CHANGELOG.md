# CHANGELOG

All notable changes to DNS Zone Manager are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] - 2026-09-30

### 🐛 严重修复

- **删除 zone 会损坏设备上的 named.conf**（会导致 DNS 在下次重载/重启后失效）
  - 根因：`delete_zone` 的正则 `zone "x." {[^}]*};` 在**第一个** `}` 处停止匹配，那其实是内层
    `allow-update { ... };` 的收尾，于是 zone 自身的 `};` 被留成孤儿，文件花括号失衡
  - 危险点：named 仍用内存里的旧配置服务，**表面一切正常**，直到下次 `rndc reconfig` / 重启才暴露
  - 修复：stanza 增删改为**花括号配对扫描**（`find_zone_stanza` / `remove_zone_stanza` / `insert_zone_stanza`），
    建 → 删往返逐字节一致，反复操作不累积空行
- **写 named.conf 增加强制校验与自动回滚**
  - 每次写入后执行 `named-checkconf -t /var/named`（chroot 感知）；校验失败立即从 `.bak` 回滚并抛错，
    坏文件不会被留在设备上
  - 文件后端的演示模式同步实现等价的结构校验与回滚

### 🐛 其他修复

- **删除过的 zone 无法重建**：删除为软删除（`is_active=False`，行保留），重建同名 zone 会触发
  `UNIQUE constraint failed: zones.zone_name`，并以 500 返回——且失败发生在**设备已被修改之后**，
  造成设备与数据库不一致。现在创建前先查重：已存在返回 **409**，命中软删除行则复用并重新激活
- **软删除的 zone 仍出现在列表中**：`GET /api/zones` 现在只返回 `is_active` 的 zone
- **Zone 同步补齐**：设备上仍存在但本地被软删除的 zone 会恢复为可用；`record_count` 变更提示修正为
  变更前后的真实数值（原先打印的是赋值后的同一个值）

### 📚 文档

- `docs/TROUBLESHOOTING.md` 新增 **J. named.conf 安全与数据一致性**：损坏症状、检测命令、回滚步骤、
  F5 由 TMOS 生成 named.conf 的注意事项

---

## [1.0.0] - 2026-09-04

### 🎉 首个正式版本

首个生产可用版本。覆盖 DNS 区域浏览、记录 CRUD、变更审批、审计、设备管理全链路。

### Added（新增）

#### 核心功能
- F5 BIG-IP SSH 直连，零中间层操作 BIND named 配置
- 4 角色 RBAC：`super_admin` / `zone_operator` / `zone_viewer` / `approver`
- 按区域细粒度授权（`user_zone_access` 表 + permissions 数组）
- DNS 区域浏览、记录 CRUD（增 / 改 / 删）
- 变更审批流（申请 → 审批 → 执行 三段式，可关闭）
- 自动 zone 文件备份（每次写操作前），支持一键回滚
- 完整审计日志（登录、查询、变更、审批、系统事件）
- 多 F5 设备管理（Web UI 增删改，运行时加载到 SSH 连接器）

#### 技术特性
- FastAPI + SQLAlchemy 2.0 异步栈
- 前端 Vue 3 + TypeScript + Vite + Element Plus
- Lite / Full 双部署模式（SQLite / PostgreSQL）
- Docker Compose 一键部署
- nginx HTTPS 终止 + 反向代理
- 健康检查（前端 https / 后端 /api/health）
- JWT 认证 + bcrypt 密码哈希
- 自签名 / Let's Encrypt / 商业 CA 证书支持

#### 文档
- README.md（项目门面）
- docs/INSTALL.md（详细安装部署手册）
- docs/ARCHITECTURE.md（架构与扩展点）
- docs/USER_GUIDE.md（用户使用手册）
- docs/OPERATIONS.md（运维手册）
- docs/TROUBLESHOOTING.md（故障排查手册）

#### 交付
- Docker 镜像：backend + frontend（双架构待 v1.1）
- 离线交付包（源码 + 镜像 + 文档 一站式 tar.gz）
- GitHub 公开仓库 + Docker Hub 镜像仓库

### Known Limitations（已知限制）

- 单租户（不支持多组织隔离）
- 不支持 BIND 之外的 DNS 引擎（PowerDNS / Knot 待规划）
- 不内置通知（邮件 / 飞书 / 钉钉 待 v1.1）
- 不内置 LDAP / SAML 认证（v1.1 规划）
- frontend 镜像仅 amd64（arm64 待 v1.1 提供 buildx 多架构）

---

## 版本规划

### [1.1.0] - 计划 2026-Q4

- 内置邮件通知（SMTP）
- 变更窗口限制（按时间窗自动放行 / 拦截）
- CSV 批量导入记录
- 操作回滚 UI 优化（diff 视图）
- 飞书 / 钉钉审批通知 Webhook
- Docker 多架构（amd64 + arm64）

### [1.2.0] - 计划 2027-Q1

- LDAP / OIDC 认证集成
- 多租户（组织隔离）
- RBAC 可视化编辑器
- 操作录制（按键级回放）

### [2.0.0] - 待评估

- Kubernetes Operator
- F5 iControl REST API 支持（替代 SSH）
- 多 DNS 引擎适配器（PowerDNS / Knot / Route 53）

---

## 升级路径

| 当前版本 | 目标版本 | 注意事项 |
|----------|----------|----------|
| 1.0.0 | 1.1.0 | 数据兼容，可直接升级镜像 |
| 1.1.0 | 1.2.0 | 新增 `tenants` 表，需迁移脚本 |
| 1.x | 2.0.0 | 评估中 |

---

[1.0.0]: ../../releases/tag/v1.0.0