import os
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
# hidden input 対応のファイルアップロード
# ==============================
def safe_upload_file(page, file_path: str, timeout=60000):
    """hiddenな<input type='file'>にも対応して直接アップロード"""
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
        safe_click_by_index(page, "button.ant-btn", 0)
        print("✅ 上传ボタン押下")
        time.sleep(3)
        
        # (4) ファイル添付（hidden input対応）
        safe_upload_file(page, FILE_PATH)
        print("🌐 現在のURL:", page.url)  # ← ここ。safe_upload_file と同じインデント

        # (5) 导入ボタン（青いやつ） - モーダル内最後の primary ボタンをリトライ探索して押す
        print("⏳ 导入ボタンをリトライ探索中...")

        clicked = False
        for i in range(30):  # 最大30秒リトライ
            # モーダル要素をより広く探索
            modal_buttons = page.query_selector_all(
                "div[role='dialog'] button.ant-btn-primary, div.ant-modal button.ant-btn-primary, div.ant-modal-root button.ant-btn-primary"
            )

            if modal_buttons:
                print(f"🟦 {len(modal_buttons)}個の primary ボタンを検出（{i+1}回目）:")
                for idx, b in enumerate(modal_buttons):
                    txt = b.inner_text().strip()
                    print(f"   [{idx}] text='{txt}'")
                # 最後のボタンをクリック（通常「导入」）
                modal_buttons[-1].click()
                print(f"✅ 导入ボタン押下成功（{i+1}回目の試行）")
                clicked = True
                break
            time.sleep(1)

        if not clicked:
            page.screenshot(path="debug_screenshot_modal.png", full_page=True)
            with open("debug_modal.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError("❌ 30秒待っても导入ボタンが出ませんでした。debug_modal.htmlを確認してください。")



        # (6) 一覧反映を待機（最大120秒）
        print("⏳ 导入結果の反映を待機中...")
        try:
            page.wait_for_selector("input[type='checkbox']", state="visible", timeout=120000)
            print("✅ 一覧表示を検出（checkboxあり）")
        except Exception:
            page.screenshot(path="debug_screenshot.png", full_page=True)
            html_dump = page.content()
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(html_dump)
            raise RuntimeError("❌ 一覧反映が確認できません。debug.htmlを確認してください。")

        # (7) 一括確認 → 确认
        safe_click_by_index(page, "input[type='checkbox']", 0)
        safe_click_by_index(page, "button.ant-btn", 0)
        safe_click_by_index(page, "button.ant-btn-primary", -1)
        print("✅ 一括確認完了")

        browser.close()

if __name__ == "__main__":
    main()
