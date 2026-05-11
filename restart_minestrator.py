import os
import time
import json
import urllib.request
import urllib.parse
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
            } catch (err) {
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


def send_restart(sb, token: str) -> bool:
    payload = json.dumps({
        "poweraction": "restart",
        "turnstile_token": token
    })
    script = f"""
        var done = arguments[0];
        fetch("{API_URL}", {{
            method: "PUT",
            headers: {{
                "Authorization": "{AUTH_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            }},
            body: JSON.stringify({payload})
        }})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{ done({{ok: true, data: data}}); }})
        .catch(function(err) {{ done({{ok: false, error: err.toString()}}); }});
    """
    try:
        result = sb.execute_async_script(script)
        print(f"📡 API响应：{result}")
        if result.get("ok") and result.get("data", {}).get("api", {}).get("code") == 200:
            print("✅ 重启指令已成功送达！")
            return True
        print(f"❌ API返回异常：{result}")
        return False
    except Exception as e:
        print(f"⚠️ API请求异常：{e}")
        return False


def run_script():
    print("🔧 启动浏览器前检查代理...")

    use_proxy = should_use_proxy()

    sb_kwargs = dict(uc=True, test=True)
    if use_proxy:
        sb_kwargs["proxy"] = LOCAL_PROXY
        print(f"🌐 已启用本地代理：{LOCAL_PROXY}")
    else:
        print("ℹ️ 本地代理不可用，直连运行")

    print("🔧 启动浏览器...")
    with SB(**sb_kwargs) as sb:
        print("🚀 浏览器就绪！")

        print("🌐 验证出口IP...")
        try:
            sb.open("https://api.ipify.org/?format=json")
            ip_text = mask_ip_text(sb.get_text("body"))
            print(f"✅ 出口IP确认：{ip_text}")
        except Exception as e:
            print(f"⚠️ IP验证超时或失败，跳过：{e}")

        print("🔑 打开登录页面...")
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
        time.sleep(3)

        print("✏️ 填写账号密码...")
        
