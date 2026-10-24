#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜秣个人IP生成器 · 按量付费（A2M 402）调用方脚本。

职责边界（严格遵守支付宝官方技能 alipay-aipay 的契约）：
- 只做四件事：发业务请求、读 402 账单、带 Payment-Proof 重试、校验交付证据。
- 职责分工：账单签名、验付（payment.verify）与商家履约确认（fulfillment.confirm）
  由商家服务端实现；本脚本只做客户端编排，付款走支付宝官方收银流程。
- 生产付款停在人工确认前，绝不自动发起。

流程：
  quote   只取 402 账单并展示摘要（停在付款确认前，默认动作）
  pay     调支付宝官方买家侧 CLI 生成支付入口（二维码 + 链接），展示后等用户付款
  wallet  钱包三步：check 查开通状态 / apply 拿开通入口 / bind 绑 6 位授权码 / close 解绑换号
          （🔴 首次付款前必须开通：AI 付是一个智能体环境绑一个支付宝账号，一次开通长期有效）
  prove   带 Payment-Proof 重发资源 URL（POST，附带照片 base64），取回出图结果
          —— 照片用 --photo 传【本地文件路径】，不要把 base64 塞进行令参数
  status  查单：先查资源是否存在，再用同一凭证重试一次
  run     一站式：quote → 等凭证 → prove（默认仍需人工提供凭证，不自动付款）

买家侧依赖（付款用，与卖家侧 alipay-aipay 不是同一个包）：
  npx -y @alipay/agent-payment@latest install      # 装完得到 alipay-bot 命令

用法示例：
  python pay_generate.py quote --style 023
  python pay_generate.py wallet check          # 首次付款前查开通状态（none=未开通）
  python pay_generate.py wallet apply          # 未开通时拿开通入口，扫码后拿 6 位授权码
  python pay_generate.py wallet bind --code <6位授权码>
  python pay_generate.py pay --state-file .ip_payment_state.json
  python pay_generate.py prove --state-file .ip_payment_state.json --proof "<base64url>" --photo 我的照片.jpg
  python pay_generate.py status --out-trade-no YEMO... --proof "<base64url>"

🔴 照片必须用 --photo 传【本地文件路径】。不要把 base64 / 图片内容塞进行令参数——
命令行有长度上限，agent 会被迫把照片压成几百 px 的缩图，五官细节全丢，IP 就不像本人了。
聊天里收到的照片，先保存成本地文件，再把路径传给 --photo。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = os.environ.get("PAYSKILL_API_BASE", "https://api.yemo.xyz").rstrip("/")
RESOURCE_PATH = "/api/ip/generate"
DOWNLOAD_PATH = "/api/ip/download"
DEFAULT_PRICE = "5.00"
DEFAULT_STATE_FILE = ".ip_payment_state.json"

# 15 种手绘风格（与服务端 STYLES 同源，供选择参考）
STYLE_CHOICES = [
    "001", "003", "005", "009", "015", "018", "021", "023",
    "028", "030", "034", "036", "039", "049", "051",
]
STYLE_NAMES = {
    "001": "Playful Deadpan Doodle",
    "003": "Fine-Line Urban Miniature",
    "005": "Childlike Free-Line Humor",
    "009": "Raw Zine Diary Cartoon",
    "015": "Soft Relationship Editorial Line",
    "018": "Minimal Deadpan Dialogue",
    "021": "Watercolor Handwritten Life Notes",
    "023": "Warm Minimal Female Line",
    "028": "Retro Detached American Comic",
    "030": "Clean Urban Solitude Comic",
    "034": "Elastic Sunday Strip",
    "036": "Loose Ink-and-Wash Storybook",
    "039": "Warm Vintage Line-and-Wash",
    "049": "Dreamlike Surreal Storybook",
    "051": "Expressive Character Sketch",
}

# Payment-Needed 账单必须包含的路径（校验用）
PAYMENT_NEEDED_REQUIRED_PATHS = (
    ("protocol", "out_trade_no"),
    ("protocol", "amount"),
    ("protocol", "currency"),
    ("protocol", "resource_id"),
    ("protocol", "pay_before"),
    ("protocol", "seller_signature"),
    ("protocol", "seller_sign_type"),
    ("protocol", "seller_unique_id"),
    ("method", "seller_name"),
    ("method", "seller_id"),
    ("method", "seller_app_id"),
    ("method", "goods_name"),
    ("method", "seller_unique_id_key"),
    ("method", "service_id"),
)
KNOWN_DELIVERY_FAILURE_CODES = {
    "CREATE_ORDER_ERROR",
    "FULFILLMENT_CONFIRM_FAILED",
    "FULFILLMENT_ERROR",
    "INVALID_PAYMENT_PROOF",
    "INVALID_PAYMENT_PROOF_FORMAT",
    "MISSING_OUT_TRADE_NO",
    "MISSING_RESOURCE_ID",
    "ORDER_NOT_FOUND",
    "RESOURCE_ID_MISMATCH",
    "SIGN_ERROR",
    "VERIFY_FAILED",
}


def http_request(
    url: str,
    method: str = "GET",
    params: dict | None = None,
    proof: str | None = None,
    timeout: int = 120,
) -> tuple[int, dict[str, str], str]:
    method = method.upper()
    headers: dict[str, str] = {}
    data: bytes | None = None

    if method == "GET":
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    elif method == "POST":
        headers["Content-Type"] = "application/json"
        data = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
    else:
        raise ValueError(f"只支持 GET / POST，收到 {method}")

    if proof:
        headers["Payment-Proof"] = proof

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _headers_dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, _headers_dict(exc.headers), body


def _headers_dict(headers: Any) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


def b64url_decode_json(value: str) -> dict:
    compact = value.strip().strip('"')
    padded = compact + ("=" * ((4 - len(compact) % 4) % 4))
    decoder = base64.urlsafe_b64decode if ("-" in compact or "_" in compact) else base64.b64decode
    data = json.loads(decoder(padded).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("解码结果必须是 JSON 对象")
    return data


def validate_payment_needed(bill: dict, *, expect_sandbox: bool = False) -> None:
    missing = []
    for parent, child in PAYMENT_NEEDED_REQUIRED_PATHS:
        nested = bill.get(parent)
        if not isinstance(nested, dict) or nested.get(child) in (None, ""):
            missing.append(f"{parent}.{child}")
    if missing:
        raise RuntimeError("Payment-Needed 缺少字段: " + ", ".join(missing))
    if expect_sandbox and bill["method"].get("service_id") != "api_mock_service_id":
        raise RuntimeError(
            "沙箱联调 method.service_id 必须为 api_mock_service_id，请把服务端配置切到沙箱后再跑"
        )


def find_delivery_failure(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            found = find_delivery_failure(item)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    if value.get("success") is False:
        return "success=false"
    if value.get("validated") is False:
        return "validated=false"
    if value.get("fulfillment_confirmed") is False or value.get("fulfillmentConfirmed") is False:
        return "fulfillment_confirmed=false"
    for key in ("code", "errorCode", "sub_code", "subCode"):
        code = str(value.get(key) or "")
        if code in KNOWN_DELIVERY_FAILURE_CODES:
            return code
    for item in value.values():
        found = find_delivery_failure(item)
        if found:
            return found
    return None


def validate_delivery(
    status_code: int,
    headers: dict[str, str],
    body: str,
    *,
    expect_out_trade_no: str = "",
    require_payment_validation: bool = True,
) -> tuple[bool, str]:
    if status_code != 200:
        return False, f"最终服务必须返回 HTTP 200，实际为 {status_code}"
    if not body.strip():
        return False, "最终服务返回空响应，未证明资源交付"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None

    resource_id = ""
    if payload is not None:
        failure = find_delivery_failure(payload)
        if failure:
            return False, f"最终服务返回明确业务失败：{failure}"
        if not isinstance(payload, dict):
            return False, "响应 JSON 必须是对象，无法确认资源归属"
        resource_id = str(payload.get("resource_id") or payload.get("resourceId") or "")
        content = payload.get("content")
        if not resource_id or content in (None, "", [], {}):
            return False, "响应缺少非空 resource_id/resourceId 或 content"
        if expect_out_trade_no:
            returned = str(payload.get("out_trade_no") or payload.get("outTradeNo") or "")
            if returned and returned != expect_out_trade_no:
                return False, f"订单号串单：期望 {expect_out_trade_no}，实际 {returned}"

    raw_validation = headers.get("payment-validation")
    if require_payment_validation and not raw_validation:
        return False, "未返回 Payment-Validation 响应头"
    if raw_validation:
        try:
            validation = b64url_decode_json(raw_validation)
        except ValueError as exc:
            return False, str(exc)
        failure = find_delivery_failure(validation)
        if failure:
            return False, f"Payment-Validation 返回明确失败：{failure}"
        if validation.get("validated") is not True:
            return False, "Payment-Validation 未明确返回 validated=true"
        v_trade_no = str(validation.get("trade_no") or validation.get("tradeNo") or "")
        v_resource_id = str(validation.get("resource_id") or validation.get("resourceId") or "")
        if not v_trade_no or not v_resource_id:
            return False, "Payment-Validation 缺少非空 trade_no 或 resource_id"
        if resource_id and v_resource_id != resource_id:
            return False, "Payment-Validation 与响应体的 resource_id 不一致"

    if payload is None and not raw_validation:
        return False, "非 JSON 资源响应缺少可用于确认归属的 Payment-Validation"
    return True, "HTTP 200、非空可归属资源、订单未串单且无明确业务失败"


def load_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"状态文件不存在：{p}（先跑 quote）")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(path: str, state: dict) -> None:
    p = Path(path)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def cmd_quote(args: argparse.Namespace) -> int:
    if args.style not in STYLE_CHOICES:
        print("✗ style 必须是 15 种手绘风格之一，例如：")
        for s in STYLE_CHOICES:
            print(f"    {s}  {STYLE_NAMES.get(s, '')}")
        return 1
    url = args.base_url.rstrip("/") + RESOURCE_PATH
    params = {"style": args.style}
    status, headers, body = http_request(url, "GET", params, timeout=args.timeout)

    if status != 402:
        print(f"[quote] 期望 402，实际 {status}")
        print(body[:2000])
        return 1
    raw = headers.get("payment-needed")
    if not raw:
        print("[quote] 402 但缺少 Payment-Needed 响应头")
        print(body[:2000])
        return 1

    bill = b64url_decode_json(raw)
    validate_payment_needed(bill, expect_sandbox=args.sandbox)

    protocol = bill["protocol"]
    method = bill["method"]
    state = {
        "url": url,
        "method": "GET",
        "params": params,
        "style": args.style,
        "out_trade_no": protocol["out_trade_no"],
        "amount": protocol["amount"],
        "currency": protocol.get("currency", "CNY"),
        "goods_name": method.get("goods_name", ""),
        "resource_id": protocol.get("resource_id", RESOURCE_PATH),
        "pay_before": protocol.get("pay_before", ""),
        "seller_name": method.get("seller_name", ""),
        "service_id": method.get("service_id", ""),
        "payment_needed": raw,
    }
    save_state(args.state_file, state)

    print("=== 待付款账单 ===")
    print(f"商品      ：{state['goods_name']}")
    print(f"金额      ：{state['amount']} {state['currency']}")
    print(f"商户      ：{state['seller_name']}")
    print(f"商户订单号：{state['out_trade_no']}")
    print(f"资源      ：{state['resource_id']}")
    print(f"支付截止  ：{state['pay_before']}")
    print(f"状态文件  ：{args.state_file}")
    print()
    print("下一步：生成支付入口（二维码 / 链接）")
    print(f"  python pay_generate.py pay --state-file {args.state_file}")
    print("付款完成后再取货：")
    print(f"  python pay_generate.py prove --state-file {args.state_file} --proof \"<Payment-Proof>\" --photo 你的照片.jpg")
    return 0


def find_bot() -> str:
    """定位买家侧官方支付 CLI（alipay-bot）。"""
    hit = shutil.which("alipay-bot")
    if hit:
        return hit
    home = Path.home()
    exe = "alipay-bot.exe" if os.name == "nt" else "alipay-bot"
    cands = [
        home / ".openclaw-autoclaw" / "alipay-bot-cli" / "bin" / exe,
        home / ".local" / "bin" / exe,
        home / ".local" / "share" / "alipay-bot-cli" / "runtime" / exe,
    ]
    for c in cands:
        if c.exists():
            return str(c)
    nvm_root = home / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        for p in sorted(nvm_root.glob("*/bin/alipay-bot")):
            if os.access(str(p), os.X_OK):
                return str(p)
    return ""


def run_bot(bot: str, argv: list[str], timeout: int = 60):
    """执行 alipay-bot 子命令，返回 (returncode, 解析后的 JSON 或 None, 原文)。"""
    cmd = [bot] + list(argv) + ["-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, None, f"超时 {timeout}s"
    out = (proc.stdout or "").strip()
    data = None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        start = out.find("{")
        if start >= 0:
            try:
                data = json.loads(out[start:])
            except json.JSONDecodeError:
                data = None
    return proc.returncode, data, out


WALLET_TIP = """\
[wallet] 支付宝 AI 付是「一个智能体环境绑一个支付宝账号」：
        谁扫码开通，以后就只能用那个账号在本环境付款。
        扫码提示「请勿重复绑定」= 该支付宝账号已在别处开通过 AI 付，
        换一个没开通过 AI 付的账号扫码，或先用 wallet close 解绑再绑。
"""


def check_wallet_state(bot: str, timeout: int = 30):
    """返回 (状态串, 原始 JSON)：ready=已开通 / pending=已申请待授权 / none=未开通 / unknown。"""
    _rc, data, _raw = run_bot(bot, ["check-wallet"], timeout)
    if not data:
        return "unknown", {}
    if data.get("code") == 200:
        url = data.get("accessUrl") or data.get("access_url") or ""
        return ("pending", data) if url else ("ready", data)
    if data.get("code") == 500:
        return "none", data
    return "unknown", data


def cmd_wallet(args: argparse.Namespace) -> int:
    bot = args.bot or find_bot()
    if not bot:
        print("[wallet] 找不到 alipay-bot（买家侧官方支付 CLI）。先安装：")
        print("         npx -y @alipay/agent-payment@latest install")
        return 1
    print(f"[wallet] CLI：{bot}")

    if args.action == "check":
        state, data = check_wallet_state(bot, args.timeout)
        print(f"[wallet] 状态：{state}")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
        if state == "none":
            print(WALLET_TIP)
            print("下一步：python pay_generate.py wallet apply")
            return 3
        if state == "pending":
            print("[wallet] 已申请但还没完成授权。用支付宝扫码后把 6 位授权码给我：")
            print("         python pay_generate.py wallet bind --code <6位授权码>")
            return 2
        print("[wallet] 钱包已就绪，可以直接付款：python pay_generate.py pay")
        return 0

    if args.action == "apply":
        argv = ["apply-wallet"]
        if args.agent_name:
            argv += ["-a", args.agent_name]
        rc, data, raw = run_bot(bot, argv, args.timeout)
        if not data:
            print("[wallet] 官方 CLI 无 JSON 输出，原文：")
            print(raw[:2000])
            return 1
        print("=== 开通入口（支付宝官方生成）===")
        for key in ("shortAccessUrl", "shortUrl", "accessUrl"):
            if data.get(key):
                print(f"{key}：{data[key]}")
        qr = (data.get("mediaPaths") or [None])[0]
        if qr:
            print(f"二维码：{qr}")
        if data.get("code") or data.get("message"):
            print(f"返回：code={data.get('code')} message={data.get('message')}")
        print(WALLET_TIP)
        print("用**还没开通过 AI 付**的支付宝扫码，拿到 6 位授权码后：")
        print("  python pay_generate.py wallet bind --code <6位授权码>")
        return 0 if rc == 0 else 1

    if args.action == "bind":
        if not args.code:
            print("[wallet] 缺授权码。用法：wallet bind --code <6位授权码>")
            return 1
        rc, data, raw = run_bot(bot, ["bind-wallet", "-c", args.code], args.timeout)
        if not data:
            print("[wallet] 官方 CLI 无 JSON 输出，原文：")
            print(raw[:2000])
            return 1
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
        if data.get("code") == 200 or data.get("success"):
            print("[wallet] 绑定完成。现在可以付款：python pay_generate.py pay")
            return 0
        print("[wallet] 绑定未成功。若是「请勿重复绑定」，说明该账号已在别处绑过。")
        return 1

    if args.action == "close":
        rc, data, raw = run_bot(bot, ["close-wallet"], args.timeout)
        if not data:
            print("[wallet] 官方 CLI 无 JSON 输出，原文：")
            print(raw[:2000])
            return 1
        for key in ("shortAccessUrl", "shortUrl", "accessUrl"):
            if data.get(key):
                print(f"{key}：{data[key]}")
        print("[wallet] 解绑后本环境可重新绑定另一个支付宝账号。")
        return 0 if rc == 0 else 1

    print(f"[wallet] 未知动作：{args.action}")
    return 1


def cmd_pay(args: argparse.Namespace) -> int:
    state = load_state(args.state_file)
    raw = state.get("payment_needed")
    if not raw:
        print("[pay] 状态文件里没有账单，请先跑 quote。")
        return 1

    bot = args.bot or find_bot()
    if not bot:
        print("[pay] 找不到 alipay-bot（买家侧官方支付 CLI）。先安装：")
        print("      npx -y @alipay/agent-payment@latest install")
        print("      装完重新执行本命令；若不在 PATH，用 --bot 指定完整路径。")
        return 1

    if not args.skip_wallet_check:
        wstate, _wdata = check_wallet_state(bot, min(args.timeout, 30))
        if wstate == "none":
            print("[pay] 当前环境的支付宝 AI 付钱包还没开通（code=500 未开通），"
                  "直接造付款码会扫出「请勿重复绑定」之类的开通页。")
            print(WALLET_TIP)
            print("先开通：python pay_generate.py wallet apply")
            return 2
        if wstate == "pending":
            print("[pay] 钱包已申请但还没完成授权，先把授权码绑上：")
            print("      python pay_generate.py wallet bind --code <6位授权码>")
            return 2

    tmp_dir = Path(tempfile.gettempdir())
    bill_file = tmp_dir / f".yemo-bill-{state.get('out_trade_no', 'tmp')}.txt"
    bill_file.write_text(raw, encoding="utf-8")
    try:
        os.chmod(bill_file, 0o600)
    except OSError:
        pass

    intent = args.intent or f"{state.get('goods_name') or '个人IP手绘生成'} {state.get('amount')}元"
    cmd = [
        bot, "402-buyer-pay",
        "-f", str(bill_file),
        "-r", state["url"],
        "-m", state.get("method", "GET"),
        "-i", intent,
        "-o", "json",
    ]
    print(f"[pay] 调支付宝官方 CLI 生成支付入口：{' '.join(cmd[:-2])} ...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f"[pay] 超时（{args.timeout}s）。未拿到支付入口，请重试。")
        return 1

    out = (proc.stdout or "").strip()
    data = None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        start = out.find("{")
        if start >= 0:
            try:
                data = json.loads(out[start:])
            except json.JSONDecodeError:
                data = None

    if not data:
        if proc.returncode != 0:
            print(f"[pay] 官方 CLI 退出码 {proc.returncode}")
            print((proc.stderr or "")[:2000])
            return 1
        print("[pay] 无法解析官方 CLI 输出，原文如下：")
        print(out[:3000])
        return 1

    if proc.returncode != 0 and data.get("success"):
        print(f"[pay] 官方 CLI 退出码 {proc.returncode}（但返回 success，继续解析）")

    if not data.get("success"):
        err = data.get("errorCode") or ""
        if err == "TRADE_PROGRESS_FAILED" or "买家和卖家不能相同" in (data.get("errorMsg") or ""):
            print("[pay] 支付宝拒绝：买家和卖家不能相同（errorCode=TRADE_PROGRESS_FAILED）。")
            print("      当前绑定的付款账号就是本技能的收款账号，自己买自己的东西不被允许。")
            print("      自测请换一个第三方账号：wallet close → wallet apply → 用那个号扫码 → "
                  "wallet bind --code <6位> → 再 pay。")
            return 3
        print("[pay] 生成支付入口失败：")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        return 1

    short = data.get("shortAccessUrl") or data.get("shortUrl")
    long_url = data.get("accessUrl")
    qr = (data.get("mediaPaths") or [None])[0]
    shake = data.get("outShakeNo")

    print()
    print("=== 支付入口（支付宝官方生成）===")
    print(f"商品    ：{data.get('goodsName') or state.get('goods_name')}")
    print(f"金额    ：{data.get('amount') or state.get('amount')} {state.get('currency', 'CNY')}")
    print(f"订单号  ：{state.get('out_trade_no')}")
    if short:
        print(f"付款链接：{short}")
    if long_url and long_url != short:
        print(f"完整链接：{long_url}")
    if qr:
        print(f"二维码  ：{qr}")
    print()
    print("把上面的链接或二维码给**本环境已绑定的那个支付宝账号**扫码付款。")
    print("注意：AI 付是一个智能体环境绑一个支付宝账号，换别的账号扫会出现"
          "「请勿重复绑定」——那不是故障，是绑定关系不匹配。")
    print("付款后执行：")
    print(f"  python pay_generate.py prove --state-file {args.state_file} --proof \"<Payment-Proof>\" --photo 你的照片.jpg")
    if shake:
        print(f"（官方凭证号 outShakeNo：{shake}）")
    return 0


def _photo_pixels(path: str) -> tuple[int, int] | None:
    """纯标准库读 PNG/JPEG 像素尺寸（买家环境不一定装了 Pillow）。

    存在的原因：2026-10-21 首单实测，买家 agent 把照片 base64 塞进行令参数，
    被长度上限压成约 480px 缩图，五官细节全丢。加这道体检，缩图当场现形。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(2)
            if head == b"\x89P":                       # PNG：IHDR 固定偏移
                f.seek(16)
                w, h = struct.unpack(">II", f.read(8))
                return (w, h)
            if head == b"\xff\xd8":                    # JPEG：扫 SOF 标记
                f.seek(2)
                while True:
                    byte = f.read(1)
                    if not byte:
                        return None
                    if byte != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":           # 跳过填充字节
                        marker = f.read(1)
                    if not marker:
                        return None
                    m = marker[0]
                    if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                        continue
                    if m == 0xDA:                      # 图像数据起点，后面没有 SOF 了
                        return None
                    seg = f.read(2)
                    if len(seg) < 2:
                        return None
                    length = struct.unpack(">H", seg)[0]
                    if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(1)                      # 采样精度
                        h, w = struct.unpack(">HH", f.read(4))
                        return (w, h)
                    f.seek(length - 2, 1)
    except OSError:
        return None
    return None


def cmd_prove(args: argparse.Namespace) -> int:
    state = load_state(args.state_file)
    proof = args.proof or _read_text(args.proof_file)
    if not proof:
        print("[prove] 缺少 Payment-Proof（用 --proof 或 --proof-file 提供）")
        return 1
    if not args.photo or not os.path.exists(args.photo):
        print("[prove] 缺少照片（用 --photo 指定本地照片路径）。出图需要照片作为身份参考。")
        return 1

    photo_bytes = Path(args.photo).read_bytes()
    if len(photo_bytes) > 8 * 1024 * 1024:
        print("[prove] 照片超过 8MB 上限，请压缩后重试。")
        return 1
    photo_b64 = base64.b64encode(photo_bytes).decode("ascii")

    # 照片像素体检：聊天软件转存、命令行内联都容易把图压成缩图，五官细节不够要提前喊
    px = _photo_pixels(args.photo)
    if px:
        long_side = max(px)
        print(f"[prove] 照片像素：{px[0]}x{px[1]}（长边 {long_side}px）")
        if long_side < 700:
            print("[prove] ⚠️ 照片长边不足 700px，像是被压缩过的缩图——五官细节会丢，"
                  "IP 可能不像本人。")
            print("[prove]    建议换手机相册原图（不要用聊天软件里转存的那张）。")
            print("[prove]    坚持用这张也能出图，但身份还原度会打折，且不重复扣费、可重换图重跑。")
    else:
        print("[prove] （没能读出照片像素尺寸，按原图继续上传）")

    # prove 用 POST：把 style + 照片 base64 放进 body，由统一 402 流水线验付并出图
    params = {"style": state.get("style"), "photo_b64": photo_b64}
    url = state["url"]
    status, headers, body = http_request(
        url, "POST", params, proof=proof.strip(), timeout=args.timeout
    )

    if status == 502 or (status >= 500 and "FULFILLMENT_CONFIRM_FAILED" in body):
        print("[prove] 履约确认失败（资源可能已生成）。请用同一 Payment-Proof 重试本命令；"
              "重试不会重新扣费。")
        print(body[:2000])
        return 2

    ok, reason = validate_delivery(
        status, headers, body, expect_out_trade_no=state.get("out_trade_no", ""),
        require_payment_validation=not args.no_require_validation,
    )
    if not ok:
        print(f"[prove] 交付校验未通过：{reason}")
        print(f"[prove] HTTP {status}")
        print(body[:2000])
        if status == 402:
            print("[prove] 收到 402：凭证无效或未完成支付，需要重新付款，不重试。")
        return 1

    payload = json.loads(body)
    print("=== 个人 IP 形象图已出具 ===")
    print_delivery(payload)
    print(f"\n交付校验：{reason}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    out_trade_no = args.out_trade_no
    if not out_trade_no:
        state = load_state(args.state_file)
        out_trade_no = state["out_trade_no"]
        url = state["url"]
        method = "GET"
        params = {"style": state.get("style")}
    else:
        url = args.base_url.rstrip("/") + RESOURCE_PATH
        method = "GET"
        params = {"style": args.style} if args.style else {}

    base = args.base_url.rstrip("/")
    dl_status, _, dl_body = http_request(f"{base}{DOWNLOAD_PATH}/{out_trade_no}", "GET", timeout=args.timeout)
    if dl_status == 200:
        print(f"[status] 资源已出具，可直接下载：{base}{DOWNLOAD_PATH}/{out_trade_no}")
        return 0
    print(f"[status] 资源查单：HTTP {dl_status}（尚未交付）")

    proof = args.proof or _read_text(args.proof_file)
    if not proof:
        print("[status] 无 Payment-Proof，无法重试；请确认是否已付款。")
        return 3

    status, headers, body = http_request(url, method, params, proof=proof.strip(), timeout=args.timeout)
    ok, reason = validate_delivery(
        status, headers, body, expect_out_trade_no=out_trade_no,
        require_payment_validation=not args.no_require_validation,
    )
    if not ok:
        print(f"[status] 同凭证重试未通过：{reason}（HTTP {status}）")
        print(body[:1000])
        return 1
    print("[status] 同凭证重试成功（幂等，未重复扣费）：")
    print_delivery(json.loads(body))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rc = cmd_quote(args)
    if rc != 0:
        return rc
    proof = args.proof or _read_text(args.proof_file)
    if not proof:
        print("[run] 未检测到 Payment-Proof，已停在付款确认前（不会自动发起真实付款）。")
        return 0
    return cmd_prove(args)


def print_delivery(payload: dict) -> None:
    content = payload.get("content") or {}
    base = DEFAULT_BASE_URL
    out_trade_no = payload.get("out_trade_no", "")
    dl = content.get("download_path") or f"{DOWNLOAD_PATH}/{out_trade_no}"
    print(f"风格        ：{content.get('style_name', '')} ({content.get('style', '')})")
    print(f"图片张数    ：{content.get('image_count', 1)} 张（一次付费一张）")
    print(f"尺寸        ：{content.get('size', '')}")
    print(f"下载地址    ：{base}{dl}")
    print(f"商户订单号  ：{out_trade_no}")
    print(f"支付宝流水  ：{payload.get('trade_no', '')}")
    print(f"已履约过    ：{payload.get('already_fulfilled', False)}")


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="夜秣个人IP生成器 · 按量付费调用方脚本")
    parser.add_argument("--base-url", default=os.environ.get("PAYSKILL_API_BASE", DEFAULT_BASE_URL))
    parser.add_argument("--method", default="GET", choices=["GET", "POST"])
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--sandbox", action="store_true", help="按沙箱规则校验 service_id")
    parser.add_argument("--proof", help="Payment-Proof 头值")
    parser.add_argument("--proof-file", help="保存 Payment-Proof 的文件")
    parser.add_argument("--no-require-validation", action="store_true", help="不强制要求 Payment-Validation 头")
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("quote", "只取 402 账单并展示（停在付款确认前）"),
        ("pay", "生成支付宝支付入口（二维码+链接），展示后等付款"),
        ("wallet", "钱包三步：check 查状态 / apply 开通 / bind 绑授权码 / close 解绑"),
        ("prove", "带 Payment-Proof 重发资源 URL（POST 附带照片），取回出图结果"),
        ("status", "查单：资源查单 + 同凭证幂等重试"),
        ("run", "一站式：quote →（有凭证才）prove"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--base-url", default=os.environ.get("PAYSKILL_API_BASE", DEFAULT_BASE_URL))
        sp.add_argument("--method", default="GET", choices=["GET", "POST"])
        sp.add_argument("--state-file", default=DEFAULT_STATE_FILE)
        sp.add_argument("--timeout", type=int, default=120)
        sp.add_argument("--sandbox", action="store_true")
        sp.add_argument("--proof")
        sp.add_argument("--proof-file")
        sp.add_argument("--no-require-validation", action="store_true")
        if name == "quote":
            sp.add_argument("--style", required=True, help="手绘风格编号，如 023（见 STYLE_CHOICES）")
        if name == "pay":
            sp.add_argument("--bot", help="alipay-bot 完整路径（不在 PATH 时用）")
            sp.add_argument("--intent", help="付款意图摘要，展示在支付页上")
            sp.add_argument("--skip-wallet-check", action="store_true",
                            help="跳过钱包开通状态检查（已确认绑好时用）")
        if name == "prove":
            sp.add_argument("--photo", required=True, help="本地人物照片路径（出图身份参考，仅内存解码）")
        if name == "wallet":
            sp.add_argument("action", nargs="?", default="check",
                            choices=["check", "apply", "bind", "close"],
                            help="check 查状态 / apply 拿开通入口 / bind 绑授权码 / close 解绑")
            sp.add_argument("--bot", help="alipay-bot 完整路径（不在 PATH 时用）")
            sp.add_argument("--code", help="支付宝 App 上拿到的 6 位授权码（bind 用）")
            sp.add_argument("--agent-name", help="申请开通时展示的智能体名字（apply 用）")
        if name == "status":
            sp.add_argument("--out-trade-no")
            sp.add_argument("--style", help="风格编号（与 quote 时一致）")
        sp.set_defaults(func=globals()[f"cmd_{name}"])
    parser.set_defaults(func=cmd_quote)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
