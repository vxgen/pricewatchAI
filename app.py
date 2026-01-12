import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import json
from datetime import date
from fpdf import FPDF
import time

st.set_page_config(page_title="Product Check App", layout="wide")

# --- 1. SHARED HELPERS ---

def safe_float(val):
    """Safely converts string to float, handling symbols and empty values."""
    try:
        clean = str(val).replace('$', '').replace(',', '').strip()
        if not clean or clean.lower() in ['none', 'nan']: return 0.0
        return float(clean)
    except:
        return 0.0

def sanitize_text(text):
    """Removes special characters that crash FPDF (e.g. emojis)."""
    if not isinstance(text, str): return str(text)
    text = text.replace('\u2013', '-').replace('\u2019', "'")
    return text.encode('latin-1', 'replace').decode('latin-1')

def normalize_items(items):
    """Ensures all items have valid keys/types."""
    clean = []
    if not isinstance(items, list): return []
    
    for item in items:
        n = item.copy()
        n['qty'] = safe_float(n.get('qty', 1))
        if n['qty'] == 0: n['qty'] = 1.0
        
        n['price'] = safe_float(n.get('price', 0))
        n['discount_val'] = safe_float(n.get('discount_val', 0))
        
        if 'discount_type' not in n: n['discount_type'] = '%'
        if 'desc' not in n: n['desc'] = ""
        if 'name' not in n or pd.isna(n['name']): n['name'] = "Item"
        
        # Calc Total
        g = n['qty'] * n['price']
        d = g * (n['discount_val']/100) if n['discount_type'] == '%' else n['discount_val']
        n['total'] = g - d
        clean.append(n)
    return clean

# --- SEARCH LOGIC (RESTORED) ---
def generate_search_labels(df):
    if df.empty: return df, None
    def col_ok(d, c): return not d[c].astype(str).str.strip().eq('').all()
    valid_cols = [c for c in df.columns if col_ok(df, c)]
    if not valid_cols: return df, None
    name_col = valid_cols[0]
    for c in valid_cols:
        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
    forbidden = ['price', 'cost', 'date', 'category', 'srp', 'msrp', 'margin']
    def mk_lbl(row):
        m = str(row[name_col]) if pd.notnull(row[name_col]) else ""
        if m.lower() in ['nan','', 'none']: return None
        parts = [m.strip()]
        for c in valid_cols:
            if c != name_col and not any(k in c.lower() for k in forbidden):
                v = str(row[c]).strip()
                if v and v.lower() not in ['nan', 'none', '']: parts.append(v)
        return " | ".join(filter(None, parts))
    df['Search_Label'] = df.apply(mk_lbl, axis=1)
    return df, name_col

def extract_product_data(label, df_with_labels, name_col):
    if not label or df_with_labels.empty: return None
    match = df_with_labels[df_with_labels['Search_Label'] == label]
    if match.empty: return None
    row = match.iloc[0]
    p_name = str(row[name_col])
    p_price = 0.0
    p_cols = [c for c in df_with_labels.columns if any(x in c.lower() for x in ['price', 'msrp', 'srp', 'cost'])]
    for pc in p_cols:
        val = safe_float(row[pc])
        if val > 0: p_price = val; break
    p_desc = ""
    d_cols = [c for c in df_with_labels.columns if any(x in c.lower() for x in ['long description', 'description', 'specs', 'detail'])]
    for dc in d_cols:
        val = str(row[dc])
        if val and val.lower() not in ['nan', 'none', '']: p_desc = val; break
    if not p_desc:
        parts = []
        forbidden = ['price', 'cost', 'date', 'category', 'srp', 'msrp', 'margin', 'search_label']
        for c in df_with_labels.columns:
            if c == name_col or any(k in c.lower() for k in forbidden): continue
            v = str(row[c]).strip()
            if v and v.lower() not in ['nan', 'none', '']: parts.append(f"{c}: {v}")
        p_desc = " | ".join(parts)
    return {"name": p_name, "desc": p_desc, "price": p_price}

# --- CALLBACKS (RESTORED) ---
def on_product_search_change():
    """Section 2 Callback: Auto-fill inputs from DB."""
    lbl = st.session_state.get("q_search_product")
    if lbl:
        try:
            df = dm.get_all_products_df()
            df_lbl, name_col = generate_search_labels(df)
            data = extract_product_data(lbl, df_lbl, name_col)
            if data:
                st.session_state['input_name'] = data['name']
                st.session_state['input_desc'] = data['desc']
                st.session_state['input_price'] = data['price']
                st.session_state['input_qty'] = 1.0
        except: pass

def add_line_item_callback():
    """Section 2 Button Callback: Add to list."""
    name = st.session_state.get('input_name', '')
    if not name:
        st.toast("Name required!", icon="⚠️")
        return

    item = {
        "name": name,
        "desc": st.session_state.get('input_desc', ''),
        "qty": st.session_state.get('input_qty', 1.0),
        "price": st.session_state.get('input_price', 0.0),
        "discount_val": st.session_state.get('input_disc_val', 0.0),
        "discount_type": st.session_state.get('input_disc_type', '%'),
        "total": 0
    }
    
    if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []
    st.session_state['quote_items'].append(item)
    
    # Clear inputs safely
    st.session_state['input_name'] = ""
    st.session_state['input_desc'] = ""
    st.session_state['input_price'] = 0.0
    st.session_state['input_qty'] = 1.0
    st.session_state['q_search_product'] = None
    st.toast("Item Added!")

def save_quote_callback():
    """Save Quote Callback."""
    if not st.session_state.get("q_client_input"):
        st.toast("Client Name Required!", icon="⚠️"); return

    items = st.session_state.get('quote_items', [])
    if not items:
        st.toast("No items to save!", icon="⚠️"); return
        
    items = normalize_items(items)
    sub_ex = sum(i['total'] for i in items)
    grand_total = sub_ex * 1.10
    
    # Ensure Expiration is a String
    exp_val = st.session_state.get("q_expire_input")
    exp_str = str(exp_val) if exp_val else ""

    payload = {
        "client_name": st.session_state.get("q_client_input"),
        "client_email": st.session_state.get("q_email_input"),
        "client_phone": st.session_state.get("q_phone_input"),
        "total_amount": grand_total,
        "expiration_date": exp_str,
        "items": items
    }
    
    dm.save_quote(payload, st.session_state['user'])
    
    st.session_state['quote_items'] = []
    st.session_state['input_name'] = ""
    st.toast("Quote Saved!", icon="✅")

# --- PDF ENGINE (FIXED) ---
class QuotePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 20); self.cell(80, 10, 'MSI', 0, 0, 'L') 
        self.set_font('Arial', 'B', 16); self.cell(110, 10, 'Quote', 0, 1, 'R')
        self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Generated by Product Check App - MSI Confidential', 0, 0, 'C')

def create_pdf(quote_row):
    pdf = QuotePDF(); pdf.add_page(); pdf.set_auto_page_break(True, 15)
    
    # Load Items
    raw_items = quote_row.get('items_json', '[]')
    try: items = normalize_items(json.loads(raw_items))
    except: items = []
    
    # Sanitize
    c_name = sanitize_text(quote_row.get('client_name', ''))
    c_email = sanitize_text(quote_row.get('client_email', ''))
    c_phone = sanitize_text(str(quote_row.get('client_phone', '')))
    qid = sanitize_text(str(quote_row.get('quote_id', '')))
    dt = str(quote_row.get('created_at', ''))[:10]
    exp = str(quote_row.get('expiration_date', ''))
    if not exp or exp == 'nan': exp = "N/A"
    
    sub = sum(i['total'] for i in items)
    gst = sub * 0.10; grand = sub + gst
    
    # Header
    pdf.set_font('Arial', '', 10); rx = 130
    pdf.set_xy(rx, 20); pdf.cell(30, 6, "Quote ref:", 0, 0); pdf.cell(30, 6, qid, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Issue date:", 0, 0); pdf.cell(30, 6, dt, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Expires:", 0, 0); pdf.cell(30, 6, exp, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Currency:", 0, 0); pdf.cell(30, 6, "AUD", 0, 1)
    pdf.ln(10)
    
    ys = pdf.get_y()
    pdf.set_font('Arial', 'B', 11); pdf.cell(90, 6, "Seller", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(90, 5, "MSI Australia", 0, 1)
    pdf.cell(90, 5, "Suite 304, Level 3, 63-79 Parramatta Rd", 0, 1)
    pdf.cell(90, 5, "Silverwater, NSW 2128, Australia", 0, 1)
    pdf.cell(90, 5, "Contact: Vincent Xu (vincentxu@msi.com)", 0, 1)
    
    pdf.set_xy(110, ys)
    pdf.set_font('Arial', 'B', 11); pdf.cell(80, 6, "Buyer", 0, 1)
    pdf.set_x(110); pdf.set_font('Arial', '', 10)
    pdf.cell(80, 5, c_name, 0, 1)
    if c_email: pdf.set_x(110); pdf.cell(80, 5, f"Email: {c_email}", 0, 1)
    if c_phone and c_phone != 'nan': pdf.set_x(110); pdf.cell(80, 5, f"Phone: {c_phone}", 0, 1)
    pdf.ln(15)
    
    # Table Header
    pdf.set_font('Arial', 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 8, "Item", 1, 0, 'L', True); pdf.cell(15, 8, "Qty", 1, 0, 'C', True)
    pdf.cell(25, 8, "Price", 1, 0, 'R', True); pdf.cell(30, 8, "Disc", 1, 0, 'R', True)
    pdf.cell(30, 8, "Total", 1, 1, 'R', True)
    
    pdf.set_font('Arial', '', 9)
    if not items:
        pdf.cell(190, 10, "No items found in data.", 1, 1, 'C')
    else:
        for i in items:
            nm = sanitize_text(i['name'])
            if len(nm)>50: nm = nm[:47]+"..."
            
            ds = f"{i['discount_val']}%" if i['discount_type']=='%' else f"${i['discount_val']}"
            pdf.cell(90, 8, nm, 1, 0, 'L')
            pdf.cell(15, 8, str(int(i['qty'])), 1, 0, 'C')
            pdf.cell(25, 8, f"${i['price']:,.2f}", 1, 0, 'R')
            pdf.cell(30, 8, ds, 1, 0, 'R')
            pdf.cell(30, 8, f"${i['total']:,.2f}", 1, 1, 'R')
            
            d_txt = sanitize_text(i['desc'])
            if d_txt:
                pdf.set_font('Arial', 'I', 8)
                pdf.cell(190, 6, f"   {d_txt[:100]}", 'L', 1, 'L')
                pdf.set_font('Arial', '', 9)

    pdf.ln(5)
    pdf.set_x(130); pdf.cell(30, 6, "Subtotal:", 0, 0, 'R'); pdf.cell(30, 6, f"${sub:,.2f}", 0, 1, 'R')
    pdf.set_x(130); pdf.cell(30, 6, "GST (10%):", 0, 0, 'R'); pdf.cell(30, 6, f"${gst:,.2f}", 0, 1, 'R')
    pdf.set_font('Arial', 'B', 10)
    pdf.set_x(130); pdf.cell(30, 8, "Total:", 0, 0, 'R'); pdf.cell(30, 8, f"${grand:,.2f}", 0, 1, 'R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN APP ---
def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"): st.session_state['logged_in'] = False; st.rerun()
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Quote Generator", "Upload (Direct)", "Data Update (Direct)"])
    
    # 1. SEARCH
    if menu == "Product Search & Browse":
        st.header("🔎 Product Search")
        if st.button("Refresh"): dm.get_all_products_df.clear(); st.rerun()
        try: df = dm.get_all_products_df()
        except: df = pd.DataFrame()
        
        tab1, tab2 = st.tabs(["Search", "Browse"])
        with tab1:
            if not df.empty:
                df_lbl, name_col = generate_search_labels(df)
                if df_lbl.empty: st.warning("No data"); st.stop()
                
                df_lbl = df_lbl.dropna(subset=['Search_Label'])
                opts = sorted(df_lbl['Search_Label'].unique().tolist())
                
                c1, c2 = st.columns([8, 1])
                sel = c1.selectbox("Search", opts, index=None, key="s_main")
                if c2.button("Clear"): st.session_state["s_main"] = None; st.rerun()
                
                if sel:
                    st.divider()
                    res = df_lbl[df_lbl['Search_Label'] == sel]
                    for i, r in res.iterrows():
                        with st.expander(f"📦 {r[name_col]}", expanded=True):
                            for c in res.columns:
                                if c not in ['Search_Label'] and 'price' not in c.lower() and 'cost' not in c.lower():
                                    st.write(f"**{c}:** {r[c]}")
                            st.metric("Price", f"${safe_float(r.get('Price', 0)):,.2f}")
        with tab2:
            cats = dm.get_categories()
            if cats:
                cs = st.selectbox("Category", cats)
                if not df.empty and 'category' in df.columns:
                    cd = df[df['category'] == cs]
                    st.dataframe(cd, use_container_width=True)

    # 2. QUOTE
    elif menu == "Quote Generator":
        st.header("📝 Quotes")
        t1, t2 = st.tabs(["Create", "History"])
        
        with t1:
            try: df = dm.get_all_products_df()
            except: df = pd.DataFrame()
            search_opts = []
            df_lbl = pd.DataFrame()
            name_col = None
            if not df.empty:
                df_lbl, name_col = generate_search_labels(df)
                if not df_lbl.empty:
                    df_lbl = df_lbl.dropna(subset=['Search_Label'])
                    search_opts = sorted(df_lbl['Search_Label'].unique().tolist())

            st.subheader("1. Client Details")
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                q_client = c1.text_input("Client Name", key="q_client_input")
                q_email = c2.text_input("Client Email", key="q_email_input")
                q_phone = c3.text_input("Client Phone", key="q_phone_input") 
                c4, c5 = st.columns(2)
                q_date = c4.date_input("Date", date.today(), key="q_date_input")
                q_expire = c5.date_input("Expires", date.today(), key="q_expire_input")

            st.divider()

            st.subheader("2. Add Line Item")
            st.selectbox("Search Database (Auto-fill)", options=search_opts, index=None, key="q_search_product", on_change=on_product_search_change)
            
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                c1.text_input("Product Name", key="input_name")
                c2.text_input("Description", key="input_desc")
                c3, c4, c5, c6 = st.columns(4)
                c3.number_input("Qty", 1.0, step=1.0, key="input_qty")
                c4.number_input("Unit Price ($)", 0.0, key="input_price")
                c5.number_input("Discount", 0.0, key="input_disc_val")
                c6.selectbox("Type", ["%", "$"], key="input_disc_type")
                st.button("➕ Add Line Item", on_click=add_line_item_callback)

            st.divider()
            
            st.subheader("3. Review Items")
            if st.session_state['quote_items']:
                st.session_state['quote_items'] = normalize_items(st.session_state['quote_items'])
                q_df = pd.DataFrame(st.session_state['quote_items'])
                
                # Simple Editor - No fancy tricks
                edited = st.data_editor(
                    q_df, num_rows="dynamic", use_container_width=True, key="simple_editor",
                    column_config={
                        "name": st.column_config.TextColumn("Item", width="large"),
                        "total": st.column_config.NumberColumn("Net", disabled=True)
                    }
                )
                
                # Recalc
                items_save = []
                sub_ex = 0; tot_disc = 0
                for idx, row in edited.iterrows():
                    q = safe_float(row.get('qty', 1)); p = safe_float(row.get('price', 0))
                    d = safe_float(row.get('discount_val', 0)); t = row.get('discount_type', '%')
                    g = q * p
                    di = g * (d/100) if t == '%' else d
                    n = g - di
                    sub_ex += n; tot_disc += di
                    r = row.to_dict(); r['total'] = n
                    items_save.append(r)
                
                # Don't update state mid-run to avoid loops, just use for display
                st.session_state['quote_items'] = items_save # Save for button click

                gst = sub_ex*0.10; grand = sub_ex+gst
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Subtotal (Ex GST)", f"${sub_ex:,.2f}")
                m2.metric("Total Discount", f"${tot_disc:,.2f}")
                m3.metric("GST (10%)", f"${gst:,.2f}")
                m4.metric("Grand Total", f"${grand:,.2f}")
                
                c_a1, c_a2 = st.columns([1, 4])
                c_a1.button("💾 Save Quote", type="primary", on_click=save_quote_callback)
                if c_a2.button("Clear"): st.session_state['quote_items'] = []; st.rerun()
            else: st.info("No items.")

        with t2:
            st.subheader("📜 History")
            if st.button("Refresh"): dm.get_quotes.clear(); st.rerun()
            hist = dm.get_quotes()
            if not hist.empty:
                hist.columns = [c.strip() for c in hist.columns]
                if 'created_at' in hist.columns: hist = hist.sort_values('created_at', ascending=False)
                
                for i, r in hist.iterrows():
                    # Fallback Total
                    try:
                        amt = safe_float(r.get('total_amount', 0))
                        if amt == 0 and 'items_json' in r:
                            its = normalize_items(json.loads(r['items_json']))
                            amt = sum(x['total'] for x in its) * 1.10
                    except: amt = 0.0
                    
                    with st.expander(f"{r.get('created_at','?')} | {r.get('client_name','?')} | ${amt:,.2f}"):
                        try:
                            pdf_data = create_pdf(r)
                            st.download_button("📩 Download PDF", pdf_data, f"Quote.pdf", "application/pdf")
                        except Exception as e: st.error(f"PDF Error: {e}")
                        
                        if st.button("Delete", key=f"d_{i}"):
                            dm.delete_quote(r.get('quote_id'), st.session_state['user'])
                            st.rerun()
            else: st.info("No quotes found.")

    # 3. UPLOAD
    elif menu == "Upload (Direct)":
        st.header("📂 Upload"); c1, c2 = st.columns(2)
        with c1: cats = dm.get_categories(); cs = st.selectbox("Cat", cats if cats else ["Default"])
        with c2: 
            nc = st.text_input("New"); 
            if st.button("Add"): 
                if nc: dm.add_category(nc, st.session_state['user']); st.rerun()
        up = st.file_uploader("File", accept_multiple_files=True); hh = st.checkbox("Headers?", True)
        if up:
            for f in up:
                if st.button(f"Save {f.name}"):
                    try:
                        df = pd.read_csv(f, header=0 if hh else None) if f.name.endswith('csv') else pd.read_excel(f, header=0 if hh else None)
                        dm.save_products_dynamic(df.dropna(how='all'), cs, st.session_state['user'])
                        st.success("Saved"); time.sleep(1); st.rerun()
                    except Exception as e: st.error(str(e))

    # 4. UPDATE
    elif menu == "Data Update (Direct)":
        st.header("🔄 Update"); cats = dm.get_categories(); cs = st.selectbox("Cat", cats)
        up = st.file_uploader("File"); hh = st.checkbox("Headers?", True, key="uph")
        if up:
            df = pd.read_csv(up, header=0 if hh else None) if up.name.endswith('csv') else pd.read_excel(up, header=0 if hh else None)
            st.write(df.head(3)); k = st.selectbox("Key", list(df.columns))
            if st.button("Update"):
                r = dm.update_products_dynamic(df, cs, st.session_state['user'], k)
                st.success(f"Done. New: {r['new']}, EOL: {r['eol']}")

# --- AUTH ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""
if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []

# Init Inputs
if 'input_name' not in st.session_state: st.session_state['input_name'] = ""
if 'input_desc' not in st.session_state: st.session_state['input_desc'] = ""
if 'input_price' not in st.session_state: st.session_state['input_price'] = 0.0
if 'input_qty' not in st.session_state: st.session_state['input_qty'] = 1.0
if 'input_disc_val' not in st.session_state: st.session_state['input_disc_val'] = 0.0
if 'input_disc_type' not in st.session_state: st.session_state['input_disc_type'] = '%'

def check_login(u, p):
    try: users = dm.get_users()
    except: return False, "DB Error"
    if users.empty: return False, "No users"
    user = users[(users['username'] == u) & (users['password'] == hashlib.sha256(str.encode(p)).hexdigest())]
    return (True, user.iloc[0]['role']) if not user.empty else (False, "Invalid")

def login_page():
    st.title("🔐 Login")
    u = st.text_input("User")
    p = st.text_input("Pass", type="password")
    if st.button("Sign In"):
        s, m = check_login(u, p)
        if s: 
            st.session_state['logged_in'] = True
            st.session_state['user'] = u
            st.rerun()
        else: st.error(m)

if st.session_state['logged_in']: main_app()
else: login_page()
