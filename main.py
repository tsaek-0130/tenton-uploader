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
# モーダル内の「导入」(青) を確実に押す（文字列非依存）
# ==============================
def click_modal_primary_import(page, timeout_sec=60):
    """
    モーダル内の primary ボタン（＝导入）を、テキストに依存せず押す。
    - modal スコープ: ant-modal / ant-modal-footer / role=dialog
    - 出るまでリトライ
    """
    print("⏳ 导入ボタンをリトライ探索中...")
    end = time.time() + timeout_sec
    while time.time() < end:
        # まずモーダルの存在を確認（attachedでOK）
        modal = page.query_selector("div.ant-modal, div[role='dialog']")
        if modal:
            # モーダル内の primary を優先的に探索
            buttons = modal.query_selector_all("button.ant-btn-primary")
            if not buttons:
                # フッター直指定のケースにも対応
                buttons = page.query_selector_all("div.ant-modal-footer button.ant-btn-primary")
            if buttons:
                # 一番右（最後）を押すのが通例で「导入」
                try:
                    # 念のため可視化待ち（ただし hidden でも click は通ることが多いので短め）
                    page.wait_for_timeout(200)
                    buttons[-1].click()
                    print("✅ 导入ボタン押下（モーダル内・index指定）")
                    return True
                except Exception as e:
                    print(f"⚠️ 导入ボタン押下トライ中エラー: {e}")
        # モーダルの描画・再描画待ち
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
        print("🌐 現在のURL:", page.url)

        # (5) 导入ボタン（青）をクリック（モーダル限定・文字列非依存・リトライ）
        if not click_modal_primary_import(page, timeout_sec=60):
            # デバッグ用出力
            page.screenshot(path="debug_screenshot_modal.png", full_page=True)
            with open("debug_modal.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError("❌ 导入ボタンが見つかりません")

        # (6) エラーモーダル（提示）を検出してログ出力（古い注文など）
        print("⏳ エラーモーダル（提示）検出を待機中...")
        error_found = False
        try:
            page.wait_for_selector("div.ant-modal-confirm", timeout=8000)
            print("⚠️ エラーモーダルを検出")
            error_found = True

            # エラーメッセージ抽出（span/div のテキストを全部ログ出力）
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

            # 「知道了」ボタンを押して閉じる
            know_btns = page.query_selector_all("div.ant-modal-confirm button.ant-btn-primary")
            if know_btns:
                know_btns[-1].click()
                print("✅ 知道了ボタン押下（エラーモーダル閉じ）")

        except Exception:
            print("✅ エラーモーダルなし（正常）")

        # (7) 一覧反映（checkboxが出るまで最大60秒待機）
        print("⏳ 一覧反映を待機中...")
        try:
            page.wait_for_selector("input[type='checkbox']", state="visible", timeout=60000)
            print("✅ 一覧表示を検出（checkboxあり）")
        except Exception:
            page.screenshot(path="debug_screenshot_list.png", full_page=True)
            with open("debug_list.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError("❌ 一覧反映が確認できません。debug_list.htmlを確認してください。")

        # (8) 一括確認 → 确认（常に実行）
        print("⏳ 一括確認処理を実行中...")
        try:
            safe_click_by_index(page, "input[type='checkbox']", 0)
            safe_click_by_index(page, "button.ant-btn", 0)
            safe_click_by_index(page, "button.ant-btn-primary", -1)
            print("✅ 一括確認完了")
        except Exception as e:
            print(f"⚠️ 一括確認処理でエラー: {e}")

        # (9) 結果まとめ
        if error_found:
            print("⚠️ 一部注文は既存注文としてスキップされました（上記ログ参照）")
        else:
            print("✅ 全注文が正常に取り込まれました")

        browser.close()

if __name__ == "__main__":
    main()
