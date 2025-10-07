import os
import json
import dropbox
import requests
import time
from playwright.sync_api import sync_playwright

DROPBOX_PATH = "/tenton"
STATE_FILE = "state.json"

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

def safe_wait_selector(page, selector, timeout=60000):
    return page.wait_for_selector(selector, timeout=timeout)

def safe_click_by_index(page, selector, index):
    elems = page.query_selector_all(selector)
    if not elems:
        raise RuntimeError(f"{selector} が見つかりません")
    elems[index].click()

def select_dropdown_by_index(page, dropdown_index, option_index):
    dropdowns = page.query_selector_all("div.ant-select")
    dropdowns[dropdown_index].click()
    page.wait_for_selector("li[role='option']")
    options = page.query_selector_all("li[role='option']")
    options[option_index].click()
    print(f"✅ ドロップダウン{dropdown_index} → option[{option_index}] を選択")

def safe_upload_file(page, file_path):
    page.wait_for_selector("input[type='file']", state="attached", timeout=60000)
    input_elem = page.query_selector("input[type='file']")
    input_elem.set_input_files(file_path)
    print("✅ ファイルアップロード成功")

def click_modal_primary_import(page, timeout_sec=60):
    print("⏳ 导入ボタン探索中...")
    end = time.time() + timeout_sec
    while time.time() < end:
        buttons = page.query_selector_all("button.ant-btn-primary")
        for i, btn in enumerate(buttons):
            try:
                text = btn.inner_text().strip()
                if "导" in text:
                    btn.click()
                    print(f"✅ 『{text}』ボタン押下")
                    return True
            except:
                pass
        time.sleep(1)
    return False

def login_and_save_state(browser, username, password):
    print("🌐 初回ログイン処理開始...")
    context = browser.new_context()
    page = context.new_page()
    page.goto("http://8.209.213.176/login", timeout=300000)
    page.wait_for_selector("#username", timeout=180000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button.login-button")
    page.wait_for_load_state("networkidle", timeout=180000)
    print("✅ ログイン成功、状態保存中...")

    # localStorageをstate.jsonに保存
    context.storage_state(path=STATE_FILE)
    print(f"💾 保存完了: {STATE_FILE}")
    context.close()

def main():
    FILE_PATH = download_latest_file()
    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # すでに state.json があれば再ログイン不要
        if os.path.exists(STATE_FILE):
            print("✅ 保存済みセッションを使用")
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            login_and_save_state(browser, USERNAME, PASSWORD)
            context = browser.new_context(storage_state=STATE_FILE)

        page = context.new_page()
        page.goto("http://8.209.213.176/fundamentalData/goodInfo", timeout=300000)
        print("✅ アップロード画面へアクセス完了")

        # 通常フロー
        safe_click_by_index(page, "button.ant-btn-primary", 0)
        select_dropdown_by_index(page, 0, 0)
        select_dropdown_by_index(page, 1, 0)
        safe_click_by_index(page, "button.ant-btn", 0)
        safe_upload_file(page, FILE_PATH)

        if not click_modal_primary_import(page):
            raise RuntimeError("❌ 导入ボタンが見つかりません")

        print("✅ 完了")
        browser.close()

if __name__ == "__main__":
    main()
