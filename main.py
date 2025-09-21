import os
import time
import dropbox
import requests
from playwright.sync_api import sync_playwright

# -----------------------------
# 環境変数
# -----------------------------
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]
USERNAME = os.environ["TENTON_USER"]
PASSWORD = os.environ["TENTON_PASS"]
DROPBOX_PATH = "/tenton"   # Dropbox 監視フォルダ

# -----------------------------
# Dropbox アクセストークン取得
# -----------------------------
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

# -----------------------------
# Dropbox 最新ファイルを取得
# -----------------------------
def download_latest_file():
    token = get_access_token()
    dbx = dropbox.Dropbox(token)
    entries = dbx.files_list_folder(DROPBOX_PATH).entries
    latest = max(entries, key=lambda e: e.client_modified)
    name = latest.name
    out = f"{name}"
    dbx.files_download_to_file(out, latest.path_lower)
    print(f"Downloaded: {name}")
    return out

# -----------------------------
# セーフ系ユーティリティ
# -----------------------------
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"FATAL: Timeout waiting for selector '{selector}'") from e

def safe_click_by_index(page, selector, index=0, timeout=60000):
    safe_wait_selector(page, selector, timeout)
    elements = page.query_selector_all(selector)
    if len(elements) > index:
        elements[index].click()
        return
    raise RuntimeError(f"Selector {selector} not found at index {index}")

# -----------------------------
# メイン処理
# -----------------------------
def main():
    FILE_PATH = download_latest_file()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ログイン
        page.goto("http://8.209.213.176/")
        safe_wait_selector(page, "#username")
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        safe_click_by_index(page, "button.login-button", 0)
        page.wait_for_load_state("networkidle")
        print("✅ ログイン成功")

        # UI言語を日本語に強制
        safe_wait_selector(page, "span.ant-pro-drop-down")
        page.click("span.ant-pro-drop-down")
        items = page.query_selector_all("li[role='menuitem']")
        if len(items) >= 2:
            items[1].click()
        print("✅ 言語を日本語に切替")

        # アップロードボタンでモーダル表示
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", -1)
        print("✅ アップロード画面表示確認")

        # 店舗種類 = アマゾン
        safe_click_by_index(page, "div.ant-select-selector", 0)
        time.sleep(1)
        options = page.query_selector_all("div[title='アマゾン']")
        if options:
            options[0].click()
        else:
            raise RuntimeError("❌ 店舗種類『アマゾン』が見つからない")

        # 店舗名 = アイプロダクト
        safe_click_by_index(page, "div.ant-select-selector", 1)
        time.sleep(1)
        options = page.query_selector_all("div[title='アイプロダクト']")
        if options:
            options[0].click()
        else:
            raise RuntimeError("❌ 店舗名『アイプロダクト』が見つからない")

        # ファイル選択 → 添付
        safe_wait_selector(page, "input[type='file']")
        page.set_input_files("input[type='file']", FILE_PATH)
        print("✅ ファイル添付")

        # モーダル内の「アップロード」クリック（右下のボタン）
        confirm_buttons = page.query_selector_all("button.ant-btn.ant-btn-primary")
        if confirm_buttons:
            confirm_buttons[-1].click()
        else:
            raise RuntimeError("❌ モーダルのアップロードボタンが見つからない")
        print("✅ ファイルアップロード実行")

        # 一覧の反映待ち
        page.wait_for_load_state("networkidle", timeout=180000)

        # 一番上のチェックボックスをクリック
        safe_click_by_index(page, "th .ant-checkbox-input", 0)
        print("✅ 一覧全選択")

        # 一括確認ボタンを押す
        safe_click_by_index(page, "button.ant-btn", -1)
        print("✅ 一括確認ボタン押下")

        # モーダルで「確 認」を押す
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", -1)
        print("✅ 確認モーダル承認")

        # エラーメッセージが出ていればログに出力
        try:
            error_el = page.query_selector(".ant-modal-body .ant-alert-message")
            if error_el:
                print("⚠️ エラー内容:", error_el.inner_text())
        except:
            pass

        browser.close()

if __name__ == "__main__":
    main()
