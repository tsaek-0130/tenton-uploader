import os
import json
import dropbox
import requests
import time
from playwright.sync_api import sync_playwright

DROPBOX_PATH = "/tenton"
STATE_FILE = "state.json"

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
    return os.path.abspath(fname)

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
    FILE_PATH = download_latest_file()
    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

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

        # --- 言語切替 ---
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # --- ✅ localStorageからAccess-Token取得 ---
        print("🔑 localStorageからAccess-Token取得中...")
        access_token = page.evaluate("() => localStorage.getItem('Access-Token')")
        if not access_token:
            raise RuntimeError("❌ localStorageにAccess-Tokenが見つかりませんでした")

        access_token = access_token.strip('"')
        print(f"✅ Access-Token取得成功: {access_token[:20]}...")

        # --- ✅ API送信（导入） ---
        api_url = "http://8.209.213.176/api/back/order/importOrderYmx"
        headers = {
            "Authorization": access_token,
            "Accept": "application/json, text/plain, */*",
        }
        data = {
            "type": "1",  # 店铺类型 (1 = 亚马逊)
            "shopId": "6a7aaaf6342c40879974a8e9138e3b3b"  # 店铺名称 (アイプロダクト)
        }

        print("📤 サーバーに直接POST送信中...")
        with open(FILE_PATH, "rb") as f:
            files = {"file": (os.path.basename(FILE_PATH), f, "text/plain")}
            res = requests.post(api_url, headers=headers, data=data, files=files)

        print("📡 レスポンスコード:", res.status_code)
        print("📄 レスポンス内容:", res.text[:500])

        if res.status_code == 200:
            print("✅ アップロード成功（403・401完全回避・店铺类型OK）")
        else:
            print("❌ アップロード失敗。レスポンスを確認してください。")

        # 👇 ここから次フェーズで「一括確認処理」を追加予定 👇

        browser.close()

if __name__ == "__main__":
    main()
