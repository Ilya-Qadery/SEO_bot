import os
import time
import json
import requests
import pandas as pd
import threading
from flask import Flask, render_template, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def run_seo_bot(file_path):
    print("\n" + "=" * 40)
    print("🚀 SEO BOT: STARTING WORKER THREAD")
    print("=" * 40)

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ARTICLES_DIR = os.path.join(BASE_DIR, "articles")
    CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
    LOGIN_FILE = os.path.join(BASE_DIR, "wp_login.txt")
    os.makedirs(ARTICLES_DIR, exist_ok=True)

    # 1. Load Keys
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        api_key = config.get("OPENAI_API_KEY")
        if not api_key: raise ValueError("API Key missing in config.json")
    except Exception as e:
        print(f"❌ CONFIG ERROR: {e}")
        return

    # 2. Load WP Login & Resolve URLs
    try:
        with open(LOGIN_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            # Handling your specific file format: amir, amir1, url
            wp_user, wp_pass, wp_url = lines[0], lines[1], lines[2]

        # Clean URL to get the base domain
        base_url = wp_url.lower().replace('wp-login.php', '').replace('wp-admin', '').rstrip('/')
        login_url = f"{base_url}/wp-login.php"
        new_post_url = f"{base_url}/wp-admin/post-new.php"
        print(f"🔗 Target Domain: {base_url}")
    except Exception as e:
        print(f"❌ LOGIN FILE ERROR: {e}")
        return

    # 3. Read Excel/CSV
    print(f"📊 Loading titles from: {file_path}")
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        # Grab first column regardless of header name
        titles = df.iloc[:, 0].dropna().tolist()
        print(f"✅ Loaded {len(titles)} titles.")
    except Exception as e:
        print(f"❌ FILE READ ERROR: {e}")
        return

    def generate_article(title):
        print(f"🤖 OpenAI: Generating article for '{title}'...")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system",
                 "content": "You are a professional SEO writer. Write a 1500-word article in Persian (Farsi) using HTML tags (h2, h3). Return ONLY the article content."},
                {"role": "user", "content": f"Title: {title}"}
            ]
        }
        try:
            r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=180)
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"❌ OpenAI API Error: {e}")
            return None

    # 4. Selenium Automation (Docker/Headless Optimized)
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # Add User-Agent to avoid bot detection in headless mode
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)

    try:
        print("🌐 Opening Browser (Headless)...")
        driver.get(login_url)

        # Login
        wait.until(EC.presence_of_element_located((By.ID, "user_login"))).send_keys(wp_user)
        driver.find_element(By.ID, "user_pass").send_keys(wp_pass)
        driver.find_element(By.ID, "wp-submit").click()

        # Verify Login by waiting for admin bar
        wait.until(EC.presence_of_element_located((By.ID, "wpadminbar")))
        print("✅ Login Successful.")

        for idx, title in enumerate(titles, start=1):
            print(f"\n📝 [{idx}/{len(titles)}] Current Title: {title}")

            txt_path = os.path.join(ARTICLES_DIR, f"article_{idx}.txt")

            # Step A: Get Content (Cache or AI)
            if not os.path.exists(txt_path):
                content = generate_article(title)
                if content:
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(content)
                else:
                    print(f"⏭️ Skipping '{title}' due to AI error.")
                    continue

            with open(txt_path, "r", encoding="utf-8") as f:
                post_body = f.read()

            # Step B: WordPress Posting
            print(f"📤 Navigating to New Post...")
            driver.get(new_post_url)

            # Enter Title
            wait.until(EC.presence_of_element_located((By.ID, "title"))).send_keys(title)

            # Switch to Text (HTML) Tab - Crucial for preservation of tags
            wait.until(EC.element_to_be_clickable((By.ID, "content-html"))).click()
            time.sleep(1)  # Small delay for UI

            # Enter Body
            driver.find_element(By.ID, "content").send_keys(post_body)

            # Save Draft
            save_btn = wait.until(EC.element_to_be_clickable((By.ID, "save-post")))
            save_btn.click()

            print(f"✅ Draft '{title}' saved successfully.")
            time.sleep(2)

    except Exception as e:
        print(f"❌ BOT ERROR: {e}")
        # In headless mode, screenshots help debug if it fails
        driver.save_screenshot("last_error.png")
        print("📸 Screenshot saved as 'last_error.png'")
    finally:
        print("\n🏁 Process Finished. Closing worker.")
        driver.quit()


# ================= FLASK UI ROUTES =================

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/start-bot', methods=['POST'])
def start():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    # Run automation in a background thread
    threading.Thread(target=run_seo_bot, args=(file_path,)).start()

    return jsonify({"status": "success", "message": "Bot triggered successfully!"})


if __name__ == '__main__':
    # host='0.0.0.0' is required for Docker access
    app.run(host='0.0.0.0', port=8000, debug=True)