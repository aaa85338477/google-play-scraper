import streamlit as st
import json
import urllib.parse
import requests
from urllib.parse import urlparse, parse_qs
from google_play_scraper import app as play_app, reviews, Sort
from google import genai
from google.genai import types
from PIL import Image
import io

# ================= 1. 核心功能函数 =================

def extract_package_name(url):
    """提取 Google Play 链接中的包名"""
    parsed_url = urlparse(url)
    params = parse_qs(parsed_url.query)
    if 'id' in params:
        return params['id'][0]
    return None

def scrape_play_store(url, lang='en', country='us'):
    """抓取 Google Play 商店基础数据与高赞评论"""
    package_name = extract_package_name(url)
    if not package_name:
        return None
    try:
        app_info = play_app(package_name, lang=lang, country=country)
        # 已修复：使用 Sort.MOST_RELEVANT 替代废弃的 HELPFULNESS
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
    """调用 Gemini 2.5 Flash-lite 生成完整的长篇立项文案与提示词"""
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)

    prompt = f"""
    你现在是一位资深的海外移动游戏发行与 UA (用户获取) 专家。
    请根据以下信息，为新游戏立项生成高质量的商店测试素材。

    【项目基本设定】
    - 目标市场: {market}
    - 核心玩法: {gameplay}
    - 美术方向: {art}

    【对标竞品情报 (来自 Google Play)】
    {json.dumps(scraped_data, ensure_ascii=False, indent=2)}

    【任务要求】
    请严格按照以下 JSON 格式输出结果：
    {{
      "suggested_names": [
        {{"name": "英文游戏名1", "reason": "为什么适合该市场"}}
      ],
      "aso_versions": {{
        "Version_A_Gameplay": "请在这里写出一篇完整的、可直接复制到 Google Play 的长文案（不少于300字）。包含吸睛的开头、3-4个核心玩法的 Bullet points 介绍、以及引导下载的结尾。侧重留存，强调核心机制与数值成长。",
        "Version_B_Worldview": "请在这里写出一篇完整的长文案（不少于300字）。包含史诗感的开头、剧情设定的 Bullet points、结尾。侧重沉浸，强调背景设定、角色塑造和美术氛围。",
        "Version_C_UA_Acquisition": "请在这里写出一篇完整的长文案（不少于300字）。风格要夸张、极具煽动性。包含灵魂发问、爽点痛点的 Bullet points 介绍、以及倒计时般的紧迫感结尾。侧重买量转化。"
      }},
      "key_art_prompts": {{
        "Version_A_Gameplay": "输出一段用于 AI 绘画的纯英文提示词，画面需展现游戏实际的战斗或核心操作感。不要包含任何 Markdown 标记或多余解释。",
        "Version_B_Worldview": "输出一段用于 AI 绘画的纯英文提示词，画面需展现宏大的背景设定或角色特写。不要包含任何 Markdown 标记或多余解释。",
        "Version_C_UA_Acquisition": "输出一段用于 AI 绘画的纯英文提示词，画面需具备极强的买量吸睛要素（如强烈色彩对比、密集怪物群等）。不要包含任何 Markdown 标记或多余解释。"
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

def generate_concept_image(prompt_text):
    """使用 Hugging Face 最新的 Router API 生成高质量图像"""
    hf_token = st.secrets.get("HF_API_TOKEN")
    if not hf_token:
        return "⚠️ 请先在 Streamlit Secrets 中配置 HF_API_TOKEN"

    # 已更新为 Hugging Face 最新的 Inference Router URL
    API_URL = "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {"Authorization": f"Bearer {hf_token}"}

    try:
        payload = {
            "inputs": prompt_text,
            "parameters": {
                # 过滤掉买量图中不需要的瑕疵元素
                "negative_prompt": "text, watermark, ugly, blurry, low resolution, deformed"
            }
        }
        
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
        elif response.status_code == 503:
            return "模型正在加载中，请等待约 30 秒后再次点击生成按钮。"
        else:
            return f"出图失败，状态码: {response.status_code}, 信息: {response.text}"
            
    except Exception as e:
        return f"网络请求失败: {str(e)}"

# ================= 2. Streamlit UI 构建 =================

st.set_page_config(page_title="出海立项 AI 助手", layout="wide", page_icon="🎮")

st.title("🎮 出海游戏立项 AI 助手")
st.markdown("输入基础定位与竞品链接，自动提取痛点，并**直接生成完整长文案与 16:9 概念主视图**。")
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

    generate_btn = st.button("🚀 生成完整立项方案 (含出图)", type="primary", use_container_width=True)

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
                    
                with st.spinner("🧠 正在编写长篇 ASO 商店文案..."):
                    try:
                        result = generate_pitch(scraped_data, selected_market, selected_gameplay, selected_art)
                        st.success("🎉 文案生成完毕！正在为您实时绘制游戏主视图，请稍候...")
                        
                        st.markdown("### 💡 建议游戏名称")
                        for name_item in result.get("suggested_names", []):
                            st.markdown(f"- **{name_item['name']}** \n  *{name_item['reason']}*")
                        
                        st.divider()
                        
                        st.markdown("### 📝 ASO 商店文案 & 🎨 主视图买量图")
                        aso_versions = result.get("aso_versions", {})
                        art_prompts = result.get("key_art_prompts", {})
                        
                        tab1, tab2, tab3 = st.tabs(["⚔️ 玩法驱动型 (版本A)", "🌍 世界观驱动型 (版本B)", "📈 买量转化型 (版本C)"])
                        
                        # ----- 版本 A -----
                        with tab1:
                            st.info("侧重留存：强调核心机制与数值成长。适合硬核/核心圈层玩家。")
                            col_text_a, col_img_a = st.columns([1, 1])
                            with col_text_a:
                                st.write(aso_versions.get("Version_A_Gameplay", ""))
                                st.caption("🖼️ 后台使用的绘图提示词:")
                                st.code(art_prompts.get("Version_A_Gameplay", ""), language="text")
                            with col_img_a:
                                with st.spinner("正在绘制 版本A 主视图..."):
                                    img_a = generate_concept_image(art_prompts.get("Version_A_Gameplay", ""))
                                    if isinstance(img_a, Image.Image):
                                        st.image(img_a, caption="AI 实时生成：玩法概念图", use_container_width=True)
                                    else:
                                        st.error(f"出图失败: {img_a}")
                            
                        # ----- 版本 B -----
                        with tab2:
                            st.info("侧重沉浸：强调背景设定、角色氛围。适合泛用户破圈。")
                            col_text_b, col_img_b = st.columns([1, 1])
                            with col_text_b:
                                st.write(aso_versions.get("Version_B_Worldview", ""))
                                st.caption("🖼️ 后台使用的绘图提示词:")
                                st.code(art_prompts.get("Version_B_Worldview", ""), language="text")
                            with col_img_b:
                                with st.spinner("正在绘制 版本B 主视图..."):
                                    img_b = generate_concept_image(art_prompts.get("Version_B_Worldview", ""))
                                    if isinstance(img_b, Image.Image):
                                        st.image(img_b, caption="AI 实时生成：世界观概念图", use_container_width=True)
                                    else:
                                        st.error(f"出图失败: {img_b}")

                        # ----- 版本 C -----
                        with tab3:
                            st.info("侧重吸量：强调爽点、矛盾点与极具点击欲的话术。降低 CPI 利器。")
                            col_text_c, col_img_c = st.columns([1, 1])
                            with col_text_c:
                                st.write(aso_versions.get("Version_C_UA_Acquisition", ""))
                                st.caption("🖼️ 后台使用的绘图提示词:")
                                st.code(art_prompts.get("Version_C_UA_Acquisition", ""), language="text")
                            with col_img_c:
                                with st.spinner("正在绘制 版本C 主视图..."):
                                    img_c = generate_concept_image(art_prompts.get("Version_C_UA_Acquisition", ""))
                                    if isinstance(img_c, Image.Image):
                                        st.image(img_c, caption="AI 实时生成：买量吸睛图", use_container_width=True)
                                    else:
                                        st.error(f"出图失败: {img_c}")
                            
                    except Exception as e:
                        st.error(f"生成过程中出错: {e}")
