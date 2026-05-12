import os
import time
import json
import urllib.request
import urllib.parse
import re
from seleniumbase import SB

# ============================================================
# 配置加载
# ============================================================
_account = os.environ.get("MINESTRATOR_ACCOUNT", "").split(",")
EMAIL      = _account[0].strip() if len(_account) > 0 else ""
PASSWORD   = _account[1].strip() if len(_account) > 1 else ""
SERVER_ID  = os.environ.get("MINESTRATOR_SERVER_ID", "").strip()
AUTH_TOKEN = os.environ.get("MINESTRATOR_AUTH", "").strip()

# 强制指向 YAML 中 Xray 启动的本地代理端口
LOCAL_PROXY = "http://127.0.0.1:8080"
# 关键：防止代理干扰驱动程序内部通信
os.environ["no_proxy"] = "localhost,127.0.0.1"

_tg = os.environ.get("TG_BOT", "").strip()
TG_CHAT_ID = _tg.split(",")[0].strip() if _tg else ""
TG_TOKEN   = _tg.split(",")[1].strip() if _tg and "," in _tg else ""

LOGIN_URL  = "https://minestrator.com/connexion"
SERVER_URL = f"https://minestrator.com/my/server/{SERVER_ID}"
API_URL    = f"https://mine.sttr.io/server/{SERVER_ID}/poweraction"

# ============================================================
# 工具函数 (TG推送/时间等保持不变)
# ============================================================
def now_str():
    import datetime
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def send_tg(result, detail=''):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG_BOT，跳过推送")
        return
    msg = f"🎮 Minestrator 重启通知\n🕐 时间: {now_str()}\n📊 结果: {result}\n{detail}"
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": msg}).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15): print("📨 TG推送成功")
    except Exception as e: print(f"⚠️ TG推送失败：{e}")

# ============================================================
# Turnstile 脚本与 API 发送 (保持不变)
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
        window.__cf_turnstile_token__ = d.token;
    });
})();
"""

def inject_listener(sb):
    try: sb.execute_script(INJECT_TOKEN_LISTENER_JS); print("📡 监听器已注入")
    except: pass

def wait_for_token(sb, timeout=60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            token = sb.execute_script("return window.__cf_turnstile_token__ || '';")
            if token and len(token) > 50: return token
        except: pass
        time.sleep(1)
    return ''

def send_restart(sb, token: str) -> bool:
    token_js = json.dumps(token)
    script = (
        "var done = arguments[0];"
        'fetch("' + API_URL + '", {'
        '  method: "PUT",'
        '  headers: {'
        '    "Authorization": "' + AUTH_TOKEN + '",'
        '    "Content-Type": "application/json",'
        '    "X-Requested-With": "XMLHttpRequest"'
        '  },'
        '  body: JSON.stringify({poweraction: "restart", turnstile_token: ' + token_js + '})'
        '})'
        '.then(function(r){ return r.json(); })'
        '.then(function(data){ done({ok: true, data: data}); })'
        '.catch(function(err){ done({ok: false, error: err.toString()}); });'
    )
    try:
        result = sb.execute_async_script(script)
        return result.get("ok") and result.get("data", {}).get("api", {}).get("code") == 200
    except: return False

# ============================================================
# 主流程 (核心修改处)
# ============================================================
def run_script():
    print("🔧 启动浏览器（强制代理模式）...")

    # 关键参数：解决 GitHub Actions 下的 Service Unavailable 报错
    sb_kwargs = {
        "uc": True,
        "test": True,
        "headless": True,
        "proxy": LOCAL_PROXY,
        "chromium_arg": "--no-sandbox,--disable-dev-shm-usage", # 解决资源限制报错
    }

    with SB(**sb_kwargs) as sb:
        print(f"🚀 浏览器已通过代理 {LOCAL_PROXY} 启动")

        # IP 验证
        try:
            sb.open("https://api.ipify.org")
            print(f"✅ 出口 IP: {sb.get_text('body')}")
        except: print("⚠️ IP 验证失败")

        # 登录流程
        print("🔑 登录中...")
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=4)
        try:
            sb.wait_for_element_visible("input[name='pseudo']", timeout=20)
            sb.type("input[name='pseudo']", EMAIL)
            sb.type("input[name='password']", PASSWORD)
            sb.click("button[type='submit']")
            time.sleep(5)
        except Exception as e:
            sb.save_screenshot("error.png")
            print(f"❌ 登录交互异常: {e}")
            return

        # 跳转与重启
        print(f"🔃 跳转管理页: {SERVER_URL}")
        sb.open(SERVER_URL)
        time.sleep(5)
        
        inject_listener(sb)
        token = wait_for_token(sb, timeout=60)
        
        if token and send_restart(sb, token):
            print("✅ 重启指令发送成功！")
            send_tg("✅ 重启成功！")
        else:
            print("❌ 重启失败")
            sb.save_screenshot("fail.png")
            send_tg("❌ 重启失败")

if __name__ == "__main__":
    run_script()
