import os
import dropbox
import requests
from playwright.sync_api import sync_playwright

# ==============================
# Dropbox から最新ファイルを取得
# ==============================
DROPBOX_PATH = "/tenton"

def refresh_access_token():
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": os.environ["DROPBOX_REFRESH_TOKEN"],
        "client_id": os.environ["DROPBOX_APP_KEY"],
        "client_secret": os.environ["DROPBOX_APP_SECRET"],
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]

def download_latest_file():
    access_token = refresh_access_token()
    dbx = dropbox.Dropbox(oauth2_access_token=access_token)
    entries = dbx.files_list_folder(DROPBOX_PATH).entries
    latest = max(entries, key=lambda e: e.server_modified)
    _, res = dbx.files_download(latest.path_lower)
    fname = f"Downloaded: {latest.name}"
    with open(fname, "wb") as f:
        f.write(res.content)
    print(fname)
    return os.path.abspath(fname)

# ==============================
# Playwright ユーティリティ
# ==============================
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"FATAL: Timeout waiting for selector '{selector}'") from e

def safe_click_by_index(page, selector, index, timeout=60000):
    safe_wait_selector(page, selector, timeout)
    elems = page.query_selector_all(selector)
    if not elems:
        raise RuntimeError(f"{selector} が見つかりません")
    target = elems[index] if index >= 0 else elems[index]
    target.click()

def select_dropdown_by_index(page, dropdown_index, option_index):
    """indexベースで選択する。文字列は一切使わない"""
    dropdowns = page.query_selector_all("div.ant-select")
    if len(dropdowns) <= dropdown_index:
        raise RuntimeError(f"ドロップダウン index={dropdown_index} が見つかりません")
    dropdowns[dropdown_index].click()
    safe_wait_selector(page, "li[role='option']")
    options = page.query_selector_all("li[role='option']")
    if len(options) <= option_index:
        raise RuntimeError(f"ドロップダウン{dropdown_index} に option {option_index} がありません (len={len(options)})")
    options[option_index].click()
    print(f"✅ ドロップダウン{dropdown_index} → option[{option_index}] を選択")

# ==============================
# メイン処理
# ==============================
def main():
    FILE_PATH = download_latest_file()
    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ログイン
        page.goto("http://8.209.213.176/login")
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button.login-button")
        page.wait_for_load_state("networkidle", timeout=180000)
        print("✅ ログイン成功")

        # 言語を日本語に統一
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # (1) アップロードモーダルを開く
        safe_click_by_index(page, "button.ant-btn-primary", 0)
        print("✅ アップロード画面表示確認")

        # (2) 店舗種類・店舗名を index 指定で選択
        select_dropdown_by_index(page, 0, 0)  # 店舗種類（例: アマゾン）
        select_dropdown_by_index(page, 1, 0)  # 店舗名（例: アイプロダクト）
        
        # (3) 上传ボタンをクリック（モーダル内のアップロード）
        safe_click_by_index(page, "button.ant-btn", 0)  # ← 修正
        print("✅ 上传ボタン押下")

        # (4) ファイル添付
        safe_wait_selector(page, "input[type='file']", timeout=60000)
        page.set_input_files("input[type='file']", FILE_PATH)
        print("✅ ファイル添付完了")

        # (5) 导入ボタン（青いやつ）
        safe_click_by_index(page, "button.ant-btn-primary", -1)
        print("✅ 导入実行")


        # (6) 一覧反映を待機
        page.wait_for_timeout(10000)

        # (7) 一括確認 → 确认
        safe_click_by_index(page, "input[type='checkbox']", 0)
        safe_click_by_index(page, "button.ant-btn", 0)
        safe_click_by_index(page, "button.ant-btn-primary", -1)
        print("✅ 一括確認完了")

        browser.close()

if __name__ == "__main__":
    main()
