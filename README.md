# storescraper

一个轻量级的新游选题工作台：

- 左侧抓取 App Store / Google Play 候选游戏
- 中间以卡片流展示 Icon、AI 提炼玩法、商店评分
- 右侧为选中的游戏生成微信公众号 Markdown 稿件

## 安装

```powershell
pip install -r requirements.txt
```

## 启动

```powershell
streamlit run streamlit_app.py
```

## 可选的大模型配置

如果你希望“AI 提炼玩法”和“生成推文”调用真实大模型，请设置：

```powershell
$env:OPENAI_API_KEY="你的 Key"
$env:OPENAI_MODEL="gpt-4o-mini"
```

如果未设置，系统会使用本地回退摘要与模板稿件，界面仍可完整使用。
