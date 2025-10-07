import os
import dropbox
import requests
import time
from playwright.sync_api import sync_playwright

# ==============================
# Dropbox から最新ファイルを取得
# ==============================
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
    elems[index].click()

def select_dropdown_by_index(page, dropdown_index, option_index):
    dropdowns = page.query_selector_all("div.ant-select")
    if len(dropdowns) <= dropdown_index:
        raise RuntimeError(f"ドロップダウン index={dropdown_index} が見つかりません")

    dropdowns[dropdown_index].click()
    print(f"🕓 ドロップダウン{dropdown_index} をクリック、選択肢表示待機中...")

    # リストが安定して出現するまで最大10回リトライ
    for attempt in range(10):
        try:
            safe_wait_selector(page, "div.ant-select-dropdown li[role='option']", timeout=2000)
            options = page.query_selector_all("div.ant-select-dropdown li[role='option']")
            if len(options) > option_index:
                options[option_index].hover()  # hoverで描画安定させる
                time.sleep(0.2)
                options[option_index].click()
                print(f"✅ ドロップダウン{dropdown_index} → option[{option_index}] を選択（試行{attempt+1}回目）")
                return
        except Exception as e:
            print(f"⚠️ ドロップダウン選択失敗（{attempt+1}回目）: {e}")
            time.sleep(0.5)

    raise RuntimeError(f"❌ ドロップダウン{dropdown_index} の option[{option_index}] 選択に失敗（全試行終了）")


def safe_upload_file(page, file_path: str, timeout=60000):
    """Ant Design Upload対応：Reactイベントを経由してファイル選択"""
    print("⏳ アップロードボタンを探索中...")
    # 「アップロード」ボタンをクリック（hidden inputをReactが生成する）
    upload_trigger = page.query_selector(".ant-upload") or page.query_selector("button.ant-btn")
    if not upload_trigger:
        raise RuntimeError("❌ アップロードトリガーが見つかりません。")

    upload_trigger.click()
    print("✅ アップロードボタンをクリック（Reactのinput生成を誘発）")

    # 生成されたinput[type=file]を待機
    input_elem = page.wait_for_selector("input[type='file']", timeout=timeout)
    html_preview = input_elem.evaluate("el => el.outerHTML")
    print(f"🔍 inputタグHTML: {html_preview}")

    # ファイルをセット（ReactのonChangeが発火）
    input_elem.set_input_files(file_path)
    print("✅ ファイルを選択（onChange発火）")

    # アップロード完了を待機
    try:
        page.wait_for_selector(".ant-upload-list-item", timeout=30000)
        print("✅ アップロード完了を検出（.ant-upload-list-item出現）")
    except Exception:
        print("⚠️ アップロード完了を検出できません（非同期遅延の可能性）")


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
# ログイン & セッション保存
# ==============================
def login_and_save_state(browser, username, password):
    context = browser.new_context()
    page = context.new_page()
    print("🌐 初回ログイン...")
    page.goto("http://8.209.213.176/login", timeout=300000)
    page.wait_for_selector("#username", timeout=180000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button.login-button")
    page.wait_for_load_state("networkidle", timeout=180000)
    print("✅ ログイン成功、state.jsonへ保存中...")
    context.storage_state(path=STATE_FILE)
    context.close()
    print("💾 state.json 保存完了")

# ==============================
# メイン処理
# ==============================
def main():
    FILE_PATH = download_latest_file()
    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # --- セッション再利用 or 初回ログイン ---
        if os.path.exists(STATE_FILE):
            print("✅ 保存済みセッションを使用")
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            login_and_save_state(browser, USERNAME, PASSWORD)
            context = browser.new_context(storage_state=STATE_FILE)

        page = context.new_page()
        page.goto("http://8.209.213.176/fundamentalData/goodInfo", timeout=300000)
        print("✅ アップロード画面へアクセス完了")

        # 言語切替（以前通り）
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # アップロードモーダル → ドロップダウン選択
        safe_click_by_index(page, "button.ant-btn-primary", 0)
        print("✅ アップロード画面表示確認")

        select_dropdown_by_index(page, 0, 0)
        select_dropdown_by_index(page, 1, 0)

        # 上传ボタン押下
        safe_click_by_index(page, "button.ant-btn", 0)
        print("✅ 上传ボタン押下")
        time.sleep(3)

        # ファイルアップロード
        safe_upload_file(page, FILE_PATH)
        # ファイルアップロード直後の挙動確認
        print("🌐 現在のURL:", page.url)
        print("📄 page title:", page.title())
        with open("debug_after_upload.html", "w", encoding="utf-8") as f:
            f.write(page.content())


        # アップロード後のページHTMLを保存して中身を確認
        with open("debug_after_upload.html", "w", encoding="utf-8") as f:
            f.write(page.content())



        # 导入ボタン
        if not click_modal_primary_import(page, timeout_sec=60):
            page.screenshot(path="debug_screenshot_modal.png", full_page=True)
            with open("debug_modal.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError("❌ 导入ボタンが見つかりません")

        # エラーモーダル
        print("⏳ エラーモーダル（提示）検出を待機中...")
        error_found = False
        try:
            page.wait_for_selector("div.ant-modal-confirm", timeout=8000)
            print("⚠️ エラーモーダルを検出")
            error_found = True
            error_texts = page.query_selector_all(
                "div.ant-modal-confirm div.ant-modal-confirm-body span, "
                "div.ant-modal-confirm div.ant-modal-confirm-body div"
            )
            if error_texts:
                print("🧾 エラー内容一覧:")
                for e in error_texts:
                    txt = e.inner_text().strip()
                    if txt:
                        print("   ", txt)
            know_btns = page.query_selector_all("div.ant-modal-confirm button.ant-btn-primary")
            if know_btns:
                know_btns[-1].click()
                print("✅ 知道了ボタン押下（エラーモーダル閉じ）")
        except Exception:
            print("✅ エラーモーダルなし（正常）")

        # 一覧反映
        print("⏳ 一覧反映を待機中...")
        try:
            page.wait_for_selector("input[type='checkbox']", state="visible", timeout=60000)
            print("✅ 一覧表示を検出（checkboxあり）")
        except Exception:
            page.screenshot(path="debug_screenshot_list.png", full_page=True)
            with open("debug_list.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError("❌ 一覧反映が確認できません。debug_list.htmlを確認してください。")

        # 一括確認
        print("⏳ 一括確認処理を実行中...")
        try:
            safe_click_by_index(page, "input[type='checkbox']", 0)
            safe_click_by_index(page, "button.ant-btn", 0)
            safe_click_by_index(page, "button.ant-btn-primary", -1)
            print("✅ 一括確認完了")
        except Exception as e:
            print(f"⚠️ 一括確認処理でエラー: {e}")

        # 結果
        if error_found:
            print("⚠️ 一部注文は既存注文としてスキップされました（上記ログ参照）")
        else:
            print("✅ 全注文が正常に取り込まれました")

        browser.close()

if __name__ == "__main__":
    main()
