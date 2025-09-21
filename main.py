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

# 最新ファイルを取得
headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
folder_path = "/tenton"
res = requests.post(
    "https://api.dropboxapi.com/2/files/list_folder",
    headers=headers,
    json={"path": folder_path},
)
res.raise_for_status()
files = res.json()["entries"]
latest_file = sorted(files, key=lambda f: f["server_modified"], reverse=True)[0]

# ダウンロード
res = requests.post(
    "https://content.dropboxapi.com/2/files/download",
    headers={
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Dropbox-API-Arg": str({"path": latest_file["path_lower"]}).replace("'", '"'),
    },
)
res.raise_for_status()

FILE_PATH = "latest_report.txt"
with open(FILE_PATH, "wb") as f:
    f.write(res.content)
print(f"Downloaded: {latest_file['name']}")

# ===== Tenton アップロード処理 =====
USERNAME = os.environ["TENTON_USER"]
PASSWORD = os.environ["TENTON_PASS"]
LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ログイン
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=180000)
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click("button.login-button")
    page.wait_for_load_state("networkidle")
    print("✅ ログイン成功")

    # ===== 言語を日本語に切替 =====
    try:
        page.click("span.ant-pro-drop-down")
        page.click("li:has-text('日本語'), li:has-text('日语')")
        print("✅ UI を日本語に切替")

        # 「アップロード」が出るまで最大3分待機
        page.wait_for_selector("text=アップロード", timeout=180000)
        print("✅ 日本語UIを確認しました")
    except Exception as e:
        print("❌ 言語切替失敗:", e)
        raise

    # アップロード画面
    page.goto(UPLOAD_URL)
    page.wait_for_load_state("networkidle")

    # 店舗種類・店舗名が「アマゾン」「アイプロダクト」になっているか確認
    page.wait_for_selector("div[title='アマゾン']")
    page.wait_for_selector("div[title='アイプロダクト']")

    # アップロード処理
    page.click("button.ant-btn.ant-btn-primary")  # モーダル開く
    page.set_input_files("input[type='file']", FILE_PATH)
    page.click("button.ant-btn.ant-btn-primary >> text=アップロード")
    print("✅ ファイルをアップロードしました")

    # 一覧 → 一括確認
    page.wait_for_selector("input[type='checkbox']")
    page.click("input[type='checkbox']")  # 全選択
    page.click("a.ant-btn.ant-btn-primary")  # 一括確認
    page.click("button.ant-btn.ant-btn-primary.ant-btn-sm")  # 確認
    print("✅ 一括確認完了")

    # エラー確認
    try:
        error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
        print("⚠️ エラー内容:", error_dialog.inner_text())
    except:
        print("✅ エラーなし、正常に完了しました")

    browser.close()
