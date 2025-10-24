import os
import json
import dropbox
import requests
import time
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from googletrans import Translator

DROPBOX_PATH = "/tenton"
STATE_FILE = "state.json"
translator = Translator()
JST = timezone(timedelta(hours=9))

# --- 翻訳ユーティリティ ---
def translate_to_japanese(text):
    if not text:
        return text
    try:
        result = translator.translate(text, src='zh-cn', dest='ja')
        return result.text
    except Exception as e:
        return f"[翻訳失敗: {e}] 原文: {text}"

# --- 結果要約（同一メッセージをグルーピング） ---
def summarize_orders(raw_text):
    try:
        data = json.loads(raw_text)
        result = data.get("result", {})
        if not isinstance(result, dict):
            msg = data.get("msg", raw_text)
            return translate_to_japanese(msg)

        grouped = {}
        for order_no, msg in result.items():
            jp_msg = translate_to_japanese(msg)
            grouped.setdefault(jp_msg, []).append(order_no)

        lines = []
        for msg, orders in grouped.items():
            order_list = ", ".join(orders[:10])
            more = f" …他{len(orders)-10}件" if len(orders) > 10 else ""
            lines.append(f"{msg}：{order_list}{more}")
        return "\n".join(lines)
    except Exception:
        return translate_to_japanese(raw_text)

# --- Chatwork通知 ---
def notify_chatwork(report_time, upload_log, confirm_log):
    token = os.environ.get("CHATWORK_TOKEN")
    room_id = "366280327"  # 固定ルームID（#!rid366280327）
    to_account_id = "10110346"  # 脇山友香(Yuka Wakiyama)さん
    to_display = "脇山友香(Yuka Wakiyama)さん"

    if not token or not room_id:
        print("⚠️ Chatwork通知スキップ（環境変数未設定）")
        return

    now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')

    # ステータス分類
    upload_status = "✅ 成功" if "HTTP 200" in upload_log else "❌ 失敗"
    confirm_status = "✅ 成功" if "HTTP 200" in confirm_log else "❌ 失敗"

    # 翻訳・要約
    upload_summary = summarize_orders(upload_log)
    confirm_summary = summarize_orders(confirm_log)

    # 通知本文（Toメンション付き）
    body = f"""[To:{to_account_id}] {to_display}
🏗️【テントン自動処理レポート】

📦 対象データ：
Amazon注文レポート作成時刻：{report_time}

📤 アップロード結果：
{upload_status}
{upload_summary}

🚀 一括確認結果：
{confirm_status}
{confirm_summary}

⏰ 実行完了：{now_jst}（JST）
"""

    # Chatwork送信
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    headers = {"X-ChatWorkToken": token}
    try:
        res = requests.post(url, headers=headers, data={"body": body})
        print(f"📨 Chatwork通知送信結果: {res.status_code}")
    except Exception as e:
        print(f"❌ Chatwork通知エラー: {e}")

# --- Dropbox 認証 ---
def refresh_access_token():
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": os.environ["DROPBOX_REFRESH_TOKEN"],
        "client_id": os.environ["DROPBOX_APP_KEY"],
        "client_secret": os.environ["DROPBOX_APP_SECRET"],
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]

def download_latest_file():
    access_token = refresh_access_token()
    dbx = dropbox.Dropbox(oauth2_access_token=access_token)
    entries = dbx.files_list_folder(DROPBOX_PATH).entries
    latest = max(entries, key=lambda e: e.server_modified)
    _, res = dbx.files_download(latest.path_lower)
    fname = f"Downloaded: {latest.name}"
    with open(fname, "wb") as f:
        f.write(res.content)
    print(fname)
    return os.path.abspath(fname), latest.name

# --- Playwright util ---
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"FATAL: Timeout waiting for selector '{selector}'") from e

# --- Login ---
def login_and_save_state(browser, username, password):
    context = browser.new_context()
    page = context.new_page()
    print("🌐 初回ログイン...")
    page.goto("http://8.209.213.176/login", timeout=300000)
    page.wait_for_selector("#username", timeout=180000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button.login-button")
    page.wait_for_load_state("networkidle", timeout=180000)

    local_data = page.evaluate("() => JSON.stringify(window.localStorage)")
    print("💾 localStorage内容:", local_data)
    print("✅ ログイン成功、state.jsonへ保存中...")
    context.storage_state(path=STATE_FILE)
    context.close()
    print("💾 state.json 保存完了")

# --- メイン ---
def main():
    FILE_PATH, FILE_NAME = download_latest_file()

    # ▼ UTC → JST (+9h) に補正
    base_name = FILE_NAME.replace(".txt", "").replace("Downloaded: ", "")
    try:
        utc_dt = datetime.strptime(base_name, "%Y-%m-%d %H:%M:%S")
        report_time = (utc_dt + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        report_time = base_name

    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    upload_log = ""
    confirm_log = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            # セッション復元 or ログイン
            if os.path.exists(STATE_FILE):
                print("✅ 保存済みセッションを使用")
                context = browser.new_context(storage_state=STATE_FILE)
            else:
                login_and_save_state(browser, USERNAME, PASSWORD)
                context = browser.new_context(storage_state=STATE_FILE)

            page = context.new_page()
            page.goto("http://8.209.213.176/fundamentalData/goodInfo", timeout=300000)
            print("✅ アップロード画面へアクセス完了")

            # 言語切替
            try:
                page.click("span.ant-pro-drop-down")
                safe_wait_selector(page, "li[role='menuitem']")
                items = page.query_selector_all("li[role='menuitem']")
                if len(items) >= 2:
                    items[1].click()
                print("✅ 言語を日本語に切替")
            except Exception as e:
                print("⚠️ 言語切替失敗:", e)

            # Access Token
            print("🔑 localStorageからAccess-Token取得中...")
            access_token = page.evaluate("() => localStorage.getItem('Access-Token')")
            if not access_token:
                raise RuntimeError("❌ localStorageにAccess-Tokenが見つかりませんでした")
            access_token = access_token.strip('"')
            print(f"✅ Access-Token取得成功: {access_token[:20]}...")

            # アップロード
            api_url = "http://8.209.213.176/api/back/order/importOrderYmx"
            headers = {"Authorization": access_token, "Accept": "application/json, text/plain, */*"}
            data = {"type": "1", "shopId": "6a7aaaf6342c40879974a8e9138e3b3b"}

            print("📤 サーバーに直接POST送信中...")
            with open(FILE_PATH, "rb") as f:
                files = {"file": (os.path.basename(FILE_PATH), f, "text/plain")}
                res = requests.post(api_url, headers=headers, data=data, files=files)

            upload_log = f"HTTP {res.status_code}\n{res.text[:500]}"
            print("📡 レスポンスコード:", res.status_code)
            print("📄 レスポンス内容:", res.text[:500])

            # 一括確認
            print("🚀 一括確認フェーズ開始...")
            time.sleep(40)  # 登録反映待機（非同期登録の完了を待つ）
            list_url = "http://8.209.213.176/api/back/orderManagement/orderInfo"
            res_list = requests.post(
                list_url,
                headers={
                    "Authorization": access_token,
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                },
                json={"size": 200, "current": 1},
                timeout=120,
            )

            if res_list.status_code != 200:
                confirm_log = f"❌ 注文一覧取得失敗: HTTP {res_list.status_code}\n{res_list.text[:200]}"
            else:
                data = res_list.json()
                result = data.get("result", {})
                records = result.get("records", [])
                order_ids = [r.get("id") for r in records if isinstance(r, dict)]
                if not order_ids:
                    confirm_log = "⚠️ 一括確認対象なし"
                else:
                    confirm_url = "http://8.209.213.176/api/back/orderManagement/orderInfo/batchConfirmation"
                    confirm_res = requests.post(
                        confirm_url,
                        headers={
                            "Authorization": access_token,
                            "Accept": "application/json, text/plain, */*",
                            "Content-Type": "application/json",
                        },
                        json=order_ids,
                        timeout=120,
                    )
                    confirm_log = f"HTTP {confirm_res.status_code}\n{confirm_res.text[:500]}"

        except Exception as e:
            upload_log = upload_log or f"❌ 例外発生: {e}"
            confirm_log = confirm_log or "未実施（例外発生により中断）"
        finally:
            browser.close()
            notify_chatwork(report_time, upload_log, confirm_log)

if __name__ == "__main__":
    main()
