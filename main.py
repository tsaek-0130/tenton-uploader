import os
import sys
import time
import json
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# --------- 設定（環境変数） ---------
APP_KEY = os.environ.get("DROPBOX_APP_KEY")
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")
TENTON_USER = os.environ.get("TENTON_USER")
TENTON_PASS = os.environ.get("TENTON_PASS")

if not all([APP_KEY, APP_SECRET, REFRESH_TOKEN, TENTON_USER, TENTON_PASS]):
    print("Missing required environment variables. Exit.")
    sys.exit(1)

LOGIN_URL = "http://8.209.213.176/user/login"
UPLOAD_URL = "http://8.209.213.176/orderManagement/orderInFo"
FOLDER_PATH = "/tenton"
FILE_PATH = "latest_report.txt"

# --------- Dropbox: refresh -> access token ---------
def get_access_token():
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j["access_token"]

# --------- Dropbox: download latest file (using HTTP endpoints) ---------
def download_latest_from_dropbox(access_token, folder_path, out_path):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    r = requests.post(
        "https://api.dropboxapi.com/2/files/list_folder",
        headers=headers,
        json={"path": folder_path},
        timeout=30,
    )
    r.raise_for_status()
    entries = r.json().get("entries", [])
    if not entries:
        raise RuntimeError("No files in Dropbox folder.")
    latest = sorted(entries, key=lambda e: e["server_modified"], reverse=True)[0]
    path_lower = latest["path_lower"]

    dl_headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({"path": path_lower}),
    }
    r2 = requests.post("https://content.dropboxapi.com/2/files/download", headers=dl_headers, timeout=60)
    r2.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r2.content)
    print(f"Downloaded: {latest.get('name')}")

# --------- Playwright: helper safe click/query ---------
def safe_click_by_index(page, selector, idx=0, timeout=180000):
    """wait for selector, then click the idx-th element if exists"""
    elements = page.query_selector_all(selector)
    # If not yet present, wait up to timeout by polling
    waited = 0
    interval = 0.5
    while len(elements) <= idx and waited < (timeout / 1000.0):
        time.sleep(interval)
        waited += interval
        elements = page.query_selector_all(selector)
    if len(elements) <= idx:
        raise RuntimeError(f"No element for selector '{selector}' index {idx} after {timeout}ms")
    elements[idx].click()
    return elements[idx]

def safe_wait_selector(page, selector, timeout=180000):
    """wrapper to use Playwright wait_for_selector and convert exceptions"""
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except PWTimeout as e:
        raise RuntimeError(f"Timeout waiting for selector '{selector}'") from e

# --------- Main flow ---------
def main():
    try:
        # Dropbox
        token = get_access_token()
        download_latest_from_dropbox(token, FOLDER_PATH, FILE_PATH)

        # Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # 1) ログイン
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=180000)
            safe_wait_selector(page, "input#username", timeout=120000)
            page.fill("input#username", TENTON_USER)
            page.fill("input#password", TENTON_PASS)
            safe_click_by_index(page, "button.login-button", 0, timeout=60000)
            # wait for main app load (network idle or a reliable element)
            # we wait for the language dropdown to appear (page-specific)
            safe_wait_selector(page, "span.ant-pro-drop-down", timeout=180000)
            print("✅ ログイン成功")

            # 2) 言語切替（文字列は一切使わず、DOM index ベース）
            try:
                # open language dropdown
                safe_click_by_index(page, "span.ant-pro-drop-down", 0, timeout=60000)
                # wait menu items, click second item (index=1) -> 日本語と仮定
                safe_wait_selector(page, "li[role='menuitem']", timeout=60000)
                safe_click_by_index(page, "li[role='menuitem']", 1, timeout=60000)
                # give UI time to apply
                time.sleep(2)
                print("✅ 言語をインデックス指定で切替（2番目を選択）")
            except Exception as e:
                print("⚠️ 言語切替に失敗（続行）:", e)

            # 3) アップロードページへ移動・待機（class ベースのみ）
            page.goto(UPLOAD_URL)
            # wait for at least one primary button to appear (max 3min)
            safe_wait_selector(page, "button.ant-btn.ant-btn-primary", timeout=180000)
            print("✅ アップロード画面表示確認")

            # 4) 開くボタン（最初の primary を押してモーダルを起動）
            safe_click_by_index(page, "button.ant-btn.ant-btn-primary", 0, timeout=60000)
            # wait for store selectors to be attached
            safe_wait_selector(page, "div.ant-select-selector", timeout=60000)

            # 5) 店舗種類選択（indexベースで最初の selector を使い、title 属性で選択）
            # open first selector
            safe_click_by_index(page, "div.ant-select-selector", 0, timeout=60000)
            # choose the element whose title equals 'アマゾン' by querying all matching titles
            # We'll attempt to find div[title='アマゾン'] and click the first match
            elems = page.query_selector_all("div[title='アマゾン']")
            if not elems:
                raise RuntimeError("店舗種類 'アマゾン' の選択肢が見つかりません")
            elems[0].click()
            time.sleep(0.5)

            # 6) 店舗名選択（2番目 selector）
            safe_click_by_index(page, "div.ant-select-selector", 1, timeout=60000)
            elems2 = page.query_selector_all("div[title='アイプロダクト']")
            if not elems2:
                raise RuntimeError("店舗名 'アイプロダクト' の選択肢が見つかりません")
            elems2[0].click()
            time.sleep(0.5)

            # 7) wait until input[type=file] is attached (modal may enable it)
            safe_wait_selector(page, "input[type='file']", timeout=120000)
            # set files
            page.set_input_files("input[type='file']", FILE_PATH)
            time.sleep(0.3)

            # 8) modal のアップロード確定ボタン（1つ目が開くボタン、ここでは2つ目の primary と仮定）
            # collect primaries again and click the second one when exists
            primaries = page.query_selector_all("button.ant-btn.ant-btn-primary")
            if len(primaries) < 2:
                # fallback: click last one
                if primaries:
                    primaries[-1].click()
                else:
                    raise RuntimeError("モーダル内のアップロード確定ボタンが見つかりません")
            else:
                primaries[1].click()
            print("✅ ファイル添付してアップロード確定をクリック")

            # 9) 一覧に反映されるのを待つ（checkbox が出るまで）
            safe_wait_selector(page, "input[type='checkbox']", timeout=180000)
            # click the first checkbox (header select all) — index 0
            checkboxes = page.query_selector_all("input[type='checkbox']")
            if not checkboxes:
                raise RuntimeError("チェックボックスが見つかりません")
            checkboxes[0].click()
            print("✅ 一覧の一番上チェック（全選択）")

            # 10) 一括確認ボタン（classベース、アンカー）
            # click first anchor with class ant-btn ant-btn-primary (assume it's 一括確認)
            anchors = page.query_selector_all("a.ant-btn.ant-btn-primary")
            if not anchors:
                # fallback: try buttons with same class
                anchors_btns = page.query_selector_all("button.ant-btn.ant-btn-primary")
                if anchors_btns:
                    anchors_btns[0].click()
                else:
                    raise RuntimeError("一括確認ボタンが見つかりません")
            else:
                anchors[0].click()
            print("✅ 一括確認ボタンをクリック")

            # 11) モーダル確認ボタン（小さい primary ボタン）
            # locate small primary button with class including ant-btn-sm
            time.sleep(0.5)
            sm_btns = page.query_selector_all("button.ant-btn.ant-btn-primary.ant-btn-sm")
            if sm_btns:
                sm_btns[0].click()
            else:
                # fallback: click any primary small-ish button via index
                primaries2 = page.query_selector_all("button.ant-btn.ant-btn-primary")
                if primaries2:
                    primaries2[0].click()
            print("✅ 確認ボタンをクリック")

            # 12) エラーチェック：もしモーダル body が出ていたら中身を取得してログ出力
            try:
                modal = page.wait_for_selector(".ant-modal-body", timeout=5000)
                if modal:
                    txt = modal.inner_text()
                    print("⚠️ エラー画面検出:", txt)
                else:
                    print("✅ エラーなし（モーダル未表示）")
            except PWTimeout:
                print("✅ エラーなし（モーダル未表示）")

            browser.close()
            print("All done.")
    except Exception as e:
        print("FATAL:", str(e))
        raise

if __name__ == "__main__":
    main()
