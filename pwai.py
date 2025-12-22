import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import sys
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth  # Note: 2025 update, use 'stealth' not 'stealth_sync'
from openai import OpenAI

# --- 1. CLOUD INSTALLER BLOCK ---
# This ensures Chromium is installed automatically on the Streamlit server
def install_playwright_browsers():
    try:
        # Check if browser is already there to avoid redundant installs
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Failed to install browser: {e}")

if "browser_installed" not in st.session_state:
    with st.spinner("Initializing browser environment..."):
        install_playwright_browsers()
        st.session_state.browser_installed = True

# --- 2. INITIALIZE CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")

client = OpenAI(api_key=OPENAI_KEY)

# --- 3. CORE LOGIC ---

def google_search_api(query):
    """Requirement #3: Fetch retail links via Google API."""
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    try:
        response = requests.get(url).json()
        items = response.get("items", [])
        return [item['link'] for item in items[:3]]
    except:
        return []

def analyze_with_vision(image_path, product_name):
    """Requirement #5: Vision AI for price extraction."""
    with open(image_path, "rb") as f:
        base64_img = base64.b64encode(f.read()).decode('utf-8')
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"Extract the price for {product_name}. Return ONLY the number (e.g. 49.99)."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
            ]
        }]
    )
    return response.choices[0].message.content

def run_browser_watch(url, product_name, search_mode=False):
    """Requirement #5 & #6: Browser automation."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()
        stealth(page) # Updated stealth call
        
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
            
            # Requirement #6: Internal Search Fallback
            if search_mode:
                search_selectors = ['input[type="search"]', 'input[name="q"]', 'input[placeholder*="Search"]']
                for selector in search_selectors:
                    if page.locator(selector).is_visible():
                        page.fill(selector, product_name)
                        page.press(selector, "Enter")
                        page.wait_for_load_state("networkidle")
                        break

            path = f"snap_{os.getpid()}.png"
            page.screenshot(path=path)
            price = analyze_with_vision(path, product_name)
            os.remove(path)
            return price
        except Exception as e:
            return f"Error: {str(e)}"
        finally:
            browser.close()

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="Pro Price Watcher", layout="wide")

# INITIALIZE WATCHLIST AT THE VERY START OF THE UI SECTION
if "items" not in st.session_state:
    st.session_state.items = []

st.title("🛒 AI-Powered Price Watcher v2.0")

with st.sidebar:
    st.header("Add Product")
    sku_input = st.text_input("Product Name / SKU", key="sku_input") # Added unique key
    manual_url = st.text_input("Target URL (Optional)", key="url_input")
    
    if st.button("Add to Watchlist"):
        if sku_input:
            with st.spinner("Searching for links..."):
                links = [manual_url] if manual_url else google_search_api(sku_input)
                
                if links:
                    for link in links:
                        # Double-check initialization right before appending
                        st.session_state.items.append({"sku": sku_input, "url": link})
                    st.success(f"Added {sku_input} to watchlist!")
                else:
                    st.warning("No links found. Please provide a manual URL.")
        else:
            st.error("Please enter a SKU or Product Name.")

# Requirement #4: Table
if "items" in st.session_state:
    if st.button("🚀 Run Analysis"):
        results = []
        for entry in st.session_state.items:
            with st.status(f"Scanning {entry['sku']}..."):
                price = run_browser_watch(entry['url'], entry['sku'], search_mode=True)
                results.append({"SKU": entry['sku'], "Price": price, "Source": entry['url']})
        st.table(pd.DataFrame(results))

