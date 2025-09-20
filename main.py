import os
import requests
import dropbox
from playwright.sync_api import sync_playwright

# ===== Dropbox 認証 =====
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]

def get_access_token():
    resp = requests.post(
        "https://api.dropboxapi.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
        },
        auth=(APP_KEY, APP_SECRET),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

DBX_TOKEN = get_access_token()
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

# ===== テントンにアップロード処理（Playwright） =====
USERNAME = "小山充寛"
PASSWORD = "123456"
LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ログイン
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)
    page.fill("input#username", USERNAME)
    page.fill("input#password", PASSWORD)
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")

    # アップロード画面へ
    page.goto(UPLOAD_URL)
    page.wait_for_load_state("networkidle")

    # 「アップロード」ボタンをクリック
    page.click("button:has-text('アップロード')")
    page.set_input_files("input[type='file']", FILE_PATH)
    page.click("button.ant-btn.ant-btn-primary:has-text('アップロード')")

    # 一括確認
    page.wait_for_selector("input[type='checkbox']")
    page.click("input[type='checkbox']")
    page.click("a.ant-btn.ant-btn-primary:has-text('一括確認')")
    page.click("button.ant-btn.ant-btn-primary.ant-btn-sm:has-text('確 認')")

    # エラーチェック
    try:
        error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
        print("エラー内容:", error_dialog.inner_text())
    except:
        print("エラーなし、正常に完了しました。")

    browser.close()
