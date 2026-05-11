import os
import time
import json
import urllib.request
import urllib.parse
import urllib.error
import re
from seleniumbase import SB

_account = os.environ["MINESTRATOR_ACCOUNT"].split(",")
EMAIL = _account[0].strip()
PASSWORD = _account[1].strip()
SERVER_ID = os.environ.get("MINESTRATOR_SERVER_ID", "").strip()
AUTH_TOKEN = os.environ.get("MINESTRATOR_AUTH", "").strip()

_proxy_flag = os.environ.get("GOST_PROXY", "").strip()
XRAY_CONFIG = os.environ.get("XRAY_CONFIG_JSON", "").strip()
LOCAL_PROXY = "127.0.0.1:8080"

_tg = os.environ.get("TG_BOT", "").strip()
TG_CHAT_ID = _tg.split(",")[0].strip() if _tg else ""
TG_TOKEN = _tg.split(",")[1].strip() if _tg and "," in _tg else ""

LOGIN_URL = "https://minestrator.com/connexion"
SERVER_URL = f"https://minestrator.com/my/server/{SERVER_ID}"
API_URL = f"https://mine.sttr.io/server/{SERVER_ID}/poweraction"


# ============================================================
# 工具函数
# ============================================================

def now_str():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask_ip_text(text: str) -> str:
    return re.sub(r"(\d+\.\d+\.\d+\.)\d+", r"\1xx", text or "")


def test_local_proxy(proxy_hostport="127.0.0.1:8080", timeout=10):
    proxy_url = f"http://{proxy_hostport}"
    target_url = "https://api.ipify.org/?format=json"
    proxy_handler = urllib.request.ProxyHandler({
        "http": proxy_url,
        "https": proxy_url,
    })
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            print(f"✅ 本地代理可用：{mask_ip_text(body)}")
            return True, body
    except Exception as e:
        print(f"⚠️ 本地代理不可用：{e}")
        return False, ""


def should_use_proxy():
    print(f"ℹ️ GOST_PROXY 开关状态：{'已设置' if _proxy_flag else '未设置'}")
    print(f"ℹ️ XRAY_CONFIG_JSON 状态：{'已设置' if XRAY_CONFIG else '未设置'}")
    ok, _ = test_local_proxy(LOCAL_PROXY, timeout=10)
    return ok


# ============================================================
# TG 推送（可选）
# ============================================================

def send_tg(result, detail=""):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG_BOT，跳过推送")
        return
    msg = (
        f"🎮 Minestrator 重启通知\n"
        f"🕐 运行时间: {now_str()}\n"
        f"🖥 服务器: 🇫🇷 Minestrator-FR\n"
        f"📊 结果: {result}\n"
        f"{detail}"
    )
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT_ID,
        "text": msg
    }).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15):
            print("📨 TG推送成功")
    except Exception as e:
        print(f"⚠️ TG推送失败：{e}")


# ============================================================
# Invisible Turnstile：注入监听器，轮询等待 token
# ============================================================

INJECT_TOKEN_LISTENER_JS = """
(function() {
    if (window.__cf_token_listener_injected__) return;
    window.__cf_token_listener_injected__ = true;
    window.__cf_turnstile_token__ = '';

    window.addEventListener('message', function(e) {
        if (!e.origin || e.origin.indexOf('cloudflare.com') === -1) return;
        var d = e.data;
        if (!d || d.event !== 'complete' || !d.token) return;

        console.log('[TokenCapture] complete, token length:', d.token.length);
        window.__cf_turnstile_token__ = d.token;

        var inputs = document.querySelectorAll(
            'input[name="cf-turnstile-response"], input[name="cf_turnstile_response"]'
        );
        for (var i = 0; i < inputs.length; i++) {
            try {
                var nativeSet = Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype, 'value'
                ).set;
                nativeSet.call(inputs[i], d.token);
                inputs[i].dispatchEvent(new Event('input', {bubbles: true}));
                inputs[i].dispatchEvent(new Event('change', {bubbles: true}));
            } catch(err) {
                inputs[i].value = d.token;
            }
        }
    });
    console.log('[TokenCapture] listener injected');
})();
"""

READ_TOKEN_JS = "(function(){ return window.__cf_turnstile_token__ || ''; })()"


def inject_listener(sb):
    try:
        sb.execute_script(INJECT_TOKEN_LISTENER_JS)
        print("📡 Turnstile 监听器已注入")
    except Exception as e:
        print(f"⚠️ 监听器注入失败：{e}")


def wait_for_token(sb, timeout=60) -> str:
    print(f"⏳ 等待 Turnstile Token 自动生成（最多 {timeout} 秒）...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            token = sb.execute_script(READ_TOKEN_JS)
            if token and len(token) > 50:
                print(f"✅ Token 已捕获（长度 {len(token)}）")
                return token
        except Exception:
            pass

        try:
            token = sb.execute_script("""
                (function(){
                    var inp = document.querySelector('input[name="cf-turnstile-response"]');
                    return (inp && inp.value && inp.value.length > 50) ? inp.value : '';
                })()
            """)
            if token:
                print(f"✅ Token 从 input 读取（长度 {len(token)}）")
                return token
        except Exception:
            pass

        time.sleep(1)

    print("❌ 等待 Token 超时")
    return ""


# ============================================================
# API：通过浏览器 fetch 发送重启指令（携带登录 Cookie）
# ============================================================

def send_restart(sb, token: str) -> bool:
    token_js = json.dumps(token)
    script = (
        "var done = arguments[0];"
        'fetch("' + API_URL + '", {'
        '  
