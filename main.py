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
    seen_urls = set()
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
            
            page_urls = []
            for l in links:
                url = l.get('href')
                if url not in page_urls: page_urls.append(url)

            for i, detail_url in enumerate(page_urls):
                if detail_url in seen_urls: continue
                
                print(f"  [{i+1}/{len(page_urls)}] 解析中...")
                detail_data = parse_detail_page(detail_url, headers, summary_len, now_jst)
                
                if detail_data:
                    all_data.append(detail_data)
                    seen_urls.add(detail_url)
                
                time.sleep(1.0 + margin_sec + random.uniform(0, 2.0))

        except Exception as e:
            print(f"エラー発生: {e}")
            break

    if all_data:
        df = pd.DataFrame(all_data)
        # 指定された列順に整理
        column_order = [
            "質問日時", "カテゴリ", "投稿者名", "経過時間", 
            "回答数", "閲覧数", "共感数", "回答リアクション総数",
            "注目度", "回答競争率", "注目/競争比", "ランキングポテンシャル",
            "受付終了まで", "URL", "本文冒頭"
        ]
        df = df.reindex(columns=[c for c in column_order if c in df.columns])
        
        now_str = now_jst.strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(output_dir, f"chiebukuro_analysis_{now_str}.csv")
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"\n--- 完了 ---")
        print(f"保存先: {file_path}")
    else:
        print("データが取得できませんでした。")

def parse_detail_page(url, headers, summary_len, now_jst):
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, "html.parser")

        # 1. 本文冒頭（改行徹底除去）
        content_tag = soup.select_one('h1[class*="ClapLv1TextBlock_Chie-TextBlock__Text__"]')
        summary = ""
        if content_tag:
            raw_text = content_tag.get_text(" ", strip=True)
            clean_text = re.sub(r'[\r\n\t\s]+', ' ', raw_text).strip()
            summary = (clean_text[:summary_len] + '...') if len(clean_text) > summary_len else clean_text

        cat_tag = soup.select_one('a[class*="ClapLv2QuestionItem_Chie-QuestionItem__SubAnchor__"]')
        user_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__UserName__"]')
        date_tag = soup.select_one('p[class*="ClapLv1UserInfo_Chie-UserInfo__Date__"]')
        ans_tag = soup.select_one('strong[class*="ClapLv2QuestionItem_Chie-QuestionItem__AnswerNumber__"]')
        limit_tag = soup.select_one('p[class*="ClapLv2QuestionItem_Chie-QuestionItem__DeadlineText__"]')
        
        ans_count = int(ans_tag.get_text(strip=True)) if ans_tag else 0
        
        # 2. 閲覧数
        view_count = 0
        sub_info_tags = soup.select('p[class*="ClapLv1TextBlock_Chie-TextBlock__Text--colorGray__"]')
        for tag in sub_info_tags:
            text = tag.get_text()
            if "閲覧" in text:
                match = re.search(r'([\d,]+)', text)
                if match: view_count = int(match.group(1).replace(',', ''))

        # 3. 共感数 (質問への「共感した」ボタンの数値)
        empathy_count = 0
        # 「共感した」というテキストを持つ要素を探す
        empathy_element = soup.find(lambda tag: tag.name in ["div", "p", "button"] and "共感した" in tag.get_text())
        if empathy_element:
            # 構造上、同じ親要素内のテキストから数字を探す
            parent_text = empathy_element.parent.get_text()
            match = re.search(r'共感した([\d,]+)', parent_text.replace(' ', ''))
            if match:
                empathy_count = int(match.group(1).replace(',', ''))
            else:
                # テキストに含まれない場合、隣接する要素から数字を抽出
                num_part = re.search(r'([\d,]+)', empathy_element.get_text())
                if num_part: empathy_count = int(num_part.group(1).replace(',', ''))

        # 4. 回答リアクション総数 (「なるほど」「そうだね」「ありがとう」の合計)
        reaction_total = 0
        reaction_labels = ["なるほど", "そうだね", "ありがとう"]
        # ラベルを探して、その次の要素（Countクラス）から数値を取る
        for label in reaction_labels:
            label_tags = soup.find_all(lambda tag: tag.name == "p" and label in tag.get_text())
            for lt in label_tags:
                # Countクラスを持つ兄弟要素を探す
                count_tag = lt.find_next_sibling(lambda tag: tag.name == "p" and "Count" in str(tag.get("class")))
                if count_tag:
                    try:
                        val = int(count_tag.get_text(strip=True).replace(',', ''))
                        reaction_total += val
                    except: pass

        # 5. 指標計算
        post_date_str = date_tag.get_text(strip=True) if date_tag else ""
        elapsed_text = ""
        popularity_score = 0.0
        potential_score = 0.0
        
        if post_date_str:
            try:
                post_dt = datetime.strptime(post_date_str, "%Y/%m/%d %H:%M").replace(tzinfo=timezone(timedelta(hours=+9)))
                diff = now_jst - post_dt
                total_min = diff.total_seconds() / 60
                
                d, h, m = diff.days, (diff.seconds // 3600), ((diff.seconds // 60) % 60)
                elapsed_text = f"{d}日{h}時間{m}分" if d > 0 else f"{h}時間{m}分"
                
                if total_min >= 0:
                    popularity_score = round(view_count / (total_min + 0.1), 3)
                    # ランキングポテンシャルの計算
                    potential_score = round(((empathy_count * 100) + (ans_count * 50) + (reaction_total * 30) + view_count) / (total_min + 1), 2)
            except: pass

        answer_ratio = round((ans_count / view_count) * 100, 2) if view_count > 0 else 0.0
        score_ratio = round(popularity_score / answer_ratio, 2) if answer_ratio > 0 else 0.0

        return {
            "質問日時": post_date_str,
            "カテゴリ": cat_tag.get_text(strip=True) if cat_tag else "未分類",
            "投稿者名": user_tag.get_text(strip=True).replace("さん", "") if user_tag else "匿名",
            "経過時間": elapsed_text,
            "回答数": ans_count,
            "閲覧数": view_count,
            "共感数": empathy_count,
            "回答リアクション総数": reaction_total,
            "注目度": popularity_score,
            "回答競争率": answer_ratio,
            "注目/競争比": score_ratio,
            "ランキングポテンシャル": potential_score,
            "受付終了まで": limit_tag.get_text(strip=True).replace("回答受付終了まで", "") if limit_tag else "不明",
            "URL": url,
            "本文冒頭": summary
        }
    except Exception as e:
        print(f"解析エラー({url}): {e}")
        return None

if __name__ == "__main__":
    scrape_chiebukuro(max_pages=5, output_dir="./", margin_sec=0.5)
