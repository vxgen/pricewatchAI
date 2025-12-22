import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import sys
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. GLOBAL SESSION INITIALIZATION (CRITICAL FIX) ---
# This must run before any other logic to prevent AttributeErrors
if "items" not in st.session_state or st.session_state.items is None:
    st.session_state["items"] = []

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

# --- 2. CLOUD INSTALLER ---
def install_playwright_browsers():
    if not st.session_state["browser_installed"]:
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception as e:
            st.error(f"Browser installation failed: {e}")

# --- 3. API CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")

client = OpenAI(api_key=OPENAI_KEY)

# --- 4. CORE FUNCTIONS ---

def google_search_api(query):
    """Requirement #3: Fetch links via Google. Returns empty list if fails."""
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    try:
        response = requests.get(url, timeout=10)
        items = response.json().get("items", [])
        return [item['link'] for item in items[:3]]
    except:
        return []

def analyze_with_vision(image_path, product_name):
    """Requirement #5: Use the $5 credit for Vision AI analysis."""
    try:
        with open(image_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Find the price for {product_name}. Return ONLY the number (e.g. 150.00). If not found, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def run_browser_watch(url, product_name):
    """Requirement #5 & #6: Stealth browsing and screenshot."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()
        stealth(page) 
        
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Requirement #6: Internal Search Fallback
            search_box = page.locator('input[type="search"], input[name="q"]').first
            if search_box.is_visible():
                search_box.fill(product_name)
                search_box.press("Enter")
                page.wait_for_timeout(4000)

            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except:
            return "Scan Failed"
        finally:
            browser.close()

# --- 5. UI LAYOUT ---
st.set_page_config(page_title="Price Watcher v2.1", layout="wide")
install_playwright_browsers()

st.title("🛒 AI Price Comparison Tool")

with st.sidebar:
    st.header("Add New Product")
    sku_val = st.text_input("SKU / Keywords")
    url_val = st.text_input("Store URL (Optional)")
    
    if st.button("Add to Watchlist"):
        if sku_val:
            # Re-verify list existence immediately before appending
            if "items" not in st.session_state or st.session_state.items is None:
                st.session_state.items = []
                
            with st.spinner("Fetching links..."):
                found_links = [url_val] if url_val else google_search_api(sku_val)
                if found_links:
                    for link in found_links:
                        st.session_state.items.append({"sku": sku_val, "url": link})
                    st.success(f"Added {sku_val}")
                else:
                    st.error("No links found.")
        else:
            st.warning("Enter a SKU.")

    if st.button("🗑️ Clear List"):
        st.session_state.items = []
        st.rerun()

# --- 6. DISPLAY & ANALYSIS ---
if st.session_state.items:
    st.subheader("Your Watchlist")
    
    if st.button("🚀 Run Price Comparison Analysis"):
        results = []
        progress = st.progress(0)
        
        for i, item in enumerate(st.session_state.items):
            with st.status(f"Scanning {item['sku']}...") as status:
                price = run_browser_watch(item['url'], item['sku'])
                results.append({
                    "Product": item['sku'],
                    "Price": price,
                    "Source": item['url']
                })
                progress.progress((i + 1) / len(st.session_state.items))
                status.update(label="Complete!", state="complete")
        
        st.divider()
        st.subheader("Results Table")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
    else:
        st.table(pd.DataFrame(st.session_state.items))
else:
    st.info("Sidebar: Add a product to begin.")
