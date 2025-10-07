import os
import json
import dropbox
import requests
import time
from playwright.sync_api import sync_playwright

DROPBOX_PATH = "/tenton"
STATE_FILE = "state.json"

# --- Dropbox 認証 ---
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

# --- Playwright util ---
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

    for attempt in range(10):
        try:
            safe_wait_selector(page, "div.ant-select-dropdown li[role='option']", timeout=2000)
            options = page.query_selector_all("div.ant-select-dropdown li[role='option']")
            if len(options) > option_index:
                options[option_index].hover()
                time.sleep(0.2)
                options[option_index].click()
                print(f"✅ ドロップダウン{dropdown_index} → option[{option_index}] を選択（試行{attempt+1}回目）")
                return
        except Exception as e:
            print(f"⚠️ ドロップダウン選択失敗（{attempt+1}回目）: {e}")
            time.sleep(0.5)

    raise RuntimeError(f"❌ ドロップダウン{dropdown_index} の option[{option_index}] 選択に失敗（全試行終了）")

def safe_upload_file(page, file_path: str, timeout=60000):
    print("⏳ ファイルアップロード要素を探索中...")
    input_elem = page.wait_for_selector(".ant-upload input[type='file']", state="attached", timeout=timeout)
    html_preview = input_elem.evaluate("el => el.outerHTML")
    print(f"🔍 inputタグHTML: {html_preview}")
    input_elem.set_input_files(file_path)
    print("✅ ファイルを選択完了")

    try:
        page.wait_for_selector(".ant-list-item", state="attached", timeout=30000)
        print("✅ アップロードリスト表示検出（アップロード完了）")
    except Exception:
        print("⚠️ アップロード完了を検出できず（遅延の可能性）")

# --- Login ---
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
    # ここ追加👇
    local_data = page.evaluate("() => JSON.stringify(window.localStorage)")
    print("💾 localStorage内容:", local_data)
    print("✅ ログイン成功、state.jsonへ保存中...")
    context.storage_state(path=STATE_FILE)
    context.close()
    print("💾 state.json 保存完了")

# --- メイン ---
def main():
    FILE_PATH = download_latest_file()
    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # セッション復元
        if os.path.exists(STATE_FILE):
            print("✅ 保存済みセッションを使用")
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            login_and_save_state(browser, USERNAME, PASSWORD)
            context = browser.new_context(storage_state=STATE_FILE)

        page = context.new_page()
        page.goto("http://8.209.213.176/fundamentalData/goodInfo", timeout=300000)
        print("✅ アップロード画面へアクセス完了")

        # 言語切替
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # アップロードモーダル表示
        safe_click_by_index(page, "button.ant-btn-primary", 0)
        print("✅ アップロード画面表示確認")

        select_dropdown_by_index(page, 0, 0)
        select_dropdown_by_index(page, 1, 0)

        safe_click_by_index(page, "button.ant-btn", 0)
        print("✅ 上传ボタン押下")
        time.sleep(2)
        safe_upload_file(page, FILE_PATH)

        # --- ✅ ここから修正版: tokenをstate.jsonから直接抽出 ---
        print("🍪 state.jsonからtokenを取得中...")

        token_value = None
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cookies = data.get("cookies", [])
                for c in cookies:
                    if c.get("name") == "token":
                        token_value = c.get("value")
                        print(f"✅ token取得成功: {token_value[:20]}...")

        if not token_value:
            raise RuntimeError("❌ tokenがstate.jsonから取得できませんでした")

        cookie_header = f"token={token_value}"
        api_url = "http://8.209.213.176/api/back/order/importOrderYmx"
        headers = {
            "Cookie": cookie_header,
            "Accept": "application/json, text/plain, */*",
        }

        print("📤 サーバーに直接POST送信中...")
        with open(FILE_PATH, "rb") as f:
            files = {"file": (os.path.basename(FILE_PATH), f, "text/plain")}
            res = requests.post(api_url, headers=headers, files=files)

        print("📡 レスポンスコード:", res.status_code)
        print("📄 レスポンス内容:", res.text[:500])

        if res.status_code == 200:
            print("✅ アップロード成功（403・401完全回避）")
        else:
            print("❌ アップロード失敗。レスポンスを確認してください。")

        browser.close()

if __name__ == "__main__":
    main()
