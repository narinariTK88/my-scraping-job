import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import random
import argparse
from datetime import datetime, timedelta, timezone

# --- 設定 ---
URL_LIST_FILE = "target_urls_to_analyze.csv"

def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

# フェーズ1: URLだけを取得して保存する
def save_urls(max_pages=10):
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
            for l in links:
                url = l.get('href')
                if url not in all_urls:
                    all_urls.append(url)
            print(f"  Page {page}: {len(links)} 件検知")
            time.sleep(1.0 + random.uniform(1.0, 3.0)) # 固定1s + ランダム1~3s
        except Exception as e:
            print(f"エラー: {e}")
            break

    if all_urls:
        pd.DataFrame(all_urls, columns=["URL"]).to_csv(URL_LIST_FILE, index=False, encoding="utf-8-sig")
        print(f"--- {len(all_urls)} 件のURLを {URL_LIST_FILE} に保存しました ---")

# フェーズ2: 保存されたURLを解析する
def analyze_urls(margin_sec=1.0):
    if not os.path.exists(URL_LIST_FILE):
        print(f"エラー: {URL_LIST_FILE} が見つかりません。先にURL収集を行ってください。")
        return

    session = get_session()
    df_urls = pd.read_csv(URL_LIST_FILE)
    target_urls = df_urls["URL"].tolist()
    
    jst = timezone(timedelta(hours=+9), 'JST')
    now_jst = datetime.now(jst)
    all_data = []

    print(f"--- フェーズ2: 詳細解析開始 (全 {len(target_urls)} 件) ---")
    for i, url in enumerate(target_urls):
        print(f"  [{i+1}/{len(target_urls)}] 解析中...")
        data = parse_detail_page(url, session, now_jst)
        if data:
            all_data.append(data)
        time.sleep(1.0 + margin_sec + random.uniform(0.0, 3.0)) # 固定1s + マージン + ランダム0~3s

    if all_data:
        df = pd.DataFrame(all_data)
        now_str = now_jst.strftime("%Y%m%d_%H%M%S")
        output_file = f"chiebukuro_analysis_{now_str}.csv"
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
        # 解析が終わったらURLリストは削除（次回重複防止のため）
        os.remove(URL_LIST_FILE)
        print(f"--- 解析完了: {output_file} ---")

def parse_detail_page(url, session, now_jst):
    try:
        res = session.get(url, timeout=15)
        soup = BeautifulSoup(res.content, "html.parser")
        
        # タイトル/本文
        content_tag = soup.select_one('h1[class*="ClapLv1TextBlock_Chie-TextBlock__Text__"]')
        summary = content_tag.get_text(" ", strip=True)[:50] if content_tag else ""
        summary = re.sub(r'[\r\n\t\s]+', ' ', summary).strip()

        # 数値取得
        ans_tag = soup.select_one('strong[class*="ClapLv2QuestionItem_Chie-QuestionItem__AnswerNumber__"]')
        ans_count = int(ans_tag.get_text(strip=True)) if ans_tag else 0
        
        view_count, empathy_count = 0, 0
        sub_info_tags = soup.select('p[class*="ClapLv1TextBlock_Chie-TextBlock__Text--colorGray__"]')
        for tag in sub_info_tags:
            text = tag.get_text()
            if "閲覧" in text:
                match = re.search(r'([\d,]+)', text)
                if match: view_count = int(match.group(1).replace(',', ''))
            if "共感した" in text:
                match = re.search(r'([\d,]+)', text)
                if match: empathy_count = int(match.group(1).replace(',', ''))

        reaction_total = 0
        for label in ["なるほど", "そうだね", "ありがとう"]:
            label_tags = soup.find_all(lambda tag: tag.name == "p" and label in tag.get_text())
            for lt in label_tags:
                count_tag = lt.find_next_sibling(lambda tag: tag.name == "p" and "Count" in str(tag.get("class")))
                if count_tag:
                    try: reaction_total += int(count_tag.get_text(strip=True).replace(',', ''))
                    except: pass

        # 指標計算
        date_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__Date__"]')
        post_date_str = date_tag.get_text(strip=True) if date_tag else ""
        elapsed_text, pop_score, pot_score = "0分", 0.0, 0.0
        
        if post_date_str:
            post_dt = datetime.strptime(post_date_str, "%Y/%m/%d %H:%M").replace(tzinfo=timezone(timedelta(hours=+9)))
            total_min = max(0.1, (now_jst - post_dt).total_seconds() / 60)
            h, m = divmod(int(total_min), 60)
            elapsed_text = f"{h}時間{m}分" if h > 0 else f"{m}分"
            pop_score = round(view_count / total_min, 3)
            pot_score = round(((empathy_count * 100) + (ans_count * 50) + (reaction_total * 30) + view_count) / (total_min + 1), 2)

        return {
            "質問日時": post_date_str, "経過時間": elapsed_text, "回答数": ans_count, 
            "閲覧数": view_count, "共感数": empathy_count, "回答リアクション総数": reaction_total,
            "注目度": pop_score, "ランキングポテンシャル": pot_score, "URL": url, "本文冒頭": summary
        }
    except: return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["save_urls", "analyze"], required=True)
    args = parser.parse_args()

    if args.mode == "save_urls":
        save_urls(max_pages=10) # 19時に実行
    else:
        analyze_urls(margin_sec=1.0) # 0時に実行
