import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import random
from datetime import datetime, timedelta, timezone

def scrape_chiebukuro(max_pages=1, output_dir="./", margin_sec=0.0, summary_len=50):
    base_list_url = "https://chiebukuro.yahoo.co.jp/question/list?flg=0&fr=common-navi"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    all_data = []
    # 経過時間の基準となるJST時刻
    jst = timezone(timedelta(hours=+9), 'JST')
    now_jst = datetime.now(jst)

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
                detail_data = parse_detail_page(detail_url, headers, summary_len, now_jst)
                if detail_data:
                    all_data.append(detail_data)
                
                rand_wait = random.uniform(0, 3.0)
                total_wait = 1.0 + margin_sec + rand_wait
                print(f"    (待機中: {total_wait:.2f}秒)")
                time.sleep(total_wait)

        except Exception as e:
            print(f"エラー発生: {e}")
            break

    if all_data:
        df = pd.DataFrame(all_data)

        # --- ここで列の順番を強制的に指定する ---
        column_order = [
            "質問日時", 
            "経過時間",   # 2列目
            "カテゴリ", 
            "投稿者名", 
            "回答数", 
            "閲覧数", 
            "受付終了まで", 
            "URL", 
            "本文冒頭"    # 最後
        ]
        # 存在する列のみで並び替え（エラー防止）
        df = df.reindex(columns=[c for c in column_order if c in df.columns])
        
        now_str = now_jst.strftime("%Y%m%d_%H%M%S")
        file_name = f"chiebukuro_{now_str}_{max_pages}pages.csv"
        file_path = os.path.join(output_dir, file_name)
        
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"\n--- 完了 ---")
        print(f"経過時間を2列目に配置しました。")
        print(f"保存先: {file_path}")
    else:
        print("データが取得できませんでした。")

def parse_detail_page(url, headers, summary_len, now_jst):
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, "html.parser")

        # 1. 本文冒頭
        content_tag = soup.select_one('h1[class*="ClapLv1TextBlock_Chie-TextBlock__Text__"]')
        if content_tag:
            raw_text = content_tag.get_text(" ", strip=True)
            clean_text = re.sub(r'[\r\n\s]+', ' ', raw_text)
            summary = (clean_text[:summary_len] + '...') if len(clean_text) > summary_len else clean_text
        else:
            summary = ""

        # 各タグの取得
        cat_tag = soup.select_one('a[class*="ClapLv2QuestionItem_Chie-QuestionItem__SubAnchor__"]')
        user_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__UserName__"]')
        date_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__Date__"]')
        ans_tag = soup.select_one('strong[class*="ClapLv2QuestionItem_Chie-QuestionItem__AnswerNumber__"]')
        limit_tag = soup.select_one('p[class*="ClapLv2QuestionItem_Chie-QuestionItem__DeadlineText__"]')
        
        # 経過時間の計算
        post_date_str = date_tag.get_text(strip=True) if date_tag else ""
        elapsed_time = ""
        if post_date_str:
            try:
                # 投稿日時を変換
                post_dt = datetime.strptime(post_date_str, "%Y/%m/%d %H:%M")
                post_dt = post_dt.replace(tzinfo=timezone(timedelta(hours=+9)))
                
                diff = now_jst - post_dt
                d = diff.days
                h, rem = divmod(diff.seconds, 3600)
                m, _ = divmod(rem, 60)
                elapsed_time = f"{d}日{h}時間{m}分" if d > 0 else f"{h}時間{m}分"
            except:
                elapsed_time = "計算不可"

        # 閲覧数
        view_count = 0
        sub_info_tag = soup.select_one('p[class*="ClapLv1TextBlock_Chie-TextBlock__Text--colorGray__"]')
        if sub_info_tag:
            text = sub_info_tag.get_text(strip=True)
            match = re.search(r'([\d,]+)閲覧', text)
            if match:
                view_count = int(match.group(1).replace(',', ''))

        return {
            "質問日時": post_date_str,
            "経過時間": elapsed_time,
            "カテゴリ": cat_tag.get_text(strip=True) if cat_tag else "未分類",
            "投稿者名": user_tag.get_text(strip=True).replace("さん", "") if user_tag else "匿名",
            "回答数": int(ans_tag.get_text(strip=True)) if ans_tag else 0,
            "閲覧数": view_count,
            "受付終了まで": limit_tag.get_text(strip=True).replace("回答受付終了まで", "") if limit_tag else "不明",
            "URL": url,
            "本文冒頭": summary
        }
    except:
        return None

if __name__ == "__main__":
    scrape_chiebukuro(max_pages=2, output_dir="./", margin_sec=0.5, summary_len=50)
