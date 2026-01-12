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

# --- HELPERS ---
def safe_float(val):
    try:
        clean = str(val).replace('$', '').replace(',', '').strip()
        if not clean or clean.lower() in ['none', 'nan']: return 0.0
        return float(clean)
    except: return 0.0

def sanitize_text(text):
    if not isinstance(text, str): return str(text)
    text = text.replace('\u2013', '-').replace('\u2019', "'")
    return text.encode('latin-1', 'replace').decode('latin-1')

def normalize_items(items):
    clean = []
    if not isinstance(items, list): return []
    for item in items:
        n = item.copy()
        n['qty'] = safe_float(n.get('qty', 1))
        n['price'] = safe_float(n.get('price', 0))
        n['discount_val'] = safe_float(n.get('discount_val', 0))
        if 'discount_type' not in n: n['discount_type'] = '%'
        if 'desc' not in n: n['desc'] = ""
        if 'name' not in n: n['name'] = "Item"
        
        g = n['qty'] * n['price']
        d = g * (n['discount_val']/100) if n['discount_type'] == '%' else n['discount_val']
        n['total'] = g - d
        clean.append(n)
    return clean

# --- SEARCH LOGIC ---
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

# --- CALLBACKS ---
def on_search_change():
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

def add_item_cb():
    name = st.session_state.get('input_name', '')
    if not name: st.toast("Name required!", icon="⚠️"); return
    item = {
        "name": name, "desc": st.session_state.get('input_desc', ''),
        "qty": st.session_state.get('input_qty', 1.0),
        "price": st.session_state.get('input_price', 0.0),
        "discount_val": st.session_state.get('input_disc_val', 0.0),
        "discount_type": st.session_state.get('input_disc_type', '%'),
        "total": 0
    }
    if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []
    st.session_state['quote_items'].append(item)
    st.session_state['input_name'] = ""
    st.session_state['input_desc'] = ""
    st.session_state['input_price'] = 0.0
    st.session_state['q_search_product'] = None
    st.toast("Item Added!")

def save_quote_cb():
    if not st.session_state.get("q_client_input"): st.toast("Client Name Required!", icon="⚠️"); return
    items = st.session_state.get('quote_items', [])
    if not items: st.toast("No items!", icon="⚠️"); return
    
    items = normalize_items(items)
    total = sum(i['total'] for i in items) * 1.10
    
    seller_data = {
        "name": st.session_state.get("s_name", ""),
        "email": st.session_state.get("s_email", ""),
        "phone": st.session_state.get("s_phone", "")
    }

    payload = {
        "client_name": st.session_state.get("q_client_input"),
        "client_email": st.session_state.get("q_email_input"),
        "client_phone": st.session_state.get("q_phone_input"),
        "total_amount": total,
        "expiration_date": str(st.session_state.get("q_expire_input")),
        "seller_info": seller_data,
        "items": items
    }
    dm.save_quote(payload, st.session_state['user'])
    st.session_state['quote_items'] = []
    st.session_state['input_name'] = ""
    st.toast("Quote Saved!", icon="✅")

# --- PDF ENGINE (NEW LAYOUT) ---
class QuotePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 20); self.cell(80, 10, 'MSI', 0, 0, 'L') 
        self.set_font('Arial', 'B', 16); self.cell(110, 10, 'Quote', 0, 1, 'R'); self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Generated by Product Check App - MSI Confidential', 0, 0, 'C')

def create_pdf(quote_row):
    pdf = QuotePDF(); pdf.add_page(); pdf.set_auto_page_break(True, 15)
    
    raw_items = quote_row.get('items_json', '[]')
    try: items = normalize_items(json.loads(raw_items))
    except: items = []
    
    try: seller_info = json.loads(quote_row.get('seller_info', '{}'))
    except: seller_info = {}
    
    s_name = sanitize_text(seller_info.get("name", "MSI Australia"))
    s_email = sanitize_text(seller_info.get("email", "vincentxu@msi.com"))
    s_phone = sanitize_text(seller_info.get("phone", ""))
    
    c_name = sanitize_text(quote_row.get('client_name', ''))
    c_email = sanitize_text(quote_row.get('client_email', ''))
    c_phone = sanitize_text(str(quote_row.get('client_phone', '')))
    qid = sanitize_text(str(quote_row.get('quote_id', '')))
    dt = str(quote_row.get('created_at', ''))[:10]
    exp = str(quote_row.get('expiration_date', ''))
    if not exp or exp == 'nan': exp = "N/A"
    
    sub = sum(i['total'] for i in items)
    gst = sub * 0.10; grand = sub + gst
    
    # HEADER
    pdf.set_font('Arial', '', 10); rx = 130
    pdf.set_xy(rx, 20); pdf.cell(30, 6, "Quote ref:", 0, 0); pdf.cell(30, 6, qid, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Issue date:", 0, 0); pdf.cell(30, 6, dt, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Expires:", 0, 0); pdf.cell(30, 6, exp, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Currency:", 0, 0); pdf.cell(30, 6, "AUD", 0, 1)
    pdf.ln(10)
    
    # INFO BLOCKS
    ys = pdf.get_y()
    pdf.set_font('Arial', 'B', 11); pdf.cell(90, 6, "Seller", 0, 1)
    pdf.set_font('Arial', '', 10)
    if s_name: pdf.cell(90, 5, s_name, 0, 1)
    else: pdf.cell(90, 5, "MSI Australia", 0, 1)
    
    pdf.cell(90, 5, "Suite 304, Level 3, 63-79 Parramatta Rd", 0, 1)
    pdf.cell(90, 5, "Silverwater, NSW 2128, Australia", 0, 1)
    
    contact_str = f"Email: {s_email}"
    if s_phone: contact_str += f" | Phone: {s_phone}"
    pdf.cell(90, 5, contact_str, 0, 1)
    
    pdf.set_xy(110, ys)
    pdf.set_font('Arial', 'B', 11); pdf.cell(80, 6, "Buyer", 0, 1)
    pdf.set_x(110); pdf.set_font('Arial', '', 10)
    pdf.cell(80, 5, c_name, 0, 1)
    if c_email: pdf.set_x(110); pdf.cell(80, 5, f"Email: {c_email}", 0, 1)
    if c_phone and c_phone != 'nan': pdf.set_x(110); pdf.cell(80, 5, f"Phone: {c_phone}", 0, 1)
    pdf.ln(15)
    
    # TABLE HEADER
    pdf.set_font('Arial', 'B', 10); pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 8, "Item", 1, 0, 'L', True); pdf.cell(15, 8, "Qty", 1, 0, 'C', True)
    pdf.cell(25, 8, "Price", 1, 0, 'R', True); pdf.cell(30, 8, "Disc", 1, 0, 'R', True)
    pdf.cell(30, 8, "Total", 1, 1, 'R', True)
    
    # TABLE ROWS (MULTI-CELL LOGIC)
    pdf.set_font('Arial', '', 9)
    if not items:
        pdf.cell(190, 10, "No items found", 1, 1, 'C')
    else:
        for i in items:
            # Prepare Text
            nm = sanitize_text(i['name'])
            d_txt = sanitize_text(i['desc'])
            full_text = nm
            if d_txt: full_text += f"\n{d_txt}" # Append description in new line inside cell
            
            # Save Start Position
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            
            # Draw Item Column (MultiCell) - Width 90
            pdf.multi_cell(90, 5, full_text, border=1, align='L')
            
            # Calculate Row Height
            y_end = pdf.get_y()
            h_row = y_end - y_start
            
            # Draw Other Columns (Single Cell with calculated height)
            pdf.set_xy(x_start + 90, y_start) # Move back to top-right of Item cell
            
            pdf.cell(15, h_row, str(int(i['qty'])), 1, 0, 'C')
            pdf.cell(25, h_row, f"${i['price']:,.2f}", 1, 0, 'R')
            ds = f"{i['discount_val']}%" if i['discount_type']=='%' else f"${i['discount_val']}"
            pdf.cell(30, h_row, ds, 1, 0, 'R')
            # Last cell moves to next line (ln=1)
            pdf.cell(30, h_row, f"${i['total']:,.2f}", 1, 1, 'R')

    pdf.ln(5)
    pdf.set_x(130); pdf.cell(30, 6, "Subtotal:", 0, 0, 'R'); pdf.cell(30, 6, f"${sub:,.2f}", 0, 1, 'R')
    pdf.set_x(130); pdf.cell(30, 6, "GST (10%):", 0, 0, 'R'); pdf.cell(30, 6, f"${gst:,.2f}", 0, 1, 'R')
    pdf.set_font('Arial', 'B', 10)
    pdf.set_x(130); pdf.cell(30, 8, "Total:", 0, 0, 'R'); pdf.cell(30, 8, f"${grand:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN ---
def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"): st.session_state['logged_in'] = False; st.rerun()
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Quote Generator", "Data Admin"])
    
    if menu == "Product Search & Browse":
        st.header("🔎 Search")
        if st.button("Refresh DB"): dm.get_all_products_df.clear(); st.rerun()
        try: df = dm.get_all_products_df()
        except: df = pd.DataFrame()
        
        t1, t2 = st.tabs(["Search", "Browse"])
        with t1:
            if not df.empty:
                df_lbl, name_col = generate_search_labels(df)
                if df_lbl.empty: st.warning("No data")
                else:
                    opts = sorted(df_lbl['Search_Label'].dropna().unique().tolist())
                    sel = st.selectbox("Search", opts, index=None, key="s_main")
                    if sel:
                        st.divider()
                        res = df_lbl[df_lbl['Search_Label'] == sel]
                        for i, r in res.iterrows():
                            with st.expander(f"📦 {r[name_col]}", expanded=True):
                                price_cols = [c for c in res.columns if any(x in c.lower() for x in ['price', 'cost', 'srp', 'msrp'])]
                                pub_cols = [c for c in res.columns if c not in price_cols and c != 'Search_Label']
                                for c in pub_cols: st.write(f"**{c}:** {r[c]}")
                                if price_cols:
                                    st.markdown("---")
                                    if st.toggle("Show Prices", key=f"t_{i}"):
                                        for pc in price_cols: st.metric(pc, f"{r[pc]}")
        with t2:
            cats = dm.get_categories()
            if cats:
                cs = st.selectbox("Category", cats)
                if not df.empty and 'category' in df.columns:
                    cd = df[df['category'] == cs]
                    if st.toggle("Show Prices in Table", key="t_browse"):
                        st.dataframe(cd, use_container_width=True)
                    else:
                        bad = ['price', 'cost', 'srp', 'msrp']
                        cols = [c for c in cd.columns if not any(x in c.lower() for x in bad)]
                        st.dataframe(cd[cols], use_container_width=True)

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
                if not df_lbl.empty: search_opts = sorted(df_lbl['Search_Label'].dropna().unique().tolist())

            st.subheader("1. Client")
            c1, c2, c3 = st.columns(3)
            c1.text_input("Name", key="q_client_input")
            c2.text_input("Email", key="q_email_input")
            c3.text_input("Phone", key="q_phone_input")
            c4, c5 = st.columns(2)
            c4.date_input("Date", date.today(), key="q_date_input")
            c5.date_input("Expire", date.today(), key="q_expire_input")
            
            with st.expander("🏢 Seller Details (Optional)"):
                st.text_input("Contact Name", value="Vincent Xu", key="s_name")
                st.text_input("Contact Email", value="vincentxu@msi.com", key="s_email")
                st.text_input("Contact Phone", value="", placeholder="Optional", key="s_phone")

            st.divider()
            st.subheader("2. Add Item")
            st.selectbox("Search (Auto-fill)", search_opts, index=None, key="q_search_product", on_change=on_search_change)
            c1, c2 = st.columns([1, 2])
            c1.text_input("Product", key="input_name")
            c2.text_input("Desc", key="input_desc")
            c3, c4, c5, c6 = st.columns(4)
            c3.number_input("Qty", 1.0, step=1.0, key="input_qty")
            c4.number_input("Price", 0.0, key="input_price")
            c5.number_input("Disc", 0.0, key="input_disc_val")
            c6.selectbox("Type", ["%", "$"], key="input_disc_type")
            st.button("➕ Add", on_click=add_item_cb)
            st.divider()

            st.subheader("3. Review")
            if st.session_state['quote_items']:
                st.session_state['quote_items'] = normalize_items(st.session_state['quote_items'])
                q_df = pd.DataFrame(st.session_state['quote_items'])
                if 'table_key' not in st.session_state: st.session_state['table_key'] = 0
                curr_names = q_df['name'].unique().tolist()
                comb_opts = sorted(list(set(search_opts + curr_names))) if search_opts else curr_names
                
                edited = st.data_editor(
                    q_df, num_rows="dynamic", use_container_width=True, key=f"tbl_{st.session_state['table_key']}",
                    column_config={
                        "name": st.column_config.SelectboxColumn("Item", options=comb_opts, width="large"),
                        "total": st.column_config.NumberColumn("Net", disabled=True)
                    }
                )
                
                new_items = []; trigger = False
                for idx, row in edited.iterrows():
                    nm = str(row['name'])
                    if "|" in nm and nm in search_opts:
                        d = extract_product_data(nm, df_lbl, name_col)
                        if d:
                            row['name'] = d['name']; row['desc'] = d['desc']
                            row['price'] = d['price']; row['qty'] = 1.0
                            trigger = True
                    q = safe_float(row.get('qty', 1)); p = safe_float(row.get('price', 0))
                    d = safe_float(row.get('discount_val', 0)); t = row.get('discount_type', '%')
                    g = q*p; di = g*(d/100) if t=='%' else d
                    row['total'] = g - di
                    new_items.append(row.to_dict())
                
                st.session_state['quote_items'] = new_items
                if trigger: 
                    st.session_state['table_key'] += 1
                    st.rerun()

                sub = sum(i['total'] for i in new_items); gst = sub*0.1; grand = sub+gst
                c1, c2, c3 = st.columns(3)
                c1.metric("Subtotal", f"${sub:,.2f}")
                c2.metric("GST", f"${gst:,.2f}")
                c3.metric("Grand Total", f"${grand:,.2f}")
                c_a1, c_a2 = st.columns([1, 4])
                c_a1.button("💾 Save Quote", type="primary", on_click=save_quote_cb)
                if c_a2.button("Clear"): st.session_state['quote_items'] = []; st.rerun()
            else: st.info("Empty")

        with t2:
            st.subheader("📜 History")
            if st.button("Refresh List"): dm.get_quotes.clear(); st.rerun()
            hist = dm.get_quotes()
            if not hist.empty:
                # Force correct columns if header names are weird
                if 'total_amount' not in hist.columns and len(hist.columns) > 7:
                    # Fallback mapping based on fixed index
                    pass 
                
                hist.columns = [c.strip() for c in hist.columns]
                if 'created_at' in hist.columns: hist = hist.sort_values('created_at', ascending=False)
                
                for i, r in hist.iterrows():
                    try:
                        amt = safe_float(r.get('total_amount', 0))
                        # Fix mismatch if total is 0
                        if amt == 0 and 'items_json' in r:
                            its = normalize_items(json.loads(r['items_json']))
                            amt = sum(x['total'] for x in its) * 1.10
                    except: amt = 0.0
                    with st.expander(f"{r.get('created_at','?')} | {r.get('client_name','?')} | ${amt:,.2f}"):
                        try:
                            pdf_data = create_pdf(r)
                            st.download_button("📩 Download PDF", pdf_data, f"Quote.pdf", "application/pdf")
                        except Exception as e: st.error(f"PDF Error: {e}")
                        if st.button("✏️ Edit", key=f"e_{i}"):
                            try:
                                st.session_state['quote_items'] = normalize_items(json.loads(r['items_json']))
                                st.session_state['q_client_input'] = r.get('client_name', '')
                                st.session_state['q_email_input'] = r.get('client_email', '')
                                st.session_state['q_phone_input'] = r.get('client_phone', '')
                                # Load Seller Info if present
                                s_inf = json.loads(r.get('seller_info', '{}'))
                                st.session_state['s_name'] = s_inf.get('name', 'Vincent Xu')
                                st.session_state['s_email'] = s_inf.get('email', 'vincentxu@msi.com')
                                st.session_state['s_phone'] = s_inf.get('phone', '')
                                st.toast("Loaded!"); time.sleep(1)
                            except: st.error("Data Error")
                        if st.button("Delete", key=f"d_{i}"):
                            dm.delete_quote(r.get('quote_id'), st.session_state['user'])
                            st.rerun()
            else: st.info("No quotes found.")

    elif menu == "Data Admin":
        st.header("📂 Data Admin")
        up = st.file_uploader("Upload", accept_multiple_files=False)
        cats = dm.get_categories()
        c_sel = st.selectbox("Category", cats if cats else ["Default"])
        if up and st.button("Process"):
            try:
                df = pd.read_csv(up) if up.name.endswith('csv') else pd.read_excel(up)
                dm.save_products_dynamic(df.dropna(how='all'), c_sel, st.session_state['user'])
                st.success("Done!")
            except Exception as e: st.error(str(e))

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""
if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []
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
