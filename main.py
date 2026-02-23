import feedparser
import requests
import os
import json
import hashlib
import re
from datetime import datetime

# 从 GitHub Secrets 中获取 Webhook 地址
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK")
AI_API_KEY = os.environ.get("AI_API_KEY")

# Feishu Bitable 配置
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.environ.get("BITABLE_APP_TOKEN")
BITABLE_TABLE_ID = os.environ.get("BITABLE_TABLE_ID")

# 订阅列表 (根据 Gist 提取的部分优质源)
RSS_FEEDS = [
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/"},
    {"name": "Jeff Geerling", "url": "https://www.jeffgeerling.com/blog.xml"},
    {"name": "Daring Fireball", "url": "https://daringfireball.net/feeds/main"},
    {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/"},
    {"name": "Sean Goedecke", "url": "https://seangoedecke.com/rss.xml"}
]

DATA_FILE = "sent_articles.json"

def load_sent_articles():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return []

def save_sent_articles(sent_list):
    # 只保留最近 100 条防止文件过大
    with open(DATA_FILE, 'w') as f:
        json.dump(sent_list[-100:], f)

def get_article_id(entry):
    # 生成唯一标识符：优先用 id，没有就用 link
    content = entry.get('id', entry.get('link', ''))
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def clean_html(raw_html):
    # 简单的清理 HTML 标签
    cleaner = re.compile('<.*?>')
    return re.sub(cleaner, '', raw_html).strip()

def get_summary(text):
    text = clean_html(text)
    if not text:
        return "无摘要内容"
        
    if not AI_API_KEY:
        # 如果没有配置 AI API Key，则仅仅截取前 200 个字符作为摘要
        return text[:200] + "..." if len(text) > 200 else text

    # 使用 AI 进行内容总结 (使用官方 DeepSeek API)
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的文章总结助手。请用一段自然流畅的中文总结以下文章的核心内容，不需要额外的客套话，字数控制在150字左右。"},
            {"role": "user", "content": text[:4000]} # 截取前 4000 字发给 AI 以节省 Token 和加快速度
        ],
        "temperature": 0.3
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        data = resp.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"AI 总结出错: {e}")
        return text[:200] + "..."

def send_to_feishu(title, link, site_name, summary):
    print(f"推送文章: {title}")
    content = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"🆕 {site_name} 更新啦！",
                    "content": [
                        [
                            {"tag": "text", "text": f"📍 标题：{title}\n\n"}
                        ],
                        [
                            {"tag": "text", "text": f"💡 总结：{summary}\n\n"}
                        ],
                        [
                            {"tag": "a", "text": "👉 点击这里阅读全文", "href": link}
                        ]
                    ]
                }
            }
        }
    }
    resp = requests.post(FEISHU_WEBHOOK_URL, json=content)
    if resp.status_code != 200:
        print(f"推送失败: {resp.text}")

def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    try:
        resp = requests.post(url, json=payload)
        return resp.json().get("tenant_access_token")
    except Exception as e:
        print(f"获取 Feishu Token 失败: {e}")
        return None

def send_to_bitable(title, link, site_name, summary):
    if not (FEISHU_APP_ID and FEISHU_APP_SECRET and BITABLE_APP_TOKEN and BITABLE_TABLE_ID):
        print("未配置 Bitable 相关环境变量，跳过同步")
        return

    token = get_tenant_access_token()
    if not token:
        return

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 字段名称需要根据你的多维表格实际情况修改
    fields = {
        "标题": title,
        "链接": {
            "link": link,
            "text": "查看全文"
        },
        "来源": site_name,
        "摘要总结": summary,
        "发布时间": int(datetime.now().timestamp() * 1000)
    }
    
    payload = {"fields": fields}
    
    try:
        resp = requests.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            print(f"同步到 Bitable 成功: {title}")
        else:
            print(f"同步到 Bitable 失败: {resp.text}")
    except Exception as e:
        print(f"同步到 Bitable 出错: {e}")

def main():
    if not FEISHU_WEBHOOK_URL:
        print("错误: 未设置 FEISHU_WEBHOOK 环境变量")
        return

    sent_articles = load_sent_articles()
    new_sent_list = list(sent_articles)
    
    for feed_info in RSS_FEEDS:
        print(f"正在检查: {feed_info['name']}...")
        try:
            feed = feedparser.parse(feed_info['url'])
            # 检查最新的 3 条
            for entry in feed.entries[:3]:
                article_id = get_article_id(entry)
                if article_id not in sent_articles:
                    # 获取 RSS 中包含的文章内容，优先获取 content，其次 summary
                    raw_content = ""
                    if 'content' in entry:
                        raw_content = entry.content[0].value
                    elif 'summary' in entry:
                        raw_content = entry.summary
                    elif 'description' in entry:
                        raw_content = entry.description
                        
                    summary = get_summary(raw_content)
                    
                    # 1. 发送到飞书群
                    send_to_feishu(entry.title, entry.link, feed_info['name'], summary)
                    
                    # 2. 同步到飞书多维表格
                    send_to_bitable(entry.title, entry.link, feed_info['name'], summary)
                    
                    new_sent_list.append(article_id)
        except Exception as e:
            print(f"抓取 {feed_info['name']} 出错: {e}")

    save_sent_articles(new_sent_list)

if __name__ == "__main__":
    main()
