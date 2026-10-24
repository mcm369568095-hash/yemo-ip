---
name: 夜秣个人IP生成器
description: >
  手绘个人 IP 生成付费技能。买家先选一种手绘风格（15 种精选），支付 5 元，上传一张清晰人物照片，
  服务端结合照片身份与所选风格，生成一张专属个人 IP 形象图并返回。
  付费方式：支付宝 AI 付按次结算，首次需在支付宝开通一次「AI 付」钱包授权（以后自动扣）；
  调用本技能前必须跑 `scripts/pay_generate.py quote → pay → prove`，**未经确认不发起真实付款**。
  当用户说「做个个人IP」「把手绘IP」「生成我的卡通形象」「夜秣个人IP生成器」「上传照片出IP」时触发。
description_zh: "手绘个人 IP 生成：选 15 种手绘风格之一，付 5 元，传照片，出一张专属 IP 形象图（支付宝按次付费）"
description_en: "Hand-drawn personal IP generator - pick a style, pay 5 CNY, upload a photo, get one custom IP portrait. Alipay AI Pay per-generation."
version: 1.0.2
slug: yemo-ip
displayName: 夜秣个人IP生成器（手绘个人IP生成）
author: 夜秣
---

# 夜秣个人IP生成器 · 手绘个人 IP 生成

> 买家流程：**选风格 → 开通钱包（仅首次）→ 付 5 元 → 传照片 → 服务端生成一张个人 IP 图 → 下载成品**。
> 出图走作者服务端代持网关，费用已含在单次出品价里。**一次付费 = 一张图，出图失败不烧令牌、可重试**。
> 客户端零密钥、零本地生图脚本。

---

## 🧾 产品定位与计费（先看这里）

| 项目 | 说明 |
|---|---|
| **出品方** | 夜秣（作者） |
| **客户需要准备** | ① 选一种手绘风格（见下）② 一张清晰人物照片（本地文件） |
| **生图费用** | **作者承担**（服务端内置网关 Key，客户无需自备任何 API） |
| **客户付费方式** | **按张付费**：跑 `scripts/pay_generate.py`，经支付宝 AI 付结算，**5.00 元 / 张** |
| **交付物** | 一张手绘风格个人 IP 形象图（竖版 1024×1536，纯白/浅色背景，可商用） |
| **付费前必做** | 先 `quote` 拿账单、再 `pay` 生成支付入口、付款后 `prove` 取回成品 |

> **没有「本地免费自产」路径**：本技能发布的只有付费客户端，身份分析 / 生图全部在作者服务端完成，
> 客户端不携带任何生图脚本或密钥，无法离线白嫖。要拿到成品，必须走付费链路。

---

## 🎨 可选手绘风格（15 种精选）

完整风格库与核心视觉特征见 `references/风格库.md`。买家任选其一，把编号告诉技能即可。

| 编号 | 生图名称 | 视觉气质 |
|---|---|---|
| 001 | Playful Deadpan Doodle | 松散黑线、怪萌人物、白底、冷脸幽默 |
| 003 | Fine-Line Urban Miniature | 极细钢笔线、小人物大空间、温柔法式留白 |
| 005 | Childlike Free-Line Humor | 极简黑线、儿童式自由造型、低细节 |
| 009 | Raw Zine Diary Cartoon | 粗糙手帐、Zine 感、纸纹颗粒、反精致 |
| 015 | Soft Relationship Editorial Line | 极简线稿、柔和色块、生活型社论 |
| 018 | Minimal Deadpan Dialogue | 极简圆头人物、面无表情、灰蓝米色小色块 |
| 021 | Watercolor Handwritten Life Notes | 细黑线、柔和水彩点染、女性人物 |
| 023 | Warm Minimal Female Line | 黑色简线长发女性、暖色腮红、干净背景 |
| 028 | Retro Detached American Comic | 齐肩直发、方镜、条纹绿外套、复古美式 |
| 030 | Clean Urban Solitude Comic | 清晰细线、亚洲女性半身、都市安静留白 |
| 034 | Elastic Sunday Strip | 弹性墨线、夸张表情、透明水彩 |
| 036 | Loose Ink-and-Wash Storybook | 抖动墨线、松散水彩、速写感 |
| 039 | Warm Vintage Line-and-Wash | 古典细线、水彩旧书感、温暖生活 |
| 049 | Dreamlike Surreal Storybook | 柔和笔触、低饱和梦境、安静留白 |
| 051 | Expressive Character Sketch | 速写式线条、夸张亲切、鲜明性格 |

> 风格 001–035 偏社论/幽默手绘；036–054 偏绘本/叙事手绘。想要「可爱治愈」选 021/023/039；
> 想要「都市冷淡」选 003/015/030；想要「夸张个性」选 001/009/034/051。

---

## 💳 付费出品（A2M 402）· 调用线上接口

| 项 | 值 |
|---|---|
| 资源 URL | `<服务端>/api/ip/generate`（默认作者已部署的服务端，可用环境变量 `PAYSKILL_API_BASE` 覆盖） |
| 请求方式 | `GET`（拿账单）/ `POST`（传照片出图） |
| 输入 | `style`（必填，001–051 之一）、照片文件（付款后上传） |
| 单价 | **5.00 元 / 张**（与服务市场登记单价一致） |
| 依赖 | 仅 Python 标准库；无需 SDK、无需密钥 |
| 付款入口依赖 | 买家侧官方支付 CLI `alipay-bot`（装法见下） |
| 协议依据 | 支付宝官方 A2M 402 契约 |

> **服务端是谁的、能不能换**：资源地址是作者已部署的商家服务端（出账单、验付、出品、交付），
> 装完即用，无需自建；如需自建服务端，按 `references/pay-a2m-contract.md` 实现同款接口即可。

完整字段与响应结构见 `references/pay-a2m-contract.md`。

---

## 🛠 调用流程（买家侧）

```text
0. 装买家侧支付 CLI（只需一次）：npx -y @alipay/agent-payment@latest install
1. 选风格：买家从上面 15 种里选一个编号（如 021）
2. 拿账单：python scripts/pay_generate.py quote --style 021
3. 查钱包：python scripts/pay_generate.py wallet check
   └─ 状态 none = 还没开通（首次一定要走这步）：
        python scripts/pay_generate.py wallet apply      # 出开通二维码
        → 用【本人支付宝】扫码，App 里拿 6 位授权码
        → python scripts/pay_generate.py wallet bind --code <6位授权码>
      状态 ready = 已开通，跳过（第二次起这里直接过）
4. 付款：  python scripts/pay_generate.py pay
   → 出付款二维码/链接，本人扫码确认，真实扣款 5.00 元
5. 出图：  python scripts/pay_generate.py prove --state-file .ip_payment_state.json \
            --proof "<Payment-Proof>" --photo 照片本地路径.jpg
   └─ 照片与出图在同一个命令里完成，没有单独的 generate 步骤
6. 取图：  终端打印「下载地址」（/api/ip/download/<订单号>），GET 下载即可
```

> 每一步都有明确提示；第 4 步会在支付宝完成真实扣款（5.00 元），**未付款不会出图**。
> 出图失败（如网关波动）不烧令牌：同一 `--proof` 重跑第 5 步即可，**不会重复扣费**。

### 🔴 照片必须传本地文件路径（2026-10-21 首单实测教训）

`--photo` 接的是**本地文件路径**。**禁止**把照片 base64 / 图片内容塞进行令参数——
命令行有长度上限，agent 会被迫把照片压成几百 px 的缩图，五官细节全丢，出来的 IP 不像本人。

- 聊天里收到的照片：**先保存成本地文件**（原图，不要用聊天软件转存的那张压缩版），再把路径传给 `--photo`
- 脚本会打印照片像素尺寸；长边不足 700px 会弹警告——那就是缩图，换原图
- 手机相册原图通常长边 2000px+，直接传，8MB 以内都不用管

### 取图与交付（第 6 步展开）

```text
下载地址形如：https://api.yemo.xyz/api/ip/download/YEMO1792...（GET，无需任何凭证）
curl -O "https://api.yemo.xyz/api/ip/download/<订单号>"      # 或浏览器直接打开
保存为本地文件后，再把本地文件交给用户 / 挂进附件库。
```

> 下载地址是普通公网 GET，**不发凭证、不过期**，什么时候取都取得到。
> 注意用 GET 取图；对下载地址做 HEAD 探活也可以（服务端已支持）。

---

## ⚠️ 输入要求（给买家的照片规范）

- 至少一张人物清晰、轮廓完整、五官可辨认的照片。
- 优先正面或轻微侧面的全身/半身照；戴眼镜、手表、首饰等真实配件会保留。
- 原始照片仅用于身份锚定，**不复制原背景、其他人物、文字或水印**。
- 不根据照片猜测姓名、职业、民族、健康、政治、宗教、性取向等敏感属性。
- **隐私约定**：照片只在出图当次使用，服务端不落盘存原图，仅留存哈希值用于防滥用。

---

## 📦 本技能包含文件

| 文件 | 作用 | 是否进买家包 |
|---|---|---|
| `SKILL.md` | 本说明 | ✅ |
| `scripts/pay_generate.py` | 付费客户端（quote/pay/wallet/prove/status/run） | ✅ |
| `references/风格库.md` | 15 种手绘风格完整定义 | ✅ |
| `references/ip_identity_spec.md` | 照片→固定身份→IP 提示骨架 | ✅ |
| `references/pay-a2m-contract.md` | 402 计费契约 + 数据留存契约 | ✅ |
| `ARCHITECTURE.md` | 架构分析（模式 A，作者内部） | ❌ 不进包 |
| `scripts/package_skill.py` | 打包排除表 | ✅（仅作者发版用） |
| `scripts/server/*` | 服务端代出模块（作者私有，部署在作者服务端） | ❌ 不进包 |
