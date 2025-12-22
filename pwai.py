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

# --- 1. CLOUD INSTALLER BLOCK ---
# Essential for Requirement #5: Ensures the browser "eyes" exist on the server
def install_playwright_browsers():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Browser installation failed: {e}")

# Initialize session state variables early
if "browser_installed" not in st.session_state:
    with st.spinner("Setting up browser environment..."):
        install_playwright_browsers()
        st.session_state.browser_installed = True

if "items" not in st.session_state or st.session_state.items is None:
    st.session_state.items = []

# --- 2. API CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")

client = OpenAI(api_key=OPENAI_KEY)

# --- 3. CORE LOGIC ---

def google_search_api(query):
    """Requirement #3: Fetch links using Google API. Returns empty list on failure."""
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        st.error("Google API keys missing in secrets!")
        return []
    
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        items = data.get("items", [])
        return [item['link'] for item in items[:3]]
    except Exception as e:
        st.sidebar.error(f"Search failed: {e}")
        return []

def analyze_with_vision(image_path, product_name):
    """Requirement #5: GPT-4o Vision analysis of the screenshot."""
    try:
        with open(image_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Identify the price for {product_name}. Return ONLY the number (e.g., 129.00). If not found, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
                ]
            }]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Vision Error: {str(e)}"

def run_browser_watch(url, product_name):
    """Requirement #5 & #6: Navigate, bypass anti-crawler, and screenshot."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a real browser fingerprint to avoid detection
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()
        stealth(page) 
        
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            
            # Requirement #6: Fallback - try internal search if the page is blocked or generic
            search_input = page.locator('input[type="search"], input[name="q"], input[placeholder*="Search"]').first
            if search_input.is_visible():
                search_input.fill(product_name)
                search_input.press("Enter")
                page.wait_for_timeout(3000) # Wait for results

            # Requirement #5: Visual capture for analysis
            img_path = f"temp_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price_result = analyze_with_vision(img_path, product_name)
            
            if os.path.exists(img_path):
                os.remove(img_path)
            return price_result
        except Exception as e:
            return "Connection Timed Out"
        finally:
            browser.close()

# --- 4. USER INTERFACE ---
st.set_page_config(page_title="AI Price Watcher", layout="wide", page_icon="🛒")
st.title("🛒 AI-Powered Price Watcher v2.0")



with st.sidebar:
    st.header("Product Tracking")
    sku_val = st.text_input("SKU or Product Keywords", placeholder="e.g. AM272P")
    url_val = st.text_input("Manual Store Link (Optional)")
    
    if st.button("Add to Watchlist"):
        if sku_val:
            with st.spinner("Finding best links..."):
                found_links = [url_val] if url_val else google_search_api(sku_val)
                
                if found_links:
                    for link in found_links:
                        st.session_state.items.append({"sku": sku_val, "url": link})
                    st.success(f"Added {len(found_links)} items!")
                else:
                    st.error("No links found. Please try a manual URL.")
        else:
            st.warning("Please enter a SKU.")

    if st.button("🗑️ Clear All"):
        st.session_state.items = []
        st.rerun()

# --- 5. COMPARISON TABLE ---
if isinstance(st.session_state.items, list) and len(st.session_state.items) > 0:
    st.subheader("Current Watchlist")
    
    # Requirement #4: Display comparison table
    if st.button("🚀 Start Price Analysis"):
        all_data = []
        progress = st.progress(0)
        
        for idx, item in enumerate(st.session_state.items):
            with st.status(f"Analyzing {item['sku']} at {item['url']}...") as status:
                price = run_browser_watch(item['url'], item['sku'])
                all_data.append({
                    "Product/SKU": item['sku'],
                    "Current Price": price,
                    "Link": item['url']
                })
                progress.progress((idx + 1) / len(st.session_state.items))
                status.update(label=f"Done: {item['sku']}", state="complete")
        
        st.subheader("Price Comparison Table")
        st.dataframe(pd.DataFrame(all_data), use_container_width=True)
    else:
        # Show what is currently in the list before running analysis
        st.table(pd.DataFrame(st.session_state.items))
else:
    st.info("Your watchlist is currently empty. Use the sidebar to add products.")
