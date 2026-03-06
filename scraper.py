from google_play_scraper import app, reviews, Sort
from urllib.parse import urlparse, parse_qs
import json

def extract_package_name(url):
    """从 Google Play 链接中提取游戏包名 (id)"""
    parsed_url = urlparse(url)
    # 获取 URL 中的参数字典
    params = parse_qs(parsed_url.query)
    if 'id' in params:
        return params['id'][0]
    return None

def scrape_competitor_data(play_store_url, lang='en', country='us', review_count=5):
    """
    抓取竞品游戏的核心信息和评论
    :param play_store_url: 游戏的 Google Play 商店链接
    :param lang: 目标语言 (例如 'en', 'ja', 'zh-TW')
    :param country: 目标国家/地区 (例如 'us', 'jp', 'tw')
    :param review_count: 需要抓取的评论数量 (用于提取玩家痛点/爽点)
    """
    package_name = extract_package_name(play_store_url)
    
    if not package_name:
        return {"error": "无法从链接中解析出游戏包名，请检查链接格式。"}

    try:
        # 1. 抓取应用基础信息 (ASO 文案、评分、下载量等)
        print(f"正在抓取 {package_name} 的商店信息 (地区: {country}, 语言: {lang})...")
        app_info = app(
            package_name,
            lang=lang,
            country=country
        )

        # 2. 抓取近期有用的玩家评论
        print(f"正在抓取 {package_name} 的近期评论...")
        result, continuation_token = reviews(
            package_name,
            lang=lang,
            country=country,
            sort=Sort.HELPFULNESS, # 抓取“最有帮助”的评论，通常包含了详尽的优缺点分析
            count=review_count
        )

        # 3. 整理并精简需要喂给 AI 的数据
        # 去掉冗余字段，只保留对立项和文案生成有用的核心数据
        extracted_data = {
            "Game Name": app_info.get('title'),
            "Developer": app_info.get('developer'),
            "Installs": app_info.get('installs'),
            "Score": app_info.get('score'),
            "Summary": app_info.get('summary'), # 简短描述 (Short Description)
            "Full Description": app_info.get('description'), # 完整描述 (Full Description)
            "Top Reviews": [
                {
                    "score": r['score'], 
                    "content": r['content']
                } for r in result
            ]
        }
        
        return extracted_data

    except Exception as e:
        return {"error": f"抓取失败: {str(e)}"}

# ================= 测试运行 =================
if __name__ == "__main__":
    # 以《Survivor!.io》(弹壳特攻队) 的美区链接为例
    test_url = "https://play.google.com/store/apps/details?id=com.dxx.firenow&hl=en&gl=US"
    
    # 假设你的目标市场是美国 (en, us)
    competitor_data = scrape_competitor_data(test_url, lang='en', country='us', review_count=3)
    
    # 将结果格式化输出为 JSON 字符串，方便后续直接拼接到 Prompt 中
    print("\n--- 抓取结果 ---")
    print(json.dumps(competitor_data, indent=4, ensure_ascii=False))
