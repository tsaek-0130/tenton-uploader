import os
import requests
import dropbox
from playwright.sync_api import sync_playwright

# ===== Dropbox アクセストークン更新 =====
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]

def refresh_access_token():
    resp = requests.post(
        "https://api.dropboxapi.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id": APP_KEY,
            "client_secret": APP_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

DBX_TOKEN = refresh_access_token()
dbx = dropbox.Dropbox(DBX_TOKEN)

# ===== 最新ファイル取得 =====
folder_path = "/tenton"
files = dbx.files_list_folder(folder_path).entries
latest_file = sorted(files, key=lambda f: f.server_modified, reverse=True)[0]

FILE_PATH = "latest_report.txt"
_, res = dbx.files_download(latest_file.path_lower)
with open(FILE_PATH, "wb") as f:
    f.write(res.content)
print(f"Downloaded: {latest_file.name}")

# ===== テントンにアップロード =====
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
    page.click("button.login-button")
    page.wait_for_load_state("networkidle")

    # === 言語を日本語に切り替え ===
    try:
        page.wait_for_selector("span.ant-pro-drop-down", timeout=10000)
        page.click("span.ant-pro-drop-down")
        page.get_by_text("日语 日本語", exact=True).click()
        page.wait_for_timeout(2000)
        print("日本語に切り替え完了")
    except Exception as e:
        print("言語切替スキップ:", e)

    # アップロード画面へ
    page.goto(UPLOAD_URL)
    page.wait_for_load_state("networkidle")

    # 「アップロード」モーダルを開く
    page.click("button:has-text('アップロード')")
    page.set_input_files("input[type='file']", FILE_PATH)
    page.click("button.ant-btn.ant-btn-primary:has-text('アップロード')")

    # 一括確認
    page.wait_for_selector("input[type='checkbox']", timeout=60000)
    page.click("input[type='checkbox']")  # 全選択
    page.click("a.ant-btn.ant-btn-primary:has-text('一括確認')")
    page.click("button.ant-btn.ant-btn-primary.ant-btn-sm:has-text('確 認')")

    # エラーチェック
    try:
        error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
        print("エラー内容:", error_dialog.inner_text())
    except:
        print("エラーなし、正常に完了しました。")

    browser.close()
