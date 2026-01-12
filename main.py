import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import random
import argparse
from datetime import datetime, timedelta, timezone

URL_LIST_FILE = "target_urls_to_analyze.csv"

def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def save_urls(max_pages):
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
                if url not in all_urls: all_urls.append(url)
            print(f"  Page {page}: {len(links)} 件検知")
            time.sleep(1.0 + random.uniform(1.0, 3.0))
        except Exception as e:
            print(f"エラー: {e}"); break
    if all_urls:
        pd.DataFrame(all_urls, columns=["URL"]).to_csv(URL_LIST_FILE, index=False, encoding="utf-8-sig")
        print(f"--- {len(all_urls)} 件保存完了 ---")

def analyze_urls(margin_sec, summary_len):
    if not os.path.exists(URL_LIST_FILE):
        print("URLリストが見つかりません。"); return
    session, all_data = get_session(), []
    target_urls = pd.read_csv(URL_LIST_FILE)["URL"].tolist()
    jst = timezone(timedelta(hours=+9), 'JST')
    now_jst = datetime.now(jst)
    print(f"--- フェーズ2: 詳細解析開始 (全 {len(target_urls)} 件) ---")
    for i, url in enumerate(target_urls):
        print(f"  [{i+1}/{len(target_urls)}] 解析中...")
        data = parse_detail_page(url, session, now_jst, summary_len)
        if data: all_data.append(data)
        time.sleep(1.0 + margin_sec + random.uniform(0.0, 3.0))
    if all_data:
        df = pd.DataFrame(all_data)
        file_path = f"chiebukuro_analysis_{now_jst.strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        os.remove(URL_LIST_FILE)
        print(f"--- 解析完了: {file_path} ---")

def parse_detail_page(url, session, now_jst, summary_len):
    try:
        res = session.get(url, timeout=15)
        soup = BeautifulSoup(res.content, "html.parser")
        content_tag = soup.select_one('h1[class*="ClapLv1TextBlock_Chie-TextBlock__Text__"]')
        summary = content_tag.get_text(" ", strip=True) if content_tag else ""
        summary = (summary[:summary_len] + '...') if len(summary) > summary_len else summary
        summary = re.sub(r'[\r\n\t\s]+', ' ', summary).strip()
        ans_tag = soup.select_one('strong[class*="ClapLv2QuestionItem_Chie-QuestionItem__AnswerNumber__"]')
        ans_count = int(ans_tag.get_text(strip=True)) if ans_tag else 0
        v_count, e_count = 0, 0
        for tag in soup.select('p[class*="ClapLv1TextBlock_Chie-TextBlock__Text--colorGray__"]'):
            t = tag.get_text()
            if "閲覧" in t:
                m = re.search(r'([\d,]+)', t)
                if m: v_count = int(m.group(1).replace(',', ''))
            if "共感した" in t:
                m = re.search(r'([\d,]+)', t)
                if m: e_count = int(m.group(1).replace(',', ''))
        r_total = 0
        for L in ["なるほど", "そうだね", "ありがとう"]:
            tags = soup.find_all(lambda tag: tag.name == "p" and L in tag.get_text())
            for lt in tags:
                ct = lt.find_next_sibling(lambda tag: tag.name == "p" and "Count" in str(tag.get("class")))
                if ct: r_total += int(ct.get_text(strip=True).replace(',', ''))
        date_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__Date__"]')
        post_str = date_tag.get_text(strip=True) if date_tag else ""
        elapsed, pop, pot = "0分", 0.0, 0.0
        if post_str:
            dt = datetime.strptime(post_str, "%Y/%m/%d %H:%M").replace(tzinfo=timezone(timedelta(hours=+9)))
            total_m = max(0.1, (now_jst - dt).total_seconds() / 60)
            h, m = divmod(int(total_m), 60)
            elapsed = f"{h}時間{m}分" if h > 0 else f"{m}分"
            pop = round(v_count / total_m, 3)
            pot = round(((e_count * 100) + (ans_count * 50) + (r_total * 30) + v_count) / (total_m + 1), 2)
        return {"質問日時": post_str, "経過時間": elapsed, "回答数": ans_count, "閲覧数": v_count, "共感数": e_count, "回答リアクション総数": r_total, "注目度": pop, "ランキングポテンシャル": pot, "URL": url, "本文冒頭": summary}
    except: return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["save_urls", "analyze"], required=True)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--margin", type=float, default=1.0)
    parser.add_argument("--len", type=int, default=50)
    args = parser.parse_args()
    if args.mode == "save_urls": save_urls(args.pages)
    elif args.mode == "analyze": analyze_urls(args.margin, args.len)
