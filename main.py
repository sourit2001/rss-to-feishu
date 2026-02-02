import feedparser
import requests
import os
import json
import hashlib
from datetime import datetime

# 从 GitHub Secrets 中获取 Webhook 地址
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK")

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

def send_to_feishu(title, link, site_name):
    print(f"推送文章: {title}")
    content = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"🆕 {site_name} 更新啦！",
                    "content": [
                        [
                            {"tag": "text", "text": f"标题：{title}\n\n"},
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
                    send_to_feishu(entry.title, entry.link, feed_info['name'])
                    new_sent_list.append(article_id)
        except Exception as e:
            print(f"抓取 {feed_info['name']} 出错: {e}")

    save_sent_articles(new_sent_list)

if __name__ == "__main__":
    main()
