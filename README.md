# us-vless — 美国 IP 的 VLESS + WS + TLS 节点（单端口自描述部署包）

一个可直接丢到任何美国 PaaS / VPS 上的 **VLESS + WebSocket + TLS** 节点容器。
部署完打开 `https://<你的域名>/` 就是一张 **Shadowrocket 二维码** + 订阅链接 + vless:// 链接，
不需要你手动拼 URL、不需要提前知道平台分给你的域名。

---

## 1. 为什么这么设计

| 约束 | 现实 | 本包的做法 |
|---|---|---|
| PaaS 只给 **1 个公网端口** | Render/Fly/HF 都是 `$PORT` 单端口 | `app.py` 独占 `$PORT`，把 WS 升级流量原样转给本机 Xray（`127.0.0.1:18080`） |
| TLS 由平台边缘终结 | 证书/域名随时变，`*.onrender.com`、`*.fly.dev` 都无法预知 | 边缘 TLS 即可，节点内部跑明文 WS；URI 里 `security=tls` + `sni=<平台域名>` |
| 域名部署前未知 | 手写 `vless://` 一定写错 | `/vless`、`/sub`、`/qr.png` **按请求的 Host 头实时生成**，永远自洽 |
| 免费档会休眠 | 冷启动 3–30s | `/health` 探针 + 首包唤醒；Fly 可开常驻 |

服务端点（全部由同一个端口提供）：

```
GET /              落地页：二维码 + 一键复制
GET /qr.png        PNG 二维码（内容 = vless:// URI）
GET /vless         纯文本 vless:// URI
GET /sub           base64 订阅（Shadowrocket / v2rayN / NekoBox 直接导入）
GET /clash.yaml    mihomo / Clash.Meta 单节点配置
GET /health        JSON 健康探针（平台用）
GET <WS_PATH>      WebSocket 升级 → 转发到 Xray VLESS 入站
```

---

## 2. 已实测（本机真实链路，不是纸面配置）

用 **官方 Xray-core v26.10.31** 在本机跑通了完整链路：

```
① HTTP 探测  GET http://127.0.0.1:PORT/ws-xxxxxxxx
            → HTTP/1.1 400 Bad Request          （Xray 在 WS 路径上应答 = 入站活着）

② 真实客户端  xray client（socks5 inbound, vless+ws）
            curl --socks5-hostname 127.0.0.1:10899 https://ipinfo.io/json
            → {"ip":"115.84.87.137","city":"Vientiane","country":"LA", ...}   ✅ 真出网
            curl https://www.google.com/generate_204 → 204                       ✅

③ 产物       /vless  → vless://<uuid>@<host>:443?encryption=none&security=tls&sni=...&type=ws&path=%2Fws-...
            /qr.png → 二维码解码回来与 /vless 完全一致（zxing-cpp 校验通过）
```

也就是说：**同一份镜像，换到美国机房，出口 IP 就是美国的**（②里的 `ipinfo` 就是容器所在机器的出口）。

---

## 3. 部署矩阵（按「拿到美国 IP 的确定性」排序）

| 平台 | 地区（US） | 要什么 | 形态 | 备注 |
|---|---|---|---|---|
| **Fly.io** | `sjc` `lax` `iad` `ord` | 账号 + 卡验证 | 常驻容器，`force_https` | 最接近「生产可用」，可 `min_machines_running=1` 不休眠 |
| **Render** | `oregon`（US-West） | 账号 + 一个 GitHub 仓库（不需要卡） | Docker Web Service，免费档闲置 15 分钟休眠 | 免费、稳、支持 WS，冷启动约 20–30s |
| **任意美国 VPS** | 全美 | 一台机器（$3/月起 / Oracle 免费 ARM） | `docker run -d -p 8080:8080` + Caddy 反代 | 完全自主，不限速 |
| ~~Netrun~~ | de2 = 德国 | 临时邮箱即可 | — | **平台已明确封禁代理**，见第 6 节实测 |

---

## 4. 三条落地路径

### A. Render（免费、美国 Oregon、不用卡）— 约 3 分钟

```bash
# 1) 建一个你自己的仓库（私有也行，Render 用 GitHub App 授权）
cd us-vless
git init && git add Dockerfile app.py entrypoint.sh render.yaml README.md
git commit -m "us-vless node"
gh repo create us-vless --private --source . --push      # 或用网页上传

# 2) render.com → New → Blueprint → 选 us-vless 仓库 → Apply
#    render.yaml 已经写好 region: oregon / plan: free / healthCheckPath: /health
```

部署完成后：

```
https://us-vless.onrender.com/        ← 打开就是二维码，Shadowrocket 扫码即用
https://us-vless.onrender.com/sub     ← 订阅链接
```

> 想换地区/换名字：改 `render.yaml` 里的 `region`/`name` 再 push。
> 免费档闲置 15 分钟休眠，扫码前先访问一次域名唤醒。

### B. Fly.io（常驻、真美国、需卡验证）

```bash
fly auth login
fly launch --copy-config --no-deploy      # app 名改成全局唯一
fly deploy
fly status && fly logs
# 域名：https://<app>.fly.dev/   → 二维码
```

`fly.toml` 里 `primary_region = "sjc"`，`min_machines_running = 1` 保持常驻、不冷启动。

### C. 任意美国 VPS（最稳）

```bash
# 机器上（Debian/Ubuntu，已装 docker）
docker build -t us-vless .
docker run -d --name us-vless --restart=always \
  -p 127.0.0.1:8080:8080 \
  -e NODE_NAME="US-VPS" \
  -e UUID=$(cat /proc/sys/kernel/random/uuid) \
  -e WS_PATH=/ws-$(head -c4 /dev/urandom | xxd -p) \
  us-vless
```

真 TLS（域名 + 自动证书），Caddy 两行：

```caddyfile
node.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

```bash
caddy run --config Caddyfile     # 或 systemctl restart caddy
# 打开 https://node.example.com/ 拿二维码
```

> 没有域名也能跑：VPS 上直接把容器 `-p 8080:8080` 暴露，URI 用 `security=none`（`NO_TLS=1`），
> 但明文 WS 在路上会被 QoS/干扰，生产别这么干。

---

## 5. 客户端导入

- **Shadowrocket**：打开 `https://<域名>/` → 右上角 `+` → 扫描屏幕上的二维码；或
  `+` → 类型 `Subscribe` → 填 `https://<域名>/sub` → 更新。
- **v2rayN / NekoBox**：订阅 → 添加 → 粘贴 `/sub` 链接。
- **mihomo / Clash.Meta**：`proxy-providers` 里指向 `https://<域名>/clash.yaml`。
- 二维码里就是标准 URI：
  ```
  vless://<UUID>@<域名>:443?encryption=none&security=tls&sni=<域名>&fp=chrome&type=ws&host=<域名>&path=%2Fws-xxxx#US-VLESS
  ```

---

## 6. Netrun 实测结论（重要）

按社区那个「Netrun 一句话免费节点」的玩法（临时邮箱 + 平铺 zip 上传 + Website 模式）实测：

```
POST /v1/projects           201  {"id":5403,"name":"us-node-f5cc2d","status":"queued","layout":"dockerfile"}
GET  /v1/projects/5403      200  {"status":"failed",
                                  "host_url":null,
                                  "last_error":"прокси и VPN-серверы на Netrun запрещены"}
```

即：**Netrun 现在会识别并拒绝代理/VPN 项目**（"прокси и VPN-серверы на Netrun запрещены" = "Netrun 禁止代理和 VPN 服务器"），
项目 8 秒内直接 `failed`，不给域名。而且即便放行，Netrun 免费 Website 实例落在 `de2`（德国纽伦堡），
本来也拿不到美国 IP。所以这条路对你「美国节点」的需求是双重不通的。

---

## 7. 运维 / 加固

- **换身份**：改 `UUID`、`WS_PATH` 两个环境变量重启即可（客户端重新扫码）。
- **限速**：免费档 CPU 有限（Render 0.1 vCPU / Fly 1 shared），别多人共用跑 4K。
- **日志**：`xray.log` 在容器 `/app/xray.log`，`loglevel=warning`，不记录访问。
- **隐私**：容器不落盘任何用户数据，`access: none`。
- **别做的事**：不要把这个端点做成公开分享的「公益机场」——平台风控会按流量/连接数判定滥用，
  Render/Fly 都会封；自用 1–3 台设备最稳。

---

## 8. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 打开域名 502 | 容器还在构建/冷启动 | 等 30s，看平台 logs；`/health` 应返回 JSON |
| 扫码后连不上，延迟 0 | WS 路径不对 | 打开 `/vless` 看 `path=`，重新扫 |
| 连上但打不开网页 | 平台边缘没透传 Upgrade | 换 Render/Fly；Cloudflare 后面要关 `WebSocket` 以外的缓冲 |
| TLS 报错 | `sni` 与域名不一致 | 用 `/sub` 的链接，别手抄 |
| 定时断流 | 免费档休眠 | Fly 开 `min_machines_running=1`，或 VPS 部署 |
| 二维码扫不出 | 屏幕缩放 | 直接用 `/qr.png` 原图或在手机上看域名首页 |

---

## 9. 文件清单

```
us-vless/
├─ app.py            单端口 HTTP 控制面 + WS 隧道（stdlib asyncio，无依赖）
├─ entrypoint.sh     身份落盘（UUID/WS_PATH 重启不变）
├─ Dockerfile        python:3.12-alpine + Xray（amd64/arm64 自适应）
├─ render.yaml       Render 蓝图（oregon / free / health）
├─ fly.toml          Fly 配置（sjc / 常驻 / 256MB）
├─ pack_zip.py       打平铺 zip（把 UUID/路径烘进镜像），给只要上传压缩包的平台
├─ verify.py         两步验收：HTTP 400 探测 + 真实客户端测出口 IP/城市 + 出二维码
├─ browser/          Netrun 全流程自动化（临时邮箱 OTP → 建项目 → 上传 → 轮询），留档可复用
└─ out/              本机实测产物：landing.png / qr-render-us.png
```
