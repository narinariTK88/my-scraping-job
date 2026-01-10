import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
from datetime import datetime, timedelta, timezone

def scrape_chiebukuro(max_pages=1, output_dir="./", margin_sec=0.0, summary_len=50):
    base_list_url = "https://chiebukuro.yahoo.co.jp/question/list?flg=0&fr=common-navi"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    wait_time = 1.0 + margin_sec
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    all_data = []

    for page in range(1, max_pages + 1):
        print(f"--- {page}/{max_pages} ページ目を処理中 ---")
        list_url = f"{base_list_url}&page={page}"
        
        try:
            res = requests.get(list_url, headers=headers)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, "html.parser")
            
            links = soup.find_all('a', href=re.compile(r'https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q\d+'))
            target_urls = list(dict.fromkeys([l.get('href') for l in links]))

            for i, detail_url in enumerate(target_urls):
                print(f"  [{i+1}/{len(target_urls)}] 解析中...")
                detail_data = parse_detail_page(detail_url, headers, summary_len)
                if detail_data:
                    all_data.append(detail_data)
                
                time.sleep(wait_time)

        except Exception as e:
            print(f"エラー発生: {e}")
            break

    if all_data:
        df = pd.DataFrame(all_data)
        
        # JSTでファイル名生成
        jst = timezone(timedelta(hours=+9), 'JST')
        now_str = datetime.now(jst).strftime("%Y%m%d_%H%M%S")
        
        file_path = os.path.join(output_dir, f"chiebukuro_{now_str}_{max_pages}pages.csv")
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"\n--- 完了 ---")
        print(f"設定: {summary_len}文字(改行除去済), JST時刻保存")
        print(f"保存先: {file_path}")
    else:
        print("データが取得できませんでした。")

def parse_detail_page(url, headers, summary_len):
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.content, "html.parser")

        # 1. 本文冒頭 (改行をスペースに置換)
        content_tag = soup.select_one('h1[class*="ClapLv1TextBlock_Chie-TextBlock__Text__"]')
        if content_tag:
            raw_text = content_tag.get_text(" ", strip=True)
            # 改行と連続スペースを除去
            clean_text = re.sub(r'[\r\n\s]+', ' ', raw_text)
            summary = (clean_text[:summary_len] + '...') if len(clean_text) > summary_len else clean_text
        else:
            summary = ""

        # 2. カテゴリ
        cat_tag = soup.select_one('a[class*="ClapLv2QuestionItem_Chie-QuestionItem__SubAnchor__"]')
        category = cat_tag.get_text(strip=True) if cat_tag else "未分類"

        # 3. 投稿者名
        user_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__UserName__"]')
        user_name = user_tag.get_text(strip=True).replace("さん", "") if user_tag else "匿名"
        
        # 4. 質問日時
        date_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__Date__"]')
        post_date = date_tag.get_text(strip=True) if date_tag else ""
        
        # 5. 回答数
        ans_tag = soup.select_one('strong[class*="ClapLv2QuestionItem_Chie-QuestionItem__AnswerNumber__"]')
        ans_count = ans_tag.get_text(strip=True) if ans_tag else "0"
        
        # 6. 閲覧数
        view_count = 0
        sub_info_tag = soup.select_one('p[class*="ClapLv1TextBlock_Chie-TextBlock__Text--colorGray__"]')
        if sub_info_tag:
            text = sub_info_tag.get_text(strip=True)
            match = re.search(r'([\d,]+)閲覧', text)
            if match:
                view_count = int(match.group(1).replace(',', ''))
        
        # 7. 受付終了までの日数
        limit_tag = soup.select_one('p[class*="ClapLv2QuestionItem_Chie-QuestionItem__DeadlineText__"]')
        limit_text = limit_tag.get_text(strip=True).replace("回答受付終了まで", "") if limit_tag else "不明"

        return {
            "質問日時": post_date,
            "カテゴリ": category,
            "投稿者名": user_name,
            "回答数": int(ans_count),
            "閲覧数": view_count,
            "受付終了まで": limit_text,
            "URL": url,
            "本文冒頭": summary
        }
    except:
        return None

if __name__ == "__main__":
    scrape_chiebukuro(max_pages=2, output_dir="./scraped_data", margin_sec=0.5, summary_len=50)
