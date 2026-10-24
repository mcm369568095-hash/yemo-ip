# 计费契约 · 支付宝 A2M 402（按次付费）+ 数据留存契约

> 本文件是「夜秣个人IP生成器」客户端与服务端之间的付费接口契约。
> 服务端实现于作者已部署的商家服务端，本文件定义双方必须一致遵守的字段、流程与数据留存。
> 本文档与 v1.0.0 实际部署版（技能包 `skillId=249767`）严格一致。

## 商品登记（支付宝服务市场）

| 项 | 值 |
|---|---|
| 服务市场服务 ID | `API_XXXXXXXXXXXXXXXX`（支付宝下发，服务端 `.alipay-production.json` 登记，不进包） |
| 资源路径 | `/api/ip/generate` |
| 收款 PID | 作者支付宝 PID（服务端配置，不进包） |
| 计费模式 | `per_call`（按次） |
| 登记单价 | **5.00 元 / 次**（必与服务市场登记逐字一致） |
| 单次产出 | **1 张图**（硬约束，令牌一次性） |

> ⚠️ 定价铁律：服务市场登记单价必须与账单 `amount` 逐字一致；一个服务只能一个单价。

---

## 一、前端传什么（三步，字段写死）

> 真实入口：`https://api.yemo.xyz/api/ip/generate`（可用环境变量 `PAYSKILL_API_BASE` 覆盖）。
> 付费走支付宝 AI 付 402 标准头：`Payment-Needed`（服务端→客户端，账单）、`Payment-Proof`（客户端→服务端，凭证）、`Payment-Validation`（服务端→客户端，交付证据）。

### 1. quote（拿账单）— `GET /api/ip/generate?style=<编号>`

| 前端传 | 约束 |
|---|---|
| `style` | query 参数，`001`–`051` 之一，必须在服务端风格表内 |

服务端未付款返回 **HTTP 402**，并带响应头 `Payment-Needed`（base64url 编码的账单 JSON）；body 同步返回顶层字段：

```json
{
  "error": "Payment Required",
  "out_trade_no": "YEMOIP-20260926-xxxxxxxx",
  "amount": "5.00",
  "currency": "CNY",
  "goods_name": "夜秣个人IP生成器·单张手绘IP形象",
  "resource_id": "yemo-ip",
  "service_id": "API_XXXXXXXXXXXXXXXX",
  "seller_id": "<PID>",
  "pay_before": "2026-09-26T12:00:00+08:00",
  "sign": "<服务端对下方 8 字段字典序拼接后的签名>"
}
```

验签 8 字段（字典序 `k=v` `&` 连接，与支付宝 A2M 一致）：
`amount / currency / goods_name / out_trade_no / pay_before / resource_id / seller_id / service_id`

客户端把 `Payment-Needed` 头解码后的整段账单原样存为本地状态文件，**不改动任何字段**。

### 2. pay（买家付款）— 不经过本服务端

```bash
alipay-bot 402-buyer-pay -f payment_needed.json -r "https://api.yemo.xyz/api/ip/generate?style=023" -m GET -i "夜秣个人IP生成器·单张手绘IP形象" -o json
```

> 钱包未开通时 `402-buyer-pay` 出的是开通页不是收银台；买家与卖家不能是同一支付宝账号（作者本人无法给自己测）。

### 3. prove（上传付款凭证 + 传照片出图）— `POST /api/ip/generate`

| 前端传 | 位置 | 说明 |
|---|---|---|
| `Payment-Proof` | 请求头 | `402-buyer-pay` 返回的完整凭证 JSON（原文） |
| `style` | body JSON | 与 quote 时一致的风格编号 |
| `photo_b64` | body JSON | 人物照片，**base64 或 data URI**，仅本次出图在内存解码，不落盘 |

```json
{ "style": "023", "photo_b64": "data:image/jpeg;base64,/9j/4AAQ...（略）" }
```

服务端验签通过、出图成功返回 **HTTP 200**，并带响应头 `Payment-Validation`（交付证据）；body：

```json
{ "status": "ok", "image_url": "https://api.yemo.xyz/api/ip/download/<token>.png", "style": "023" }
```

**幂等要求**：同一 `out_trade_no` 重复 prove，返回**同一个**出图结果（同一 `image_url`），不重复出图、不报错。

**硬约束**：
- 同一 `out_trade_no` 终身只出 **1 张**图；
- `style` 必须与下单时一致，不一致返回 400；
- 生图失败（500）时令牌**不销毁**，可重试出图。

---

## 二、服务端留什么（订单台账，字段写死）

服务端持久化一张订单表（SQLite，`ip_orders.db`），**只存以下列，多一列都不存**：

| 列 | 类型 | 何时写入 | 用途 |
|---|---|---|---|
| `out_trade_no` | TEXT PK | quote | 支付宝订单号，对账主键 |
| `style` | TEXT | quote | 记录买家选的风格 |
| `paid` | INTEGER 0/1 | prove | 是否已验付 |
| `paid_token` | TEXT | prove | 一次性出图令牌（幂等：同单返回同一令牌） |
| `token_used` | INTEGER 0/1 | prove | 令牌是否已用（**单图闸门**） |
| `created_at` | TEXT | quote | 下单时间 |
| `paid_at` | TEXT | prove | 验付时间 |
| `photo_sha256` | TEXT | prove | **照片哈希，不是照片本身**（防滥用/去重） |
| `result_url` | TEXT | prove | 成品图 URL（支持补发） |
| `alipay_proof_json` | TEXT | prove | 支付宝凭证原文（对账用） |

### 隐私红线（服务端必须遵守）

1. **不落盘存原图**：照片字节只在 prove 请求的内存里活一次，出完图即丢弃；台账里只有 SHA-256 哈希。
2. **不记录买家身份**：不存 IP、不存 UA、不存任何可识别自然人的字段。
3. **不留生图中间产物**：提示词、参考图缓存一律不持久化。
4. 台账只服务于三件事：对账（支付宝流水）、防重放（令牌一次性）、售后补发（result_url）。

---

## 三、错误码

| HTTP | 含义 |
|---|---|
| 402 | 未付款，返回 Payment-Needed |
| 503 | 服务未登记（`SERVICE_NOT_REGISTERED`），网关暂时不可售 |
| 403 | 凭证无效 / 签名不符 / 令牌已用 / 令牌不存在 |
| 400 | 缺 style 或照片、style 不在 001–051、style 与订单不一致 |
| 500 | 服务端生图失败（此时令牌**不销毁**，可重试出图） |
