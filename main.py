import os
import dropbox
from playwright.sync_api import sync_playwright

# ===== Dropboxから取得 =====
DBX_TOKEN = os.environ["DROPBOX_TOKEN"]
dbx = dropbox.Dropbox(DBX_TOKEN)

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
USERNAME = os.environ.get("TENTON_USER", "小山充寛")
PASSWORD = os.environ.get("TENTON_PASS", "123456")
LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ログインページへ
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)

    # ユーザー名・パスワード入力
    page.wait_for_selector("input[name='account']", timeout=60000)
    page.fill("input[name='account']", USERNAME)

    page.wait_for_selector("input[name='password']", timeout=60000)
    page.fill("input[name='password']", PASSWORD)

    # ログインボタン押下
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")

    # アップロード画面へ
    page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_load_state("networkidle")

    # 「アップロード」ボタン → ファイル選択 → 確定
    page.click("button.ant-btn.ant-btn-primary")  # アップロードモーダルを開く
    page.set_input_files("input[type='file']", FILE_PATH)
    page.click("button.ant-btn.ant-btn-primary:has-text('アップロード')")

    # 一括確認
    page.wait_for_selector("input[type='checkbox']")
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
