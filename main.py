import os
import dropbox
import requests
from playwright.sync_api import sync_playwright

# ===== Dropboxトークン更新 =====
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
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]

ACCESS_TOKEN = get_access_token()

# ===== Dropboxから取得 =====
dbx = dropbox.Dropbox(ACCESS_TOKEN)

folder_path = "/tenton"
files = dbx.files_list_folder(folder_path).entries
latest_file = sorted(files, key=lambda f: f.server_modified, reverse=True)[0]

# 保存ファイル名を固定
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
    page.fill("input[name='username']", USERNAME)
    page.fill("input[name='password']", PASSWORD)
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")

    # アップロード画面へ
    page.goto(UPLOAD_URL, wait_until="networkidle", timeout=120000)

    # 「アップロード」ボタンが出るまで待ってクリック
    page.wait_for_selector("button.ant-btn:has-text('アップロード')", timeout=60000)
    page.click("button.ant-btn:has-text('アップロード')")

    # ファイル選択 → アップロード確定
    page.set_input_files("input[type='file']", FILE_PATH)
    page.click("button.ant-btn.ant-btn-primary:has-text('アップロード')")

    # 一括確認処理
    page.wait_for_selector("input[type='checkbox']", timeout=30000)
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
