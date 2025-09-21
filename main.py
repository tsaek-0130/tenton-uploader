import os
import requests
import dropbox
from playwright.sync_api import sync_playwright

# ===== Dropbox から最新ファイル取得 =====
DROPBOX_APP_KEY = os.environ["DROPBOX_APP_KEY"]
DROPBOX_APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
DROPBOX_REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]
DROPBOX_PATH = "/tenton"

def get_dropbox_access_token():
    url = "https://api.dropbox.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY,
        "client_secret": DROPBOX_APP_SECRET,
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]

def download_latest_file():
    access_token = get_dropbox_access_token()
    dbx = dropbox.Dropbox(oauth2_access_token=access_token)
    entries = dbx.files_list_folder(DROPBOX_PATH).entries
    latest = sorted(entries, key=lambda f: f.server_modified, reverse=True)[0]
    _, res = dbx.files_download(latest.path_lower)

    FILE_PATH = "latest_report.txt"
    with open(FILE_PATH, "wb") as f:
        f.write(res.content)
    print(f"Downloaded: {latest.name}")
    return FILE_PATH

# ===== Playwright ユーティリティ =====
def safe_wait_selector(page, selector, timeout=60000):
    return page.wait_for_selector(selector, timeout=timeout)

def safe_click_by_index(page, selector, index=0, timeout=60000):
    safe_wait_selector(page, selector, timeout)
    elems = page.query_selector_all(selector)
    if len(elems) > index:
        elems[index].click()
    else:
        raise RuntimeError(f"Selector {selector} not found at index {index}")

def select_dropdown_option(page, dropdown_index: int, option_text: str):
    """
    Ant Design のドロップダウンを index で開いて、指定の文字列 option を選択
    """
    safe_click_by_index(page, "div.ant-select-selection", dropdown_index, timeout=60000)

    try:
        safe_wait_selector(page, "li[role='option']", timeout=5000)
        options = page.query_selector_all("li[role='option']")
    except:
        safe_wait_selector(page, "ul li", timeout=5000)
        options = page.query_selector_all("ul li")

    for opt in options:
        txt = opt.inner_text().strip()
        if option_text in txt:
            opt.click()
            print(f"✅ ドロップダウン {dropdown_index} で '{option_text}' を選択")
            return

    raise RuntimeError(f"'{option_text}' が見つかりませんでした")

# ===== メイン処理 =====
def main():
    FILE_PATH = download_latest_file()

    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]
    LOGIN_URL = "http://8.209.213.176/user/login"
    UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ログイン
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=180000)
        page.fill("input#username", USERNAME)
        page.fill("input#password", PASSWORD)
        page.click("button.login-button")
        page.wait_for_load_state("networkidle", timeout=180000)
        print("✅ ログイン成功")

        # UI 言語を日本語に切替（常にドロップダウン2番目）
        try:
            safe_click_by_index(page, "span.ant-pro-drop-down", 0)
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # アップロード画面へ
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=180000)
        print("✅ アップロード画面表示確認")

        # 「アップロード」ボタン
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 0)

        # 店舗種類 = アマゾン, 店舗名 = アイプロダクト
        select_dropdown_option(page, 0, "アマゾン")
        select_dropdown_option(page, 1, "アイプロダクト")

        # ファイル添付
        safe_wait_selector(page, "input[type='file']", timeout=60000)
        page.set_input_files("input[type='file']", FILE_PATH)

        # モーダルのアップロードボタン押下
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", -1)
        print("✅ ファイルをアップロード")

        # 一覧に反映されるのを待つ
        safe_wait_selector(page, "input[type='checkbox']", timeout=180000)

        # 全選択 → 一括確認 → 確認
        page.click("input[type='checkbox']")
        page.click("a.ant-btn.ant-btn-primary")
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary.ant-btn-sm", 0)
        print("✅ 一括確認処理完了")

        # エラーモーダル確認
        try:
            error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
            print("⚠️ エラー内容:", error_dialog.inner_text())
        except:
            print("✅ エラーなし、完了しました")

        browser.close()

if __name__ == "__main__":
    main()
