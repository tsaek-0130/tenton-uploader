import os
import requests
from playwright.sync_api import sync_playwright

# ========================
# Dropbox トークン更新
# ========================
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]

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
ACCESS_TOKEN = resp.json()["access_token"]

# ========================
# Dropbox から最新ファイル取得
# ========================
import dropbox
dbx = dropbox.Dropbox(ACCESS_TOKEN)

folder_path = "/tenton"
files = dbx.files_list_folder(folder_path).entries
latest_file = sorted(files, key=lambda f: f.server_modified, reverse=True)[0]

FILE_PATH = "latest_report.txt"
_, res = dbx.files_download(latest_file.path_lower)
with open(FILE_PATH, "wb") as f:
    f.write(res.content)
print(f"Downloaded: {latest_file.name}")

# ========================
# Tenton ログイン情報
# ========================
USERNAME = os.environ["TENTON_USER"]
PASSWORD = os.environ["TENTON_PASS"]
LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

# ========================
# ユーティリティ
# ========================
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        print(f"FATAL: Timeout waiting for selector '{selector}'")
        raise RuntimeError(f"Timeout waiting for selector '{selector}'") from e

def safe_click_by_index(page, selector, index, timeout=60000):
    elems = page.query_selector_all(selector)
    if len(elems) <= index:
        raise RuntimeError(f"Selector {selector} not found at index {index}")
    elems[index].click()
    page.wait_for_timeout(500)  # 小休止

# ========================
# メイン処理
# ========================
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ログイン
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=180000)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button.login-button")
        page.wait_for_load_state("networkidle", timeout=180000)
        print("✅ ログイン成功")

        # 言語を日本語に切替
        try:
            safe_wait_selector(page, "span.ant-pro-drop-down", timeout=60000)
            page.click("span.ant-pro-drop-down")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
                print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # アップロード画面へ
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=180000)
        print("✅ アップロード画面表示確認")

        # アップロードモーダルを開く
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 0)
        print("✅ アップロードモーダルを開いた")

        # モーダルが出るまで待機
        safe_wait_selector(page, ".ant-modal-content", timeout=120000)
        modal = page.query_selector(".ant-modal-content")
        if not modal:
            raise RuntimeError("モーダルが取得できませんでした")
        print("✅ モーダルを検出")

        # 店舗種類/店舗名を選択
        selectors = modal.query_selector_all("div.ant-select-selector")
        if len(selectors) < 2:
            raise RuntimeError(f"店舗選択セレクタが足りません (found={len(selectors)})")
        selectors[0].click()
        safe_wait_selector(page, "div[title='アマゾン']", timeout=60000)
        page.query_selector("div[title='アマゾン']").click()

        selectors[1].click()
        safe_wait_selector(page, "div[title='アイプロダクト']", timeout=60000)
        page.query_selector("div[title='アイプロダクト']").click()
        print("✅ 店舗種類・店舗名を選択完了")

        # ファイルを選択してアップロード
        modal.query_selector("input[type='file']").set_input_files(FILE_PATH)
        print("✅ ファイル添付完了")

        # モーダル内の「アップロード」ボタンを押す
        buttons = modal.query_selector_all("button.ant-btn.ant-btn-primary")
        if buttons:
            buttons[-1].click()
            print("✅ モーダル内アップロード実行")

        # 一覧反映を待機
        safe_wait_selector(page, "input[type='checkbox']", timeout=180000)

        # 一括確認
        page.click("input[type='checkbox']")  # 全選択
        page.click("a.ant-btn.ant-btn-primary")  # 一括確認ボタン
        page.click("button.ant-btn-primary.ant-btn-sm")  # 確認ボタン
        print("✅ 一括確認を実行")

        # エラーチェック
        try:
            error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
            if error_dialog:
                print("エラー内容:", error_dialog.inner_text())
        except:
            print("エラーなし、正常に完了しました。")

        browser.close()

if __name__ == "__main__":
    main()
