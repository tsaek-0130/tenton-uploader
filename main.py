import os
import json
import dropbox
import requests
import time
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
# hidden input 対応のファイルアップロード
# ==============================
def safe_upload_file(page, file_path: str, timeout=60000):
    try:
        print("⏳ ファイルアップロード要素を探索中...")
        page.wait_for_selector("input[type='file']", state="attached", timeout=timeout)
        input_elem = page.query_selector("input[type='file']")
        if not input_elem:
            raise RuntimeError("❌ input[type='file'] が見つかりませんでした。")
        html_preview = input_elem.evaluate("el => el.outerHTML")
        print(f"🔍 inputタグHTML: {html_preview}")
        input_elem.set_input_files(file_path)
        print("✅ ファイルアップロード成功（hidden input対応）")
    except Exception as e:
        print(f"⚠️ アップロード中にエラー発生: {e}")
        raise

# ==============================
# モーダル内の「导入」探索（既存そのまま）
# ==============================
def click_modal_primary_import(page, timeout_sec=60):
    print("⏳ 导入ボタンをリトライ探索中...")
    end = time.time() + timeout_sec
    while time.time() < end:
        buttons = page.query_selector_all("button.ant-btn-primary")
        print(f"🔍 検出されたボタン数: {len(buttons)}")
        for i, btn in enumerate(buttons):
            try:
                text = btn.inner_text().strip()
                print(f"   [{i}] {text}")
                if "导" in text:
                    btn.click()
                    print(f"✅ 『{text}』ボタンをクリック（index={i}）")
                    return True
            except Exception as e:
                print(f"⚠️ ボタン[{i}] 処理エラー: {e}")
        time.sleep(1)
    return False

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

        print("🌐 ログインページへアクセス中...")
        page.goto("http://8.209.213.176/login", timeout=300000)
        page.wait_for_selector("#username", timeout=180000)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button.login-button")
        page.wait_for_load_state("networkidle", timeout=180000)
        print("✅ ログイン成功")

        # 🔍 ここで localStorage / sessionStorage をダンプ
        local_storage = page.evaluate("Object.entries(localStorage)")
        session_storage = page.evaluate("Object.entries(sessionStorage)")

        print("📦 localStorage:", json.dumps(local_storage, ensure_ascii=False, indent=2))
        print("📦 sessionStorage:", json.dumps(session_storage, ensure_ascii=False, indent=2))

        with open("storage_after_login.json", "w", encoding="utf-8") as f:
            json.dump({"localStorage": local_storage, "sessionStorage": session_storage}, f, ensure_ascii=False, indent=2)
        print("💾 storage_after_login.json saved")

        # ここから下は何も変えない（既存処理）
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        safe_click_by_index(page, "button.ant-btn-primary", 0)
        print("✅ アップロード画面表示確認")

        select_dropdown_by_index(page, 0, 0)
        select_dropdown_by_index(page, 1, 0)

        safe_click_by_index(page, "button.ant-btn", 0)
        print("✅ 上传ボタン押下")
        time.sleep(3)

        safe_upload_file(page, FILE_PATH)
        print("🌐 現在のURL:", page.url)

        if not click_modal_primary_import(page, timeout_sec=60):
            page.screenshot(path="debug_screenshot_modal.png", full_page=True)
            with open("debug_modal.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError("❌ 导入ボタンが見つかりません")

        browser.close()

if __name__ == "__main__":
    main()
