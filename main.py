import os
import sys
import time
import json
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --------- 設定（環境変数） ---------
APP_KEY = os.environ.get("DROPBOX_APP_KEY")
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")
TENTON_USER = os.environ.get("TENTON_USER")
TENTON_PASS = os.environ.get("TENTON_PASS")

LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"
FOLDER_PATH = "/tenton"
FILE_PATH = "latest_report.txt"

# --------- Dropbox: refresh -> access token ---------
def get_access_token():
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def download_latest_from_dropbox(access_token, folder_path, out_path):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    r = requests.post(
        "https://api.dropboxapi.com/2/files/list_folder",
        headers=headers,
        json={"path": folder_path},
        timeout=30,
    )
    r.raise_for_status()
    entries = r.json().get("entries", [])
    latest = sorted(entries, key=lambda e: e["server_modified"], reverse=True)[0]
    path_lower = latest["path_lower"]

    dl_headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({"path": path_lower}),
    }
    r2 = requests.post("https://content.dropboxapi.com/2/files/download", headers=dl_headers, timeout=60)
    r2.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r2.content)
    print(f"Downloaded: {latest.get('name')}")

# --------- Playwright helpers ---------
def safe_click_by_index(page, selector, idx=0, timeout=60000):
    page.wait_for_selector(selector, timeout=timeout)
    els = page.query_selector_all(selector)
    if len(els) <= idx:
        raise RuntimeError(f"{selector} の index {idx} が見つかりません")
    els[idx].click()
    return els[idx]

def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except PWTimeout as e:
        raise RuntimeError(f"Timeout waiting for selector '{selector}'") from e

# --------- Main ---------
def main():
    token = get_access_token()
    download_latest_from_dropbox(token, FOLDER_PATH, FILE_PATH)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ログイン
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=180000)
        page.fill("#username", TENTON_USER)
        page.fill("#password", TENTON_PASS)
        safe_click_by_index(page, "button.login-button", 0)
        safe_wait_selector(page, "span.ant-pro-drop-down", timeout=180000)
        print("✅ ログイン成功")

        # 言語切替（2番目の li をクリック = 日本語）
        safe_click_by_index(page, "span.ant-pro-drop-down", 0)
        safe_wait_selector(page, "li[role='menuitem']", timeout=60000)
        safe_click_by_index(page, "li[role='menuitem']", 1)
        time.sleep(2)
        print("✅ 言語を日本語に切替")

        # アップロードページ
        page.goto(UPLOAD_URL)
        safe_wait_selector(page, "button.ant-btn.ant-btn-primary", timeout=180000)
        print("✅ アップロード画面表示確認")

        # アップロードモーダルを開く
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 0)
        print("✅ アップロードモーダルを開いた")

        # 店舗種類 / 店舗名セレクタを待機
        safe_wait_selector(page, "div.ant-select-selector", timeout=120000)
        print("✅ 店舗選択UIを検出")

        # --- 以降の処理（店舗種類→店舗名→ファイル添付→一括確認 etc.） ---
        # ここは前回のフローと同じ。必要なら次のステップで統合します。

        browser.close()

if __name__ == "__main__":
    main()
