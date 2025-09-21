import os
import dropbox
import requests
from playwright.sync_api import sync_playwright

# ===== Dropboxから最新ファイルを取得 =====
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

def download_latest_file():
    token = refresh_access_token()
    dbx = dropbox.Dropbox(token)

    folder_path = "/tenton"  # ←ここ固定
    entries = dbx.files_list_folder(folder_path).entries
    latest_file = sorted(entries, key=lambda f: f.server_modified, reverse=True)[0]

    FILE_PATH = "latest_report.txt"
    _, res = dbx.files_download(latest_file.path_lower)
    with open(FILE_PATH, "wb") as f:
        f.write(res.content)
    print(f"Downloaded: {latest_file.name}")
    return FILE_PATH

# ===== Playwright ユーティリティ =====
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"FATAL: Timeout waiting for selector '{selector}'") from e

def safe_click_by_index(page, selector, index, timeout=60000):
    safe_wait_selector(page, selector, timeout)
    elems = page.query_selector_all(selector)
    if index < len(elems):
        elems[index].click()
    else:
        raise RuntimeError(f"Selector {selector} not found at index {index}")

def select_dropdown_option(page, dropdown_index: int, option_texts):
    """
    Ant Design のドロップダウンを index で開いて、候補リストのいずれかを選択
    option_texts: list[str]
    """
    safe_click_by_index(page, "div.ant-select-selection", dropdown_index, timeout=60000)

    try:
        safe_wait_selector(page, "li[role='option']", timeout=5000)
        options = page.query_selector_all("li[role='option']")
    except:
        safe_wait_selector(page, "ul li", timeout=5000)
        options = page.query_selector_all("ul li")

    all_txt = []
    for opt in options:
        txt = opt.inner_text().strip().replace(" ", "").replace("\n", "")
        all_txt.append(txt)
        for opt_text in option_texts:
            if opt_text in txt:  # 部分一致
                opt.click()
                print(f"✅ ドロップダウン {dropdown_index} で '{opt_text}' を選択 ({txt})")
                return

    raise RuntimeError(f"候補 {option_texts} が見つかりませんでした. 実際の候補={all_txt}")

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
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=120000)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button.login-button")
        page.wait_for_load_state("networkidle")
        print("✅ ログイン成功")

        # 言語切替（インデックスで2番目 → 日本語）
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']", timeout=60000)
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print(f"⚠️ 言語切替に失敗: {e}（続行）")

        # アップロード画面へ
        page.goto(UPLOAD_URL, timeout=180000)
        page.wait_for_load_state("networkidle")
        print("✅ アップロード画面表示確認")

        # 店舗種類・店舗名を指定
        select_dropdown_option(page, 0, ["アマゾン", "亚马逊"])
        select_dropdown_option(page, 1, ["アイプロダクト"])

        # アップロード処理
        safe_click_by_index(page, "button.ant-btn", 0)  # 最初のアップロードボタン
        page.set_input_files("input[type='file']", FILE_PATH)
        page.click("button.ant-btn-primary:has-text('アップロード')")
        print("✅ ファイルアップロード完了")

        # 一括確認
        safe_wait_selector(page, "input[type='checkbox']", timeout=60000)
        page.click("input[type='checkbox']")  # 全選択
        page.click("a.ant-btn-primary")       # 一括確認
        page.click("button.ant-btn-primary.ant-btn-sm")  # 確認
        print("✅ 一括確認処理完了")

        # エラーチェック
        try:
            error_dialog = page.wait_for_selector(".ant-modal-body", timeout=5000)
            print("❌ エラー内容:", error_dialog.inner_text())
        except:
            print("✅ エラーなし、正常に完了しました。")

        browser.close()

if __name__ == "__main__":
    main()
