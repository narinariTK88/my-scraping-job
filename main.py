import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import random
import argparse
from datetime import datetime, timedelta, timezone

# --- フォルダ構成の設定 ---
DATA_ROOT = "data"
RAW_DIR = os.path.join(DATA_ROOT, "raw")     # 日々の解析済みCSV用
TMP_DIR = os.path.join(DATA_ROOT, "tmp")     # URLリスト等の一時ファイル用
# DATASET_DIR = os.path.join(DATA_ROOT, "dataset") # 将来の学習用ラベルデータ用

URL_LIST_FILE = os.path.join(TMP_DIR, "target_urls_to_analyze.csv")

def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def ensure_directories():
    """必要なすべてのフォルダ構造を作成する"""
    for d in [RAW_DIR, TMP_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)
            print(f"フォルダ作成: {d}")

def safe_extract_int(text):
    if not text: return 0
    match = re.search(r'([\d,]+)', text)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def save_urls(max_pages):
    ensure_directories()
    session = get_session()
    all_urls = []
    print(f"--- フェーズ1: URL収集開始 (最大 {max_pages} ページ) ---")
    
    for page in range(1, max_pages + 1):
        list_url = f"https://chiebukuro.yahoo.co.jp/question/list?flg=0&fr=common-navi&page={page}"
        try:
            res = session.get(list_url, timeout=15)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, "html.parser")
            links = soup.find_all('a', href=re.compile(r'https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q\d+'))
            count_on_page = 0
            for l in links:
                url = l.get('href')
                if url not in all_urls:
                    all_urls.append(url)
                    count_on_page += 1
            print(f"  Page {page}: {count_on_page} 件検知 (累計: {len(all_urls)})")
            time.sleep(1.0 + random.uniform(1.0, 2.0))
        except Exception as e:
            print(f"一覧取得エラー: {e}")
            break

    if all_urls:
        pd.DataFrame(all_urls, columns=["URL"]).to_csv(URL_LIST_FILE, index=False, encoding="utf-8-sig")
        print(f"--- {len(all_urls)} 件のURLを {URL_LIST_FILE} に保存しました ---")
    return all_urls

def analyze_urls(margin_sec, summary_len):
    ensure_directories()
    if not os.path.exists(URL_LIST_FILE):
        print(f"エラー: {URL_LIST_FILE} が見つかりません。")
        return

    session = get_session()
    df_urls = pd.read_csv(URL_LIST_FILE)
    target_urls = df_urls["URL"].tolist()
    
    jst = timezone(timedelta(hours=+9), 'JST')
    all_data = []

    print(f"--- フェーズ2: 詳細解析開始 (全 {len(target_urls)} 件) ---")
    for i, url in enumerate(target_urls):
        current_id = i + 1
        now_jst = datetime.now(jst)
        print(f"  [{current_id}/{len(target_urls)}] 解析中...")
        data = parse_detail_page(url, session, now_jst, summary_len, current_id)
        if data:
            all_data.append(data)
        time.sleep(1.0 + margin_sec + random.uniform(0.0, 2.0))

    if all_data:
        df = pd.DataFrame(all_data)
        column_order = [
            "ID", "質問日時", "カテゴリ", "投稿者名", "経過時間", 
            "回答数", "閲覧数", "回答難易度", "共感数", "回答リアクション総数",
            "注目度", "回答競争率", "注目/競争比", "ランキングポテンシャル",
            "受付終了まで", "URL", "本文冒頭",
            "マイフラグ", "ベストアンサーフラグ"
        ]
        df = df.reindex(columns=column_order)
        df["マイフラグ"] = 0
        df["ベストアンサーフラグ"] = 0
        
        final_now = datetime.now(jst)
        filename = f"chiebukuro_analysis_{final_now.strftime('%Y%m%d_%H%M%S')}.csv"
        file_path = os.path.join(RAW_DIR, filename) # rawフォルダに保存
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"--- 解析完了: {file_path} ---")
        return df

def parse_detail_page(url, session, now_jst, summary_len, current_id):
    all_reaction_total = 0
    page_count = 1
    try:
        res = session.get(url, timeout=15)
        if res.status_code != 200: return None
        soup = BeautifulSoup(res.content, "html.parser")
        
        content_tag = soup.select_one('h1[class*="ClapLv1TextBlock_Chie-TextBlock__Text__"]')
        summary = ""
        if content_tag:
            raw_text = content_tag.get_text(" ", strip=True)
            summary = re.sub(r'[\r\n\t\s]+', ' ', raw_text).strip()
            summary = (summary[:summary_len] + '...') if len(summary) > summary_len else summary

        user_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__Date__"]')
        post_str = user_tag.get_text(strip=True) if user_tag else ""
        user_name_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__UserName__"]')
        user_name = user_name_tag.get_text(strip=True).replace("さん", "") if user_name_tag else "匿名"
        cat_tag = soup.select_one('a[class*="ClapLv2QuestionItem_Chie-QuestionItem__SubAnchor__"]')
        category = cat_tag.get_text(strip=True) if cat_tag else "未分類"
        
        ans_tag = soup.select_one('strong[class*="ClapLv2QuestionItem_Chie-QuestionItem__AnswerNumber__"]')
        ans_count = safe_extract_int(ans_tag.get_text()) if ans_tag else 0
        
        v_count, e_count = 0, 0
        all_gray_texts = soup.select('p[class*="Chie-TextBlock__Text--colorGray"]')
        for p in all_gray_texts:
            txt = p.get_text()
            if "閲覧" in txt: v_count = safe_extract_int(txt)
            if "共感" in txt: e_count = safe_extract_int(txt)
        if e_count == 0:
            e_tag = soup.find("strong", class_=re.compile(r"ReactionCounter.*TextCount"))
            if e_tag: e_count = safe_extract_int(e_tag.get_text())

        while True:
            for label in ["なるほど", "そうだね", "ありがとう"]:
                label_tags = soup.find_all(lambda tag: tag.name == "p" and label in tag.get_text())
                for lt in label_tags:
                    count_tag = lt.find_next_sibling(lambda t: t.name == "p" and "Count" in str(t.get("class", "")))
                    if count_tag:
                        all_reaction_total += safe_extract_int(count_tag.get_text())
            next_link = soup.select_one('a[class*="Pagination__Anchor--Next"]')
            if next_link and next_link.get('href') and page_count < 10:
                next_url = next_link.get('href')
                if next_url.startswith('/'): next_url = "https://chiebukuro.yahoo.co.jp" + next_url
                time.sleep(1.0 + random.uniform(0.5, 1.0))
                res = session.get(next_url, timeout=15)
                if res.status_code != 200: break
                soup = BeautifulSoup(res.content, "html.parser")
                page_count += 1
            else: break

        limit_tag = soup.select_one('p[class*="ClapLv2QuestionItem_Chie-QuestionItem__DeadlineText__"]')
        deadline = limit_tag.get_text(strip=True).replace("回答受付終了まで", "") if limit_tag else "不明"
        
        elapsed, pop, pot, comp_rate, ratio, ans_diff = "0分", 0.0, 0.0, 0.0, 0.0, 0.0
        if post_str:
            try:
                dt = datetime.strptime(post_str, "%Y/%m/%d %H:%M").replace(tzinfo=timezone(timedelta(hours=+9)))
                total_m = max(0.1, (now_jst - dt).total_seconds() / 60)
                h, m = divmod(int(total_m), 60)
                elapsed = f"{h}時間{m}分" if h > 0 else f"{m}分"
                pop = round(v_count / total_m, 3)
                comp_rate = round((ans_count / v_count * 100), 2) if v_count > 0 else 0.0
                ans_diff = round(v_count / ans_count, 1) if ans_count > 0 else float(v_count)
                ratio = round(pop / comp_rate, 2) if comp_rate > 0 else 0.0
                pot = round(((e_count * 100) + (ans_count * 50) + (all_reaction_total * 30) + v_count) / (total_m + 1), 2)
            except: pass

        return {
            "ID": current_id, "質問日時": post_str, "カテゴリ": category, "投稿者名": user_name, "経過時間": elapsed,
            "回答数": ans_count, "閲覧数": v_count, "回答難易度": ans_diff, "共感数": e_count, "回答リアクション総数": all_reaction_total,
            "注目度": pop, "回答競争率": comp_rate, "注目/競争比": ratio, "ランキングポテンシャル": pot,
            "受付終了まで": deadline, "URL": url, "本文冒頭": summary
        }
    except Exception as e:
        return None

if __name__ == "__main__":
    import sys
    is_colab = 'google.colab' in sys.modules
    if is_colab:
        save_urls(max_pages=2)
        analyze_urls(margin_sec=1.0, summary_len=50)
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--mode", choices=["save_urls", "analyze"], required=True)
        parser.add_argument("--pages", type=int, default=10)
        parser.add_argument("--margin", type=float, default=1.0)
        parser.add_argument("--len", type=int, default=50)
        args = parser.parse_args()
        if args.mode == "save_urls": save_urls(max_pages=args.pages)
        elif args.mode == "analyze": analyze_urls(margin_sec=args.margin, summary_len=args.len)
