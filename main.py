import os
import time
import dropbox
from playwright.sync_api import sync_playwright

# ===== Dropbox 設定 =====
DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_PATH = "/tenton"

# ===== Tenton ログイン情報 =====
TENTON_USER = os.getenv("TENTON_USER")
TENTON_PASS = os.getenv("TENTON_PASS")

# ===== 共通ヘルパー =====
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"FATAL: Timeout waiting for selector '{selector}'") from e


def download_latest_file():
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=DROPBOX_REFRESH_TOKEN,
        app_key=DROPBOX_APP_KEY,
        app_secret=DROPBOX_APP_SECRET,
    )
    entries = dbx.files_list_folder(DROPBOX_PATH).entries
    latest = max(entries, key=lambda e: e.server_modified)
    _, res = dbx.files_download(latest.path_lower)
    file_path = latest.name
    with open(file_path, "wb") as f:
        f.write(res.content)
    print(f"Downloaded: {file_path}")
    return file_path


def login_and_open_upload_page():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    # ログインページへ
    page.goto("http://8.209.213.176/login")
    page.fill("input[placeholder='アカウント']", TENTON_USER)
    page.fill("input[placeholder='パスワード']", TENTON_PASS)
    page.click("button:has-text('ログイン')")
    print("✅ ログイン成功")

    # 言語切替（日本語）
    try:
        page.click("span:has-text('日本語')")
        print("✅ 言語を日本語に切替")
    except:
        print("⚠ 日本語切替スキップ")

    # アップロード画面へ遷移
    page.goto("http://8.209.213.176/orderManagement/orderInFo")
    safe_wait_selector(page, "text=アップロード")
    print("✅ アップロード画面表示確認")

    return page


# ===== ドロップダウン選択 =====
def select_dropdown_by_index(page, dropdown_index, option_index):
    dropdowns = page.query_selector_all("div.ant-select")
    if dropdown_index >= len(dropdowns):
        raise RuntimeError(f"ドロップダウン {dropdown_index} が見つかりません")
    dropdowns[dropdown_index].click()
    page.wait_for_selector("li[role='option']")
    options = page.query_selector_all("li[role='option']")
    if option_index >= len(options):
        raise RuntimeError(f"選択肢 {option_index} が存在しません (候補数={len(options)})")
    option_text = options[option_index].inner_text()
    options[option_index].click()
    print(f"✅ ドロップダウン {dropdown_index} → '{option_text}' を選択")


# ===== アップロード処理 =====
def upload_and_confirm(page, file_path):
    # ① 店舗種類 = アマゾン
    select_dropdown_by_index(page, 0, 0)

    # ② 店舗名 = アイプロダクト
    select_dropdown_by_index(page, 1, 0)

    # ③ 上传（アップロード）ボタンをクリック
    page.click("button:has-text('上传')")
    print("✅ 上传ボタンをクリック")

    # ④ input[type=file] にファイル添付
    safe_wait_selector(page, "input[type='file']")
    page.set_input_files("input[type='file']", file_path)
    print(f"✅ ファイル添付 {file_path}")

    # ⑤ 导入ボタンをクリック
    page.click("button:has-text('导 入')")
    print("✅ 导入ボタンをクリック")

    # ⑥ 一覧反映待ち
    page.wait_for_timeout(3000)
    print("✅ 一覧への反映確認")

    # ⑦ 一括確認
    page.click("button:has-text('一括確認')")
    print("✅ 一括確認ボタンをクリック")

    # ⑧ 确认
    page.click("button:has-text('确认')")
    print("✅ 确认ボタンをクリック")


# ===== メイン =====
def main():
    file_path = download_latest_file()
    page = login_and_open_upload_page()
    upload_and_confirm(page, file_path)


if __name__ == "__main__":
    main()
