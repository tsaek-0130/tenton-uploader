import os
import time
import dropbox
from playwright.sync_api import sync_playwright

# Dropbox 設定
APP_KEY = os.environ["DROPBOX_APP_KEY"]
APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]
DROPBOX_PATH = "/tenton"  # フォルダ名は固定

# Tenton ログイン情報
USERNAME = os.environ["TENTON_USER"]
PASSWORD = os.environ["TENTON_PASS"]

# 安全な待機
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"FATAL: Timeout waiting for selector '{selector}'") from e

# セーフクリック（インデックス指定）
def safe_click_by_index(page, selector, index, timeout=60000):
    safe_wait_selector(page, selector, timeout)
    elements = page.query_selector_all(selector)
    if len(elements) <= index:
        raise RuntimeError(f"Selector {selector} not found at index {index}")
    elements[index].click()

# ドロップダウン選択（縦並び index）
def select_dropdown_option_by_index(page, dropdown_index, option_texts):
    dropdowns = page.query_selector_all("div.ant-select")
    if len(dropdowns) <= dropdown_index:
        raise RuntimeError(f"ドロップダウン {dropdown_index} が見つかりません")
    dropdowns[dropdown_index].click()

    page.wait_for_selector("ul[role='listbox'] li[role='option']", timeout=60000)
    options = page.query_selector_all("ul[role='listbox'] li[role='option']")
    all_txt = [opt.inner_text().strip() for opt in options]

    for opt in options:
        txt = opt.inner_text().strip()
        if txt in option_texts:
            opt.click()
            print(f"✅ ドロップダウン {dropdown_index} で '{txt}' を選択")
            return

    raise RuntimeError(f"候補 {option_texts} が見つかりませんでした. 実際の候補={all_txt}")

# Dropbox 最新ファイル取得
def download_latest_file():
    dbx = dropbox.Dropbox(oauth2_refresh_token=REFRESH_TOKEN,
                          app_key=APP_KEY,
                          app_secret=APP_SECRET)

    entries = dbx.files_list_folder(DROPBOX_PATH).entries
    if not entries:
        raise RuntimeError("Dropbox フォルダが空です")

    latest_file = max(entries, key=lambda e: e.client_modified)
    _, res = dbx.files_download(latest_file.path_lower)

    local_path = os.path.basename(latest_file.path_lower)
    with open(local_path, "wb") as f:
        f.write(res.content)

    print(f"Downloaded: {local_path}")
    return local_path

# メイン処理
def main():
    FILE_PATH = download_latest_file()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ログイン
        page.goto("http://8.209.213.176/login")
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button.login-button")
        page.wait_for_load_state("networkidle", timeout=120000)
        print("✅ ログイン成功")

        # 言語を日本語に切替（ドロップダウン2番目を選択）
        try:
            page.click("span.ant-pro-drop-down")
            page.wait_for_selector("li[role='menuitem']", timeout=60000)
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # アップロード画面へ
        page.goto("http://8.209.213.176/orderManagement/orderInFo")
        page.wait_for_load_state("networkidle", timeout=120000)
        print("✅ アップロード画面表示確認")

        # アップロード処理
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 0)  # アップロードボタン
        page.set_input_files("input[type='file']", FILE_PATH)
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 1)  # モーダル内のアップロード
        print("✅ ファイルを添付 & アップロード実行")

        # 店舗種類・店舗名選択
        select_dropdown_option_by_index(page, 0, ["アマゾン", "亚马逊"])
        select_dropdown_option_by_index(page, 1, ["アイプロダクト"])

        # 一括確認
        safe_click_by_index(page, "thead .ant-checkbox-input", 0)   # 全選択
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 2)  # 一括確認ボタン
        safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 0)  # モーダルの「確認」
        print("✅ 一括確認完了")

        # エラー画面検知
        try:
            error_elem = page.query_selector(".ant-modal-body")
            if error_elem:
                print("⚠️ エラー検出:", error_elem.inner_text())
        except Exception:
            pass

        browser.close()

if __name__ == "__main__":
    main()
