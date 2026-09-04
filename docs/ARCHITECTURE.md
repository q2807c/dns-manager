# 架构设计文档（ARCHITECTURE.md）

> **版本**：v1.0.0  
> **面向**：开发工程师、架构师、Code Reviewer  
> **目标**：理解模块划分、数据流、扩展点、二次开发边界

---

## 📑 目录

1. [设计原则](#1-设计原则)
2. [技术栈选型](#2-技术栈选型)
3. [系统拓扑](#3-系统拓扑)
4. [模块划分](#4-模块划分)
5. [数据模型](#5-数据模型)
6. [API 设计规范](#6-api-设计规范)
7. [核心流程](#7-核心流程)
8. [安全模型](#8-安全模型)
9. [扩展点](#9-扩展点)
10. [二次开发指引](#10-二次开发指引)

---

## 1. 设计原则

| 原则 | 落地方式 |
|------|----------|
| **直连 F5，零中间层** | SSH 直连 BIND 文件，无 DNS API 中转，配置即所得 |
| **容器化一等公民** | 所有交付物都是镜像，无 host-level 依赖 |
| **数据与行为可审计** | 所有写操作生成 `AuditLog` 与 `ZoneBackup` 双记录 |
| **变更可审批** | 默认所有写操作走「申请 → 审批 → 执行」，可关闭 |
| **渐进式复杂度** | Lite 模式 5 分钟上线，Full / K8s 渐进引入 |

---

## 2. 技术栈选型

### 2.1 前端

| 技术 | 用途 | 理由 |
|------|------|------|
| Vue 3 + Composition API | 视图层 | 上手快、生态成熟 |
| TypeScript | 类型 | 后端 Pydantic schema 可直接复用 |
| Vite | 构建 | 启动快、HMR 体验好 |
| Element Plus | UI 组件 | 国内运维友好、中文文档 |
| Pinia | 状态管理 | 替代 Vuex，TS 友好 |
| Vue Router | 路由 | 标配 |
| Axios | HTTP | 拦截器统一处理 JWT |

### 2.2 后端

| 技术 | 用途 | 理由 |
|------|------|------|
| FastAPI | Web 框架 | 异步、自动 OpenAPI、Pydantic 集成 |
| SQLAlchemy 2.0 (async) | ORM | 异步生态成熟、迁移工具完善 |
| Paramiko | SSH 客户端 | Python 原生、F5 SSH 兼容性好 |
| APScheduler | 定时任务 | 备份轮转、证书续签 |
| python-jose | JWT | 签名与校验 |
| passlib[bcrypt] | 密码哈希 | 抗彩虹表 |
| Pydantic v2 | 数据校验 | 性能 + 5x |

### 2.3 基础设施

| 技术 | 用途 |
|------|------|
| SQLite 3 | Lite 模式数据库（卷挂载） |
| PostgreSQL 15 | Full 模式数据库 |
| Redis 7 | 预留：任务队列、限流（当前未启用） |
| nginx 1.25 | 反向代理 + TLS 终止 + 静态托管 |
| Docker 24+ | 容器运行时 |
| Docker Compose v2 | 编排 |

---

## 3. 系统拓扑

### 3.1 容器视图

```
┌────────────────────────────────────────────────────────────┐
│ Host: 部署主机 (Ubuntu 24.04 / CentOS 8+)                  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ docker-compose.lite.yml                              │ │
│  │                                                      │ │
│  │  ┌────────────────┐         ┌────────────────────┐   │ │
│  │  │ dns-frontend   │ :80/443 │  dns-backend       │   │ │
│  │  │ (nginx 1.25)   │ ──────▶ │  (FastAPI / uvicorn)│   │ │
│  │  │                │  /api/* │  :8000              │   │ │
│  │  └────────────────┘         └──────────┬──────────┘   │ │
│  │                                        │              │ │
│  │                                        ▼              │ │
│  │                              ┌──────────────────┐     │ │
│  │                              │ SQLite 卷        │     │ │
│  │                              │ dns_manager_db   │     │ │
│  │                              └──────────────────┘     │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  F5 BIG-IP ◀──── SSH :22 ────── backend 容器               │
└────────────────────────────────────────────────────────────┘
```

### 3.2 网络流

| 阶段 | 数据 |
|------|------|
| 用户 → frontend | HTTPS:443（TLS 终止在 nginx） |
| frontend → backend | HTTP:8000（容器内网，nginx 反向代理 `/api/*`） |
| backend → F5 | SSH:22（Paramiko 长连接，per-device 单连接复用） |
| backend → DB | Unix Socket (SQLite) / TCP:5432 (Postgres) |

---

## 4. 模块划分

### 4.1 后端模块树

```
backend/app/
├── main.py              # FastAPI 入口，路由注册、生命周期
├── config.py            # Pydantic Settings，从 .env 读取
├── database.py          # SQLAlchemy async engine + session factory
├── core/
│   └── auth.py          # JWT 签发 / 校验 / 密码哈希 / 依赖注入
├── models/
│   └── __init__.py      # 7 张表的 SQLAlchemy ORM 定义
├── schemas/
│   └── __init__.py      # Pydantic 请求 / 响应模型（与 ORM 解耦）
├── api/
│   ├── __init__.py
│   └── routes/
│       ├── auth.py            # POST /auth/login, /auth/me
│       ├── users.py           # 用户 CRUD
│       ├── devices.py         # F5 设备 CRUD
│       ├── zones.py           # DNS 区域 CRUD + 同步
│       ├── records.py         # DNS 记录 CRUD
│       ├── change_requests.py # 变更申请 / 审批 / 执行
│       └── audit.py           # 审计日志查询
└── services/
    ├── ssh_connector.py  # SSH 连接池，per-device 单连接
    ├── zone_parser.py    # BIND zone 文件解析 / 序列化
    └── backup_service.py # 备份生成 / 轮转 / 恢复
```

### 4.2 前端模块树

```
frontend/src/
├── main.ts              # Vue 入口
├── App.vue              # 根组件
├── router/
│   └── index.ts         # 路由表 + 权限守卫
├── stores/              # Pinia stores
│   ├── auth.ts          # 当前用户、token
│   ├── devices.ts       # F5 设备列表
│   ├── zones.ts         # 区域列表
│   └── ui.ts            # 全局 UI 状态（侧边栏折叠等）
├── views/               # 页面级组件
│   ├── Login.vue
│   ├── Dashboard.vue（若存在）
│   ├── ZoneList.vue
│   ├── RecordList.vue
│   ├── NamedConfig.vue
│   ├── ChangeRequests.vue
│   ├── Audit.vue
│   ├── DeviceManagement.vue
│   └── UserManagement.vue
├── components/
│   ├── TopBar.vue
│   └── Sidebar.vue
└── api/
    └── index.ts         # Axios 实例 + 拦截器 + 端点定义
```

### 4.3 模块依赖图

```
                   ┌────────────┐
                   │   views/   │ (页面)
                   └─────┬──────┘
                         │
                   ┌─────▼──────┐
                   │  stores/   │ (状态)
                   └─────┬──────┘
                         │
                   ┌─────▼──────┐
                   │   api/     │ (HTTP)
                   └─────┬──────┘
                         │ HTTPS
        ┌────────────────┼────────────────┐
        │                │                │
  ┌─────▼──────┐  ┌──────▼───────┐  ┌─────▼──────┐
  │  routes/   │  │  services/   │  │   core/    │
  │  (FastAPI) │  │ (ssh, parse) │  │  (auth)    │
  └─────┬──────┘  └──────┬───────┘  └─────┬──────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
                   ┌─────▼──────┐
                   │  models/   │ (ORM)
                   └─────┬──────┘
                         │
                   ┌─────▼──────┐
                   │ database.py│ (engine)
                   └────────────┘
```

---

## 5. 数据模型

### 5.1 ER 图

```
┌─────────────┐       ┌──────────────────┐       ┌──────────────┐
│   users     │       │ user_zone_access │       │    zones     │
├─────────────┤       ├──────────────────┤       ├──────────────┤
│ id          │◀──────│ user_id          │       │ id           │
│ username    │       │ zone_id          │──────▶│ zone_name    │
│ password    │       │ permissions[]    │       │ zone_type    │
│ role        │       └──────────────────┘       │ device_id    │
│ display_name│                                  │ view_name    │
│ email       │                                  │ last_serial  │
└──────┬──────┘                                  └──────┬───────┘
       │                                                │
       │                                                ▼
       │                                        ┌──────────────┐
       │                                        │  f5_devices  │
       │                                        ├──────────────┤
       │                                        │ id           │
       │                                        │ host         │
       │                                        │ group_name   │
       │                                        │ ...          │
       │                                        └──────────────┘
       │
       ▼
┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  audit_log   │    │ change_requests │    │ zone_backups │
├──────────────┤    ├─────────────────┤    ├──────────────┤
│ user_id      │    │ requester_id    │    │ zone_id      │
│ action       │    │ approver_id     │    │ content      │
│ zone_name    │    │ status          │    │ serial       │
│ status       │    │ payload (JSON)  │    │ created_at   │
│ created_at   │    │ approved_at     │    └──────────────┘
└──────────────┘    │ executed_at     │
                    └─────────────────┘
```

### 5.2 表字段速查

#### `users`

| 字段 | 类型 | 索引 | 说明 |
|------|------|------|------|
| id | int PK | | 自增 |
| username | str(50) | UNIQUE | 登录名 |
| password_hash | str | | bcrypt |
| role | enum | | super_admin / zone_operator / zone_viewer / approver |
| display_name | str | | 显示名 |
| email | str | | 通知邮箱 |
| is_active | bool | | 软删除标志 |

#### `f5_devices`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| group_name | str | 显示名（如「北京北七家」） |
| host | str | F5 管理 IP |
| port | int | SSH 端口 |
| username / password / key_path | str | SSH 凭据 |
| named_conf_path | str | BIND 主配置路径 |
| zone_dir | str | zone 文件目录 |
| is_active | bool | 是否启用 |

#### `zones`

| 字段 | 类型 | 说明 |
|------|------|------|
| zone_name | str | FQDN（如 `ppv2.com`） |
| zone_type | enum | master / slave / forward |
| view_name | str | BIND view |
| file_name | str | zone 文件名 |
| record_count | int | 缓存 |
| last_serial | str | YYYYMMDDnn 格式 |
| device_id | FK | 所属 F5 |

#### `change_requests`

| 字段 | 类型 | 说明 |
|------|------|------|
| requester_id | FK | 申请人 |
| approver_id | FK nullable | 审批人 |
| zone_id | FK | 目标区域 |
| action | enum | add / modify / delete |
| payload | JSON | 操作详情 |
| status | enum | pending / approved / rejected / executed / failed |
| reason | str | 申请理由 |
| reject_reason | str | 拒绝理由 |

#### `zone_backups`

| 字段 | 类型 | 说明 |
|------|------|------|
| zone_id | FK | |
| content | text | zone 文件全文 |
| serial | str | 备份时的 SOA serial |
| created_at | datetime | |

#### `audit_log`

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | FK nullable | 系统行为时为 null |
| username | str | 冗余（user 删除后保留） |
| action | str | login / zone_discover / record_add / ... |
| target | str | 操作对象 |
| ip | str | 来源 IP |
| status | str | success / failure |

---

## 6. API 设计规范

### 6.1 RESTful 约定

| 方法 | 路径 | 含义 |
|------|------|------|
| GET | `/api/{resource}` | 列表（支持 `?page=&size=&filter=`） |
| GET | `/api/{resource}/{id}` | 详情 |
| POST | `/api/{resource}` | 创建 |
| PUT | `/api/{resource}/{id}` | 全量更新 |
| PATCH | `/api/{resource}/{id}` | 部分更新 |
| DELETE | `/api/{resource}/{id}` | 删除 |

### 6.2 响应格式

成功：

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... }
}
```

失败：

```json
{
  "code": 1001,
  "message": "用户名或密码错误",
  "data": null
}
```

错误码：

| 范围 | 含义 |
|------|------|
| 0 | 成功 |
| 1xxx | 通用 / 认证 |
| 2xxx | 资源未找到 |
| 3xxx | 权限不足 |
| 4xxx | 业务规则（如 SOA serial 回退） |
| 5xxx | F5 SSH / 外部依赖 |

### 6.3 鉴权

- 所有 `/api/*` 除 `/auth/login` 与 `/health` 外，必须 `Authorization: Bearer <jwt>`
- JWT payload：`{ sub: user_id, username, role, exp }`
- 过期：默认 480 分钟（`.env` 中 `JWT_EXPIRE_MINUTES`）

---

## 7. 核心流程

### 7.1 启动流程

```
main.py lifespan()
    ↓
_load_devices()
    ↓
SELECT * FROM f5_devices WHERE is_active=true
    ↓
ssh_connector.register_device(id, config)  // 建立 Paramiko 长连接
    ↓
[HTTP 请求进入]
```

### 7.2 记录新增流程

```
POST /api/records
    ↓
[鉴权] 当前用户是否对 zone 有 record_add 权限？
    ↓ 否 → 403
    ↓ 是
[审批开关] 是否启用变更审批？
    ↓ 否（环境变量或 zone 配置）
       → 直接进入「执行」步骤
    ↓ 是（默认）
       → 创建 ChangeRequest(status=pending)
       → 返回 202 + request_id
       → （异步或人工触发）通知 approver

[Approver] PATCH /api/change_requests/{id}  status=approved
    ↓
[执行] ssh_connector.run(device_id, "rndc freeze ...")
    ↓
       → zone 文件读取
    ↓
       → 解析 + 注入新记录
    ↓
       → 备份原文件 → zone_backups 表
    ↓
       → scp 回写到 F5
    ↓
       → rndc reload
    ↓
[审计] INSERT INTO audit_log ...
    ↓
返回 200
```

### 7.3 变更回滚流程

```
GET /api/zones/{id}/backups
    ↓
[选择备份]
    ↓
POST /api/zones/{id}/rollback {backup_id}
    ↓
ssh_connector.run(device_id, "cp <backup> <zone_file> && rndc reload")
    ↓
[审计]
```

---

## 8. 安全模型

### 8.1 认证

- 密码：`passlib.bcrypt` 哈希（cost=12）
- JWT：`HS256`，密钥从 `JWT_SECRET` 读取
- Token 有效期：8 小时（可配）

### 8.2 授权（RBAC + ABAC 混合）

| 角色 | 权限 |
|------|------|
| super_admin | 全部资源 |
| zone_operator | 已授权区域的记录读写 |
| zone_viewer | 已授权区域的只读 |
| approver | 审批变更（不直接编辑） |

授权检查在 `core/auth.py` 的依赖注入中执行：

```python
async def require_zone_perm(perm: str, zone_id: int, user: User = Depends(current_user)):
    if user.role == "super_admin":
        return
    access = await get_user_zone_access(user.id, zone_id)
    if perm not in access.permissions:
        raise HTTPException(403, "无权限")
```

### 8.3 传输安全

- 前端 HTTPS 强制（nginx `301` 跳转）
- 后端容器间 HTTP（仅内网）
- F5 SSH：优先密钥认证，禁用密码登录的设备不允许接入

### 8.4 审计

所有写操作（直接执行或审批后执行）必须写 `audit_log`：

```python
await AuditLog.create(
    user_id=current_user.id,
    action="record_add",
    target=f"zone={zone_name}, name={record_name}",
    ip=request.client.host,
    status="success",
)
```

---

## 9. 扩展点

### 9.1 新增 F5 设备类型

`app/services/ssh_connector.py` 是抽象层，可替换为：

- F5 iControl REST API（适用于开启 REST 的设备）
- F5 BIG-IQ（集中管理）

### 9.2 新增 DNS 引擎支持

目前仅支持 BIND 9 zone 文件格式。扩展其他引擎（PowerDNS / Knot）：

1. 在 `services/` 下新增 `powerdns_parser.py`
2. 在 `services/zone_parser.py` 增加 dispatch
3. `f5_devices` 表增加 `engine_type` 字段

### 9.3 新增通知渠道

审批 / 变更结果当前无内置通知。接入飞书 / 钉钉 / 邮件：

1. 在 `services/` 下新增 `notifier.py`
2. 在 `api/routes/change_requests.py` 的 approve/reject 处调用

### 9.4 新增认证源

当前仅本地账号。可扩展 LDAP / OIDC / SAML：

1. 在 `core/auth.py` 增加 `oauth2_provider` 抽象
2. 前端 `/api/auth/callback/{provider}` 路由

---

## 10. 二次开发指引

### 10.1 本地开发环境

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env  # 编辑后启动
python seed.py               # 初始化 + 种子
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

### 10.2 添加一条新 API

1. 在 `schemas/__init__.py` 定义 Pydantic 模型
2. 在 `api/routes/{resource}.py` 增加 endpoint
3. 在 `main.py` 注册（若新建文件）
4. 前端在 `api/index.ts` 增加 client 方法
5. 前端在 `views/{Page}.vue` 调用

### 10.3 数据库迁移

使用 Alembic（推荐）：

```bash
cd backend
alembic init alembic
alembic revision --autogenerate -m "add zone_backups table"
alembic upgrade head
```

当前 Lite 模式直接 `Base.metadata.create_all` 自动建表，生产环境强烈建议切到 Alembic。

### 10.4 测试

- 后端：`pytest tests/` （预留，待补充）
- 前端：暂无自动化测试，建议接入 Vitest

### 10.5 日志约定

- 应用日志：stdout，结构化 JSON（生产可接 Loki）
- 审计日志：`audit_log` 表
- nginx 访问日志：`/var/log/nginx/access.log`（容器内）

---

## 📎 附录

### A. 配置项全集

参见 [.env.example](../.env.example)。

### B. 端口清单

| 端口 | 用途 | 暴露 |
|------|------|------|
| 80 | HTTP（重定向） | 主机 |
| 443 | HTTPS | 主机 |
| 8000 | FastAPI | 仅容器内网 |
| 22 | F5 SSH | 出站 |

### C. 已知约束

| 约束 | 影响 | 应对 |
|------|------|------|
| F5 chroot 后路径 | named 实际路径与外部路径差一层 | 已通过 `F5_NAMED_CONF` 配置适配 |
| Paramiko GIL | 单线程 SSH IO | 多设备并发场景考虑用 multiprocessing 或切换到异步库 |
| SQLite 写锁 | 高并发写会排队 | Full / K8s 模式使用 Postgres |

---

> **下一步**：开发新功能前请阅读 [二次开发指引](#10-二次开发指引)。