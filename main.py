import os
import requests
from playwright.sync_api import sync_playwright

# ===== Dropbox 認証 =====
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]

def get_access_token():
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }
    res = requests.post(url, data=data)
    res.raise_for_status()
    return res.json()["access_token"]

ACCESS_TOKEN = get_access_token()

# 最新ファイル取得
folder_path = "/tenton"
res = requests.post(
    "https://api.dropboxapi.com/2/files/list_folder",
    headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
    json={"path": folder_path},
)
res.raise_for_status()
entries = res.json()["entries"]
latest_file = sorted(entries, key=lambda f: f["server_modified"], reverse=True)[0]

FILE_PATH = "latest_report.txt"
res = requests.post(
    "https://content.dropboxapi.com/2/files/download",
    headers={
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Dropbox-API-Arg": f'{{"path": "{latest_file["path_lower"]}"}}',
    },
)
res.raise_for_status()
with open(FILE_PATH, "wb") as f:
    f.write(res.content)
print(f"Downloaded: {latest_file['name']}")

# ===== Tenton アップロード =====
USERNAME = os.environ["TENTON_USER"]
PASSWORD = os.environ["TENTON_PASS"]
LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ログイン
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)
    page.fill("input#username", USERNAME)
    page.fill("input#password", PASSWORD)
    page.click("button.login-button")
    page.wait_for_load_state("networkidle")
    print("✅ ログイン成功")

    # 日本語に切替（存在すれば）
    try:
        page.click("span.ant-pro-drop-down")
        page.click("li:has-text('日本語'), li:has-text('日语')")
        print("✅ UI を日本語に切替")
    except:
        print("⚠ 言語切替スキップ（既に日本語の可能性あり）")

    # アップロードページへ
    page.goto(UPLOAD_URL)
    page.wait_for_load_state("networkidle")

    # アップロードモーダルを開く
    page.click("button.ant-btn.ant-btn-primary")

    # 店舗種類選択（アマゾン）
    page.click("div.ant-select-selector >> nth=0")
    page.click("div[title='アマゾン']")

    # 店舗名選択（アイプロダクト）
    page.click("div.ant-select-selector >> nth=1")
    page.click("div[title='アイプロダクト']")

    # ファイル選択
    page.set_input_files("input[type='file']", FILE_PATH)

    # 青い「アップロード」ボタン押下
    page.click("button.ant-btn.ant-btn-primary")

    print("✅ ファイルアップロード完了")

    browser.close()
