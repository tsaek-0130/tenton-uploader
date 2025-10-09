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

        # セッション復元 or ログイン
        if os.path.exists(STATE_FILE):
            print("✅ 保存済みセッションを使用")
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            login_and_save_state(browser, USERNAME, PASSWORD)
            context = browser.new_context(storage_state=STATE_FILE)

        page = context.new_page()
        page.goto("http://8.209.213.176/fundamentalData/goodInfo", timeout=300000)
        print("✅ アップロード画面へアクセス完了")

        # --- 言語切替 ---
        try:
            page.click("span.ant-pro-drop-down")
            safe_wait_selector(page, "li[role='menuitem']")
            items = page.query_selector_all("li[role='menuitem']")
            if len(items) >= 2:
                items[1].click()
            print("✅ 言語を日本語に切替")
        except Exception as e:
            print("⚠️ 言語切替失敗:", e)

        # --- ✅ localStorageからAccess-Token取得 ---
        print("🔑 localStorageからAccess-Token取得中...")
        access_token = page.evaluate("() => localStorage.getItem('Access-Token')")
        if not access_token:
            raise RuntimeError("❌ localStorageにAccess-Tokenが見つかりませんでした")

        access_token = access_token.strip('"')
        print(f"✅ Access-Token取得成功: {access_token[:20]}...")

        # --- ✅ API送信（导入） ---
        api_url = "http://8.209.213.176/api/back/order/importOrderYmx"
        headers = {
            "Authorization": access_token,
            "Accept": "application/json, text/plain, */*",
        }
        data = {
            "type": "1",  # 店铺类型 (1 = 亚马逊)
            "shopId": "6a7aaaf6342c40879974a8e9138e3b3b"  # 店铺名称 (アイプロダクト)
        }

        print("📤 サーバーに直接POST送信中...")
        with open(FILE_PATH, "rb") as f:
            files = {"file": (os.path.basename(FILE_PATH), f, "text/plain")}
            res = requests.post(api_url, headers=headers, data=data, files=files)

        print("📡 レスポンスコード:", res.status_code)
        print("📄 レスポンス内容:", res.text[:500])

        if res.status_code == 200:
            print("✅ アップロード成功（403・401完全回避・店铺类型OK）")
        else:
            print("❌ アップロード失敗。レスポンスを確認してください。")

        # --- ✅ 一括確認フェーズ ---
        print("🚀 一括確認フェーズ開始...")

        list_url = "http://8.209.213.176/api/back/orderManagement/orderInfo?size=200&current=1"
        try:
            res_list = requests.get(
                list_url,
                headers={
                    "Authorization": access_token,
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=120,
            )

            if res_list.status_code != 200:
                print(f"❌ 注文一覧取得失敗: {res_list.status_code}")
                browser.close()
                return

            # --- JSON安全パース ---
            try:
                data = res_list.json()
            except Exception:
                data = json.loads(res_list.text)

            result = data.get("result")
            # 👇ここで「文字列型ならjson.loads」してdict化
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except Exception as e:
                    print(f"❌ result のJSONデコードに失敗: {e}")
                    print(result[:300])
                    browser.close()
                    return

            # --- records 抽出 ---
            records = result.get("records", [])
            order_ids = [r["id"] for r in records if isinstance(r, dict) and r.get("id")]

            print(f"📦 一括確認対象ID数: {len(order_ids)}")
            if not order_ids:
                print("⚠️ 対象IDがありません。スキップします。")
                browser.close()
                return

            # --- 一括確認API呼び出し ---
            confirm_url = "http://8.209.213.176/api/back/orderManagement/orderInfo/batchConfirmation"
            confirm_res = requests.post(
                confirm_url,
                headers={
                    "Authorization": access_token,
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                },
                json=order_ids,
                timeout=120,
            )

            print("📡 一括確認レスポンスコード:", confirm_res.status_code)
            print("📄 内容:", confirm_res.text[:500])

            if confirm_res.status_code == 200:
                try:
                    body = confirm_res.json()
                except Exception:
                    body = {}
                if body.get("code") == 10000:
                    print("✅ 一括確認 成功！（エラーなし）")
                else:
                    print(f"⚠️ 一括確認エラー: {body.get('msg')}")
            else:
                print("❌ 一括確認API呼び出し失敗")

        except Exception as e:
            print(f"❌ 一括確認フェーズ中に例外発生: {e}")


        browser.close()

if __name__ == "__main__":
    main()
