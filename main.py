import os
import json
import dropbox
import requests
import time
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from googletrans import Translator
import math
import chardet

DROPBOX_PATH = "/tenton"
STATE_FILE = "state.json"
translator = Translator()
JST = timezone(timedelta(hours=9))


# --- 翻訳ユーティリティ ---
def translate_to_japanese(text):
    if not text:
        return text
    try:
        result = translator.translate(text, src='zh-cn', dest='ja')
        return result.text
    except Exception as e:
        return f"[翻訳失敗: {e}] 原文: {text}"


# --- 結果要約 ---
def summarize_orders(raw_text):
    try:
        data = json.loads(raw_text)
        result = data.get("result", {})
        if not isinstance(result, dict):
            msg = data.get("msg", raw_text)
            return translate_to_japanese(msg)

        grouped = {}
        for order_no, msg in result.items():
            jp_msg = translate_to_japanese(msg)
            grouped.setdefault(jp_msg, []).append(order_no)

        lines = []
        for msg, orders in grouped.items():
            order_list = ", ".join(orders[:10])
            more = f" …他{len(orders)-10}件" if len(orders) > 10 else ""
            lines.append(f"{msg}：{order_list}{more}")
        return "\n".join(lines)
    except Exception:
        return translate_to_japanese(raw_text)


# --- Chatwork通知 ---
def notify_chatwork(report_time, upload_log, confirm_log):
    token = os.environ.get("CHATWORK_TOKEN")
    room_id = "366280327"
    to_account_id = "10110346"
    to_display = "脇山友香(Yuka Wakiyama)さん"

    if not token or not room_id:
        print("⚠️ Chatwork通知スキップ（環境変数未設定）")
        return

    now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')

    upload_status = "✅ 成功" if "HTTP 200" in upload_log else "❌ 失敗"
    confirm_status = "✅ 成功" if "HTTP 200" in confirm_log else "❌ 失敗"

    upload_summary = summarize_orders(upload_log)
    confirm_summary = summarize_orders(confirm_log)

    body = f"""[To:{to_account_id}] {to_display}
🏗️【テントン自動処理レポート】

📦 対象データ：
Amazon注文レポート作成時刻：{report_time}

📤 アップロード結果：
{upload_status}
{upload_summary}

🚀 一括確認結果：
{confirm_status}
{confirm_summary}

⏰ 実行完了：{now_jst}（JST）
"""

    url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    headers = {"X-ChatWorkToken": token}

    try:
        res = requests.post(url, headers=headers, data={"body": body})
        print(f"📨 Chatwork通知送信結果: {res.status_code}")
    except Exception as e:
        print(f"❌ Chatwork通知エラー: {e}")


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
    return os.path.abspath(fname), latest.name


# --- Playwright util ---
def safe_wait_selector(page, selector, timeout=60000):
    try:
        return page.wait_for_selector(selector, timeout=timeout)
    except Exception:
        raise RuntimeError(f"Timeout waiting for selector '{selector}'")


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

    context.storage_state(path=STATE_FILE)
    context.close()

    print("💾 state.json 保存完了")


# --- メイン ---
def main():
    FILE_PATH, FILE_NAME = download_latest_file()

    base_name = FILE_NAME.replace(".txt", "").replace("Downloaded: ", "")
    try:
        utc_dt = datetime.strptime(base_name, "%Y-%m-%d %H:%M:%S")
        report_time = (utc_dt + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    except:
        report_time = base_name

    USERNAME = os.environ["TENTON_USER"]
    PASSWORD = os.environ["TENTON_PASS"]

    upload_log = ""
    confirm_log = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            # --- ログイン or セッション復元 ---
            if os.path.exists(STATE_FILE):
                context = browser.new_context(storage_state=STATE_FILE)
            else:
                login_and_save_state(browser, USERNAME, PASSWORD)
                context = browser.new_context(storage_state=STATE_FILE)

            page = context.new_page()
            page.goto("http://8.209.213.176/fundamentalData/goodInfo", timeout=300000)

            # --- 言語切替 ---
            try:
                page.click("span.ant-pro-drop-down")
                safe_wait_selector(page, "li[role='menuitem']")
                items = page.query_selector_all("li[role='menuitem']")
                if len(items) >= 2:
                    items[1].click()
            except:
                pass

            # --- Access Token 取得 ---
            access_token = page.evaluate("() => localStorage.getItem('Access-Token')")
            if not access_token:
                raise RuntimeError("Access-Tokenなし")

            access_token = access_token.strip('"')

            # --- アップロードAPI ---
            api_url = "http://8.209.213.176/api/back/order/importOrderYmx"
            headers = {
                "Authorization": access_token,
                "Accept": "application/json, text/plain, */*",
            }
            data = {
                "type": "1",
                "shopId": "6a7aaaf6342c40879974a8e9138e3b3b"
            }

            with open(FILE_PATH, "rb") as f:
                files = {"file": (os.path.basename(FILE_PATH), f, "text/plain")}
                res = requests.post(api_url, headers=headers, data=data, files=files)

            upload_log = f"HTTP {res.status_code}\n{res.text[:500]}"

            # ==========================================================
            # ① 反映チェック
            # ==========================================================
            list_url = "http://8.209.213.176/api/back/orderManagement/orderInfo"
            headers_common = {
                "Authorization": access_token,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            }

            prev_count = -1
            for i in range(9):
                res_list = requests.post(
                    list_url,
                    headers=headers_common,
                    json={"size": 200, "current": 1},
                    timeout=120,
                )

                if res_list.status_code != 200:
                    time.sleep(10)
                    continue

                data_list = res_list.json()
                records = data_list.get("result", {}).get("records", [])
                record_count = len(records)

                if record_count == prev_count and record_count > 0:
                    break

                prev_count = record_count
                time.sleep(10)

            # ==========================================================
            # ② ページング（UI仕様完全準拠）
            # ==========================================================
            all_records = []
            page_no = 1
            max_pages_safety = 1000

            while True:
                payload = {
                    "status": "1",
                    "current": page_no,
                    "size": 200,
                    "pageSize": 200,
                    "importStrTime": None,
                    "importEndTime": None,
                    "strTime": None,
                    "endTime": None,
                    "sortType": "DESC",
                    "sortName": "i.order_no"
                }

                try:
                    res_page = requests.post(
                        list_url,
                        headers=headers_common,
                        json=payload,
                        timeout=120,
                    )
                except Exception as e:
                    print(f"通信エラー: {e}")
                    break

                if res_page.status_code != 200:
                    break

                data_page = res_page.json()
                result = data_page.get("result", {}) or {}
                rec_page = result.get("records", []) or []
                total_pages = result.get("pages") or 1

                all_records.extend(rec_page)

                if page_no >= total_pages or not rec_page or len(rec_page) < 200:
                    break

                if page_no >= max_pages_safety:
                    break

                page_no += 1

            # ==========================================================
            # ③ 一括確認
            # ==========================================================
            time.sleep(10)

            if not all_records:
                confirm_log = "対象なし"
            else:
                order_ids = list({
                    r.get("id")
                    for r in all_records
                    if isinstance(r, dict)
                    and str(r.get("status")) == "1"
                })

                if not order_ids:
                    confirm_log = "IDなし"
                else:
                    confirm_url = "http://8.209.213.176/api/back/orderManagement/orderInfo/batchConfirmation"
                    confirm_res = requests.post(
                        confirm_url,
                        headers=headers_common,
                        json=order_ids,
                        timeout=120,
                    )
                    confirm_log = f"HTTP {confirm_res.status_code}\n{confirm_res.text[:500]}"

        except Exception as e:
            upload_log = upload_log or f"例外発生: {e}"
            confirm_log = confirm_log or "未実施（例外）"

        finally:
            browser.close()
            notify_chatwork(report_time, upload_log, confirm_log)


if __name__ == "__main__":
    main()
