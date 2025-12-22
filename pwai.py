import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import time
from datetime import datetime
from PIL import Image
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. SESSION & BROWSER ---
def get_watchlist():
    if "items" not in st.session_state:
        st.session_state["items"] = []
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception as e:
            st.error(f"Browser installation failed: {e}")

# --- 2. API CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")
client = OpenAI(api_key=OPENAI_KEY)

# --- 3. SMART VISION (REDUCED TOKEN USAGE) ---
def analyze_with_vision(image_path, product_name):
    try:
        # COMPRESSION STEP: Resize and lower quality to save tokens
        with Image.open(image_path) as img:
            # Resize to a reasonable width while maintaining aspect ratio
            img.thumbnail((800, 800)) 
            compressed_path = "small_" + image_path
            img.save(compressed_path, "JPEG", quality=60) # JPEG is much smaller than PNG
        
        with open(compressed_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Find the price for {product_name}. Return ONLY the number. Use 'N/A' if not found."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        
        # Cleanup
        if os.path.exists(compressed_path): os.remove(compressed_path)
        return response.choices[0].message.content.strip()
    except Exception as e:
        if "429" in str(e): return "Rate Limited (Wait 60s)"
        return f"AI Error"

def run_browser_watch(url, product_name):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        try:
            stealth(page)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2) # Let dynamic prices load
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except:
            return "Scan Timeout"
        finally:
            browser.close()

# --- 4. UI ---
st.set_page_config(page_title="Price Watch AI", layout="wide")
if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 AI Price Watcher (Safe Mode)")

# Sidebar & Table Logic (same as before)
# ... [Keeping sidebar and google_search_deep logic from previous version] ...

watchlist = get_watchlist()
if watchlist:
    df = pd.DataFrame(watchlist)
    st.dataframe(df[["sku", "price", "last_updated", "url"]], use_container_width=True)
    
    if st.button("🚀 Start Scanning Prices"):
        status_box = st.empty()
        bar = st.progress(0)
        
        for i, item in enumerate(watchlist):
            status_box.info(f"Scanning {i+1}/{len(watchlist)}: {item['sku']}...")
            
            # RUN SCAN
            found_price = run_browser_watch(item['url'], item['sku'])
            
            # Update state
            st.session_state["items"][i]["price"] = found_price
            st.session_state["items"][i]["last_updated"] = datetime.now().strftime("%H:%M")
            bar.progress((i + 1) / len(watchlist))
            
            # THE "SHIELD" DELAY: Pause for 8 seconds to prevent 429 errors
            if i < len(watchlist) - 1:
                status_box.warning(f"Waiting 8s for API cooldown... (Next: Store {i+2})")
                time.sleep(8)
        
        status_box.success("✅ Deep Scan Complete!")
        st.rerun()
