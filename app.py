import streamlit as st
import json
from urllib.parse import urlparse, parse_qs
from google_play_scraper import app as play_app, reviews, Sort
from google import genai
from google.genai import types

# ================= 1. 核心功能函数 =================

def extract_package_name(url):
    """提取包名"""
    parsed_url = urlparse(url)
    params = parse_qs(parsed_url.query)
    if 'id' in params:
        return params['id'][0]
    return None

def scrape_play_store(url, lang='en', country='us'):
    """抓取 Google Play 商店数据"""
    package_name = extract_package_name(url)
    if not package_name:
        return None
    try:
        app_info = play_app(package_name, lang=lang, country=country)
        result, _ = reviews(package_name, lang=lang, country=country, sort=Sort.MOST_RELEVANT, count=5)
        
        return {
            "Game Name": app_info.get('title'),
            "Developer": app_info.get('developer'),
            "Installs": app_info.get('installs'),
            "Summary": app_info.get('summary'),
            "Top Reviews": [{"score": r['score'], "content": r['content']} for r in result]
        }
    except Exception as e:
        st.error(f"抓取 {package_name} 失败: {e}")
        return None

def generate_pitch(scraped_data, market, gameplay, art):
    """调用 Gemini 2.5 Flash-lite 生成立项建议与美术提示词"""
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)

    prompt = f"""
    你现在是一位资深的海外移动游戏发行与 UA (用户获取) 专家。
    请根据以下信息，为新游戏立项生成高质量的商店测试素材和美术主视图提示词。

    【项目基本设定】
    - 目标市场: {market}
    - 核心玩法: {gameplay}
    - 美术方向: {art}

    【对标竞品情报 (来自 Google Play)】
    {json.dumps(scraped_data, ensure_ascii=False, indent=2)}

    【任务要求】
    请结合竞品的痛点与卖点，严格按照以下 JSON 格式输出结果：
    {{
      "suggested_names": [
        {{"name": "英文游戏名1", "reason": "中文解释说明为什么适合该市场和玩法"}}
      ],
      "aso_versions": {{
        "Version_A_Gameplay": "【玩法驱动型/侧重留存】强调核心机制、外围养成与局内战斗的结构、数值成长。适合硬核玩家。",
        "Version_B_Worldview": "【世界观驱动型/侧重沉浸】强调背景设定、角色塑造和美术氛围。",
        "Version_C_UA_Acquisition": "【买量转化型/侧重吸量】强调爽点、诱导性强，使用极具点击欲的 ASO 话术。"
      }},
      "key_art_prompts": {{
        "Version_A_Gameplay": "直接输出用于 Midjourney 的纯英文提示词。画面内容需展现游戏实际的战斗或核心操作感。结尾加上 --ar 16:9 --v 6.0",
        "Version_B_Worldview": "直接输出用于 Midjourney 的纯英文提示词。画面内容需展现宏大的背景设定或角色特写（如 Q版主角）。结尾加上 --ar 16:9 --v 6.0",
        "Version_C_UA_Acquisition": "直接输出用于 Midjourney 的纯英文提示词。画面需具备极强的买量吸睛要素（如强烈的色彩对比、密集的怪物群、夸张的伤害数字感等）。结尾加上 --ar 16:9 --v 6.0"
      }}
    }}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash-lite',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.75
        )
    )
    return json.loads(response.text)


# ================= 2. Streamlit UI 构建 =================

st.set_page_config(page_title="出海立项 AI 助手", layout="wide", page_icon="🎮")

st.title("🎮 出海游戏立项 AI 助手")
st.markdown("输入基础定位与竞品链接，自动提取痛点并生成多版本 ASO 文案及主视图买量提示词。")
st.divider()

col1, col2 = st.columns([1, 2.5])

with col1:
    st.subheader("1. 基础定位设定")
    
    market_options = [
        "欧美 T1 泛用户市场", 
        "日韩高净值市场", 
        "拉美/东南亚下沉市场",
        "全球多语言发行"
    ]
    selected_market = st.selectbox("🎯 目标市场", market_options)
    
    gameplay_options = [
        "混合变现 Roguelike 割草 (双层结构：外围养成+局内战斗)", 
        "三消 + X (剧情/建造)", 
        "放置 RPG", 
        "SLG (4X 策略)",
        "超休闲解谜"
    ]
    selected_gameplay = st.selectbox("⚔️ 玩法类型", gameplay_options)
    
    art_options = [
        "8-bit 像素赛博朋克风", 
        "Q版日系二次元", 
        "低像素马赛克风格",
        "美式卡通 (欧美休闲)", 
        "高品质写实 3D"
    ]
    selected_art = st.selectbox("🎨 美术风格", art_options)
    
    st.subheader("2. 对标竞品数据")
    competitor_url = st.text_input("🔗 核心竞品 Google Play 链接", placeholder="https://play.google.com/store/apps/details?id=...")
    
    col_lang, col_country = st.columns(2)
    with col_lang:
        scrape_lang = st.text_input("语言 (例: en)", value="en")
    with col_country:
        scrape_country = st.text_input("地区 (例: us)", value="us")

    generate_btn = st.button("🚀 生成完整立项方案", type="primary", use_container_width=True)

with col2:
    st.subheader("3. 生成结果看板")
    
    if generate_btn:
        if not competitor_url:
            st.warning("请先输入竞品的 Google Play 链接！")
        else:
            with st.spinner("正在抓取竞品商店数据与近期高赞评论..."):
                scraped_data = scrape_play_store(competitor_url, lang=scrape_lang, country=scrape_country)
            
            if scraped_data:
                with st.expander("🔍 查看抓取到的竞品原始数据", expanded=False):
                    st.json(scraped_data)
                
                with st.spinner("正在调用大模型进行数据拆解与文案/图像提示词生成..."):
                    try:
                        result = generate_pitch(scraped_data, selected_market, selected_gameplay, selected_art)
                        st.success("🎉 立项方案生成完毕！")
                        
                        # --- 游戏名称 ---
                        st.markdown("### 💡 建议游戏名称")
                        for name_item in result.get("suggested_names", []):
                            st.markdown(f"- **{name_item['name']}** \n  *{name_item['reason']}*")
                        
                        st.divider()
                        
                        # --- ASO 文案与买量图 ---
                        st.markdown("### 📝 ASO 商店文案 & 🎨 主视图买量图 (A/B Test)")
                        aso_versions = result.get("aso_versions", {})
                        art_prompts = result.get("key_art_prompts", {})
                        
                        tab1, tab2, tab3 = st.tabs(["⚔️ 玩法驱动型 (版本A)", "🌍 世界观驱动型 (版本B)", "📈 买量转化型 (版本C)"])
                        
                        with tab1:
                            st.info("侧重留存：强调核心机制与数值成长。适合硬核/核心圈层玩家。")
                            st.write(aso_versions.get("Version_A_Gameplay", ""))
                            st.caption("配套 Midjourney 绘画提示词 (点击右上角复制):")
                            st.code(art_prompts.get("Version_A_Gameplay", ""), language="text")
                            
                        with tab2:
                            st.info("侧重沉浸：强调背景设定、角色氛围。适合泛用户破圈。")
                            st.write(aso_versions.get("Version_B_Worldview", ""))
                            st.caption("配套 Midjourney 绘画提示词 (点击右上角复制):")
                            st.code(art_prompts.get("Version_B_Worldview", ""), language="text")
                            
                        with tab3:
                            st.info("侧重吸量：强调爽点、矛盾点与极具点击欲的话术。降低 CPI 利器。")
                            st.write(aso_versions.get("Version_C_UA_Acquisition", ""))
                            st.caption("配套 Midjourney 绘画提示词 (点击右上角复制):")
                            st.code(art_prompts.get("Version_C_UA_Acquisition", ""), language="text")
                            
                    except Exception as e:
                        st.error(f"生成过程中出错: {e}")
