# storescraper

一个轻量级的新游选题与厂商监控工作台。

当前支持：
- 抓取 App Store / Google Play 候选游戏
- 在 Streamlit 中展示卡片流、评分、截图和摘要
- 生成微信公众号 Markdown 稿件
- 将历史 App_ID 同步到飞书多维表格
- 通过 `target_publishers.json` 维护原始厂商资产库
- 通过 `build_core_developers.py` 自动生成监控用的 `core_developers.json`

## 安装

```powershell
pip install -r requirements.txt
```

## 启动

```powershell
streamlit run streamlit_app.py
```

## 厂商名单工作流

1. 先用 `clean_target_publishers.py` 把 AppMagic 导出文件清洗成 `target_publishers.json`
2. 再用 `build_core_developers.py` 把它转换成监控配置 `core_developers.json`
3. Streamlit 页面和监控脚本会直接读取 `core_developers.json`

```powershell
python clean_target_publishers.py "C:\Users\aaa85\Desktop\畅销榜100.xlsx" "target_publishers.json"
python build_core_developers.py "target_publishers.json" "core_developers.json"
```

## 可选的大模型配置

如果你希望“AI 提炼玩法”和“生成推文”调用真实大模型，请设置：

```powershell
$env:OPENAI_API_KEY="你的 Key"
$env:OPENAI_MODEL="gpt-4o-mini"
```

如果未设置，系统会自动使用本地回退摘要与模板稿件，界面仍可完整使用。
