import os
import requests
import dropbox
from playwright.sync_api import sync_playwright

# ===== Dropbox トークンリフレッシュ =====
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]

def refresh_access_token():
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]

ACCESS_TOKEN = refresh_access_token()
dbx = dropbox.Dropbox(ACCESS_TOKEN)

# ===== Dropbox から最新ファイル取得 =====
folder_path = "/tenton"
files = dbx.files_list_folder(folder_path).entries
latest_file = sorted(files, key=lambda f: f.server_modified, reverse=True)[0]

FILE_PATH = "latest_report.txt"
_, res = dbx.files_download(latest_file.path_lower)
with open(FILE_PATH, "wb") as f:
    f.write(res.content)
print(f"Downloaded: {latest_file.name}")

# ===== テントンへアップロード =====
USERNAME = os.environ["TENTON_USER"]
PASSWORD = os.environ["TENTON_PASS"]
LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ログイン
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click("button.login-button")  # class 固定
    page.wait_for_load_state("networkidle")

    # UI 言語を日本語に統一（安定のため）
    try:
        page.wait_for_selector("span.ant-pro-drop-down", timeout=60000)
        page.click("span.ant-pro-drop-down")
        # ドロップダウン → 常に 2 番目の option をクリック（日本語）
        page.wait_for_selector("li[role='menuitem']", timeout=60000)
        items = page.query_selector_all("li[role='menuitem']")
        if len(items) >= 2:
            items[1].click()
        print("✅ UI を日本語に切り替えました")
    except Exception as e:
        print("⚠️ 言語切り替えに失敗しました:", e)

    # アップロード画面へ
    page.goto(UPLOAD_URL)
    page.wait_for_load_state("networkidle")

    # 「アップロード」ボタン → 最初の .ant-btn-primary を押す
    page.wait_for_selector("button.ant-btn.ant-btn-primary", timeout=60000)
    buttons = page.query_selector_all("button.ant-btn.ant-btn-primary")
    if buttons:
        buttons[0].click()

    # ファイル選択
    page.set_input_files("input[type='file']", FILE_PATH)

    # モーダルの「アップロード」ボタン → 2 番目の .ant-btn-primary を押す
    page.wait_for_selector("button.ant-btn.ant-btn-primary", timeout=60000)
    buttons = page.query_selector_all("button.ant-btn.ant-btn-primary")
    if len(buttons) > 1:
        buttons[1].click()

    # 一括確認
    page.wait_for_selector("input[type='checkbox']", timeout=60000)
    page.click("input[type='checkbox']")  # 全選択
    page.click("a.ant-btn.ant-btn-primary")  # 一括確認ボタン
    page.click("button.ant-btn.ant-btn-primary.ant-btn-sm")  # 確認ボタン

    # エラーチェック
    try:
        error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
        print("エラー内容:", error_dialog.inner_text())
    except:
        print("エラーなし、正常に完了しました。")

    browser.close()
