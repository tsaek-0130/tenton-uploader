import os
import time
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
    if len(elems) <= index:
        raise RuntimeError(f"{selector} index {index} not found (len={len(elems)})")
    elems[index].click()

def select_dropdown(page, index, option_text):
    """index=0: 店舗種類, index=1: 店舗名"""
    dropdowns = page.query_selector_all("div.ant-select")
    if len(dropdowns) <= index:
        raise RuntimeError(f"ドロップダウン index={index} が見つかりません")
    dropdowns[index].click()
    safe_wait_selector(page, "li[role='option']")
    options = page.query_selector_all("li[role='option']")
    texts = [o.inner_text().strip() for o in options]
    for o in options:
        if option_text in o.inner_text():
            o.click()
            print(f"✅ ドロップダウン{index} で {option_text} を選択 (候補={texts})")
            return
    raise RuntimeError(f"{option_text} が見つかりません. 候補={texts}")

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

        # アップロードモーダルを開く
        safe_click_by_index(page, "button.ant-btn-primary", 0)  # 上部の「アップロード」
        print("✅ アップロード画面表示確認")

        # 店舗種類・店舗名を選択
        select_dropdown(page, 0, "アマゾン")
        select_dropdown(page, 1, "アイプロダクト")

        # 上传ボタンをクリック（最初の青いボタン）
        safe_click_by_index(page, "button.ant-btn-primary", 0)

        # ファイル添付
        safe_wait_selector(page, "input[type='file']")
        page.set_input_files("input[type='file']", FILE_PATH)
        print("✅ ファイル添付完了")

        # 导入ボタン（最後の青いボタン）
        safe_click_by_index(page, "button.ant-btn-primary", -1)
        print("✅ 导入実行")

        # 一覧反映を待機
        page.wait_for_timeout(10000)

        # 一括確認 → 确认
        safe_click_by_index(page, "input[type='checkbox']", 0)   # 一番上のチェックボックス
        safe_click_by_index(page, "button.ant-btn", 0)           # 一括確認
        safe_click_by_index(page, "button.ant-btn-primary", -1)  # 确认
        print("✅ 一括確認完了")

        browser.close()

if __name__ == "__main__":
    main()
