# 演示模式（DEMO_MODE）

用于**没有 F5 现场**的场景：把平台切到演示模式后，所有 F5 操作改由本地固定数据目录提供，
界面上的 Zone 列表、记录管理、变更、备份、刷新全部可用，读写都在本地生效，**不会碰任何真实设备**。
适合 POC 演示、投标演示、培训，也适合离线环境预览。

> 默认关闭。不设置 `DEMO_MODE` 时，平台行为与以前完全一致（走 SSH 连真实 F5）。

---

## 一、数据目录结构

演示模式只认 `DEMO_DATA_DIR` 下的两个东西，格式与 F5 上完全一致：

```
DEMO_DATA_DIR/
├── named.conf                    # 与 F5 /var/named/config/named.conf 相同语法
└── namedb/
    ├── db.external.ppv2.com.             # 一个文件 = 一个 zone（命名同 F5）
    ├── db.external.cq-changan-gm.com.
    └── ...
```

- **有哪些 zone**：由 `named.conf` 里的 `zone "xxx." { ... };` 决定
- **zone 里有哪些记录**：由 `namedb/db.external.<zone>.` 文件内容决定
- 目录可写：新建 zone、增删改记录会直接写到这个目录（原目录内容会生成 `.bak`）

---

## 二、启用方式

编辑 `.env`：

```bash
DEMO_MODE=true
DEMO_DATA_DIR=/home/ubuntu/dns-manager-demo      # 用绝对路径，避免受工作目录影响
```

重启后端：

```bash
# VM / systemd 部署
sudo systemctl restart dns-backend

# Docker 部署
docker compose -f docker-compose.lite.yml up -d
```

验证是否生效：

```bash
curl -s http://127.0.0.1:8000/api/health
# {"status":"ok",...,"demo_mode":true}
```

`demo_mode: true` 即已生效。此时设备页面里的「测试连接」会直接成功（返回 `bigip-demo.f5.com`），
设备记录里的真实 IP / 凭据在这台机器上不再被使用。

---

## 三、准备演示数据

### 方式 A：用真实 F5 的现有配置（推荐，演示效果最真实）

在**能连到 F5 的机器**上（例如本机 Docker 环境），把 named.conf 和全部 zone 文件导出：

```python
# 存为 export_zones.py，在能访问 F5 的环境执行
# 依赖已随平台安装：paramiko
import os
import paramiko

HOST, PORT, USER, PASSWORD = "172.18.1.202", 22, "root", "<F5密码>"
NAMED_CONF = "/var/named/config/named.conf"
ZONE_DIR = "/var/named/config/namedb"
OUT = "/tmp/demo-data"

os.makedirs(f"{OUT}/namedb", exist_ok=True)
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15,
            allow_agent=False, look_for_keys=False)

with cli.open_sftp() as sftp:
    with sftp.file(NAMED_CONF) as f:
        open(f"{OUT}/named.conf", "w").write(f.read().decode())
    for name in sftp.listdir(ZONE_DIR):
        if not name.startswith("db.external.") or name.endswith((".jnl", ".bak")):
            continue
        with sftp.file(f"{ZONE_DIR}/{name}") as f:
            open(f"{OUT}/namedb/{name}", "w").write(f.read().decode())
        print("exported", name)

cli.close()
```

打包并放到演示服务器（目录位置与 `DEMO_DATA_DIR` 一致）：

```bash
tar czf demo-data.tar.gz -C /tmp demo-data
scp demo-data.tar.gz ubuntu@<演示服务器IP>:/tmp/
ssh ubuntu@<演示服务器IP> 'sudo mkdir -p /home/ubuntu/dns-manager-demo && sudo tar xzf /tmp/demo-data.tar.gz -C /home/ubuntu/dns-manager-demo --strip-components=1'
```

> ⚠️ 导出的 zone 文件是**客户真实 DNS 数据**。不要再分发、不要提交到公开仓库，
> 演示结束建议删除或改为脱敏数据。

### 方式 B：手工造一份脱敏演示数据

新建两个目录，手写最小 zone 文件即可，例如 `namedb/db.external.demo.com.`：

```
$ORIGIN demo.com.
$TTL 300
@   IN SOA  dns1.demo.com. hostmaster.demo.com. (
        2026093001 3600 900 604800 300 )
@   IN NS   dns1.demo.com.
dns1  IN A  10.0.0.53
www   IN A  10.0.0.10
```

再在 `named.conf` 里加对应 stanza：

```
view "external" {
    zone "demo.com." {
        type master;
        file "db.external.demo.com.";
        allow-update { localhost; };
    };
};
```

---

## 四、数据库里的 Zone 列表要一致

Zone 列表页读的是数据库 `zones` 表，**记录管理读的是 zone 文件**。
如果两边的 zone 对不上，会出现「列表里有、点进去报文件不存在」。

演示前把 `zones` 表按演示数据对齐（示例）：

```sql
DELETE FROM zones WHERE zone_name NOT IN ('ppv2.com','cq-changan-gm.com','test.com','air.com','motorola.com');
DELETE FROM zones WHERE id NOT IN (1,2,3,4,5);

INSERT OR REPLACE INTO zones
  (id, zone_name, zone_type, view_name, file_name, record_count, is_active, created_at)
VALUES
  (1,'ppv2.com','master','external','db.external.ppv2.com.',6,1,'2026-07-30 15:22:30'),
  (2,'cq-changan-gm.com','master','external','db.external.cq-changan-gm.com.',4,1,'2026-07-30 15:22:30'),
  (3,'test.com','master','external','db.external.test.com.',5,1,'2026-09-30 01:29:08'),
  (4,'air.com','master','external','db.external.air.com.',5,1,'2026-09-30 01:29:08'),
  (5,'motorola.com','master','external','db.external.motorola.com.',3,1,'2026-09-30 01:29:43');
```

> `file_name` 建议带结尾点（`db.external.<zone>.`），与 F5 命名保持一致。
> `record_count` 用于列表展示，填个合理值即可（读取时会以文件内容为准）。

---

## 五、演示注意事项

| 事项 | 说明 |
|---|---|
| 数据是否落盘 | 是。新建/修改记录会写入 `DEMO_DATA_DIR`，重启后仍保留 |
| 会不会影响真实 F5 | 不会。演示模式下不建立任何 SSH 连接 |
| 想恢复出厂数据 | 重新解压一次演示数据 tar 覆盖即可（`sudo tar xzf ... -C ...`） |
| 想退回真实模式 | `.env` 里 `DEMO_MODE=false` 后重启后端 |
| 目录权限 | 后端进程（systemd 的 ubuntu 用户）需对 `DEMO_DATA_DIR` 有读写权限：`chown -R ubuntu:ubuntu` |
| 前端要不要重打包 | 不需要。这是纯后端开关 |
