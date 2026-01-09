import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import difflib
import time
from datetime import date

st.set_page_config(page_title="Product Check App", layout="wide")

# --- HELPER: FUZZY MATCHING ---
def find_best_match(target, options):
    options_lower = [str(o).lower() for o in options]
    matches = difflib.get_close_matches(str(target).lower(), options_lower, n=1, cutoff=0.4)
    if matches:
        match_index = options_lower.index(matches[0])
        return options[match_index]
    return None

# --- AUTH HELPERS ---
def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_login(username, password):
    try:
        users = dm.get_users()
    except Exception as e:
        return False, f"DB Connection Error: {str(e)}"
        
    if users.empty: return False, "No users in DB"
    hashed = hash_pw(password)
    user = users[(users['username'] == username) & (users['password'] == hashed)]
    if not user.empty:
        status = user.iloc[0]['status']
        if status == 'active': return True, user.iloc[0]['role']
        if status == 'pending': return False, "Account pending approval"
    return False, "Invalid credentials"

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""

# Initialize Quote Session State
if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []

# --- LOGIN PAGE ---
def login_page():
    st.title("🔐 Login")
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Sign In"):
            success, msg = check_login(u, p)
            if success:
                st.session_state['logged_in'] = True
                st.session_state['user'] = u
                dm.log_action(u, "Login", "Success")
                st.rerun()
            else:
                st.error(msg)
    with tab2:
        new_u = st.text_input("New Username")
        new_p = st.text_input("New Password", type="password")
        new_e = st.text_input("Email")
        if st.button("Register"):
            dm.register_user(new_u, hash_pw(new_p), new_e)
            st.success("Sent. Wait for approval.")

# --- MAIN APP ---
def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    # --- NAVIGATION MENU ---
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Quote Generator (New)", "Upload (Direct)", "Data Update (Direct)"])
    
    # =======================================================
    # 1. PRODUCT SEARCH & BROWSE
    # =======================================================
    if menu == "Product Search & Browse":
        st.header("🔎 Product Search & Browse")
        
        # 1. Refresh Button
        if st.button("Refresh Database"):
            try:
                dm.get_all_products_df.clear()
                st.toast("Cache cleared. Reloading...", icon="🔄")
                time.sleep(1) 
                st.rerun()
            except Exception as e:
                st.error(f"Error refreshing: {e}")

        # 2. Safe Data Loading
        try:
            df = dm.get_all_products_df()
        except Exception as e:
            st.error("⚠️ Connection Busy: Google Sheets API limit reached.")
            st.caption("Please wait 10 seconds and click 'Refresh Database' again.")
            df = pd.DataFrame()

        # 3. Create Tabs
        tab_search, tab_browse = st.tabs(["Search (Predictive)", "Browse Full Category"])

        # --- TAB 1: PREDICTIVE SEARCH ---
        with tab_search:
            if not df.empty:
                def col_has_data(dataframe, col_name):
                    if col_name not in dataframe.columns: return False
                    s = dataframe[col_name].astype(str).str.strip()
                    is_empty = s.str.lower().isin(['nan', 'none', '', 'nat'])
                    return not is_empty.all()

                valid_data_cols = [c for c in df.columns if col_has_data(df, c)]
                
                if not valid_data_cols:
                    st.error("Data loaded, but all columns appear empty.")
                else:
                    name_col = None
                    for col in valid_data_cols:
                        if 'product' in col.lower() and 'name' in col.lower():
                            name_col = col
                            break
                    if not name_col:
                        for col in valid_data_cols:
                            if 'model' in col.lower():
                                name_col = col
                                break
                    if not name_col: name_col = valid_data_cols[0]

                    search_df = df.copy()

                    forbidden_in_search = [
                        'price', 'cost', 'srp', 'msrp', 'rrp', 'margin', 
                        'date', 'time', 'last_updated', 'timestamp',
                        'category', 'class', 'group', 'segment' 
                    ]

                    def make_search_label(row):
                        main_name = str(row[name_col]) if pd.notnull(row[name_col]) else ""
                        label_parts = [main_name.strip()]

                        for col in valid_data_cols:
                            if col == name_col: continue
                            if any(k in col.lower() for k in forbidden_in_search): continue
                            
                            val = str(row[col]).strip()
                            if val and val.lower() not in ['nan', 'none', '']:
                                if val not in label_parts:
                                    label_parts.append(val)
                        
                        return " | ".join(filter(None, label_parts))

                    search_df['Search_Label'] = search_df.apply(make_search_label, axis=1)
                    search_options = sorted([x for x in search_df['Search_Label'].unique().tolist() if x])

                    c_bar, c_clear = st.columns([8, 1])
                    with c_bar:
                        selected_label = st.selectbox(
                            label="Search Product",
                            options=search_options,
                            index=None, 
                            placeholder="Start typing Name or SKU...",
                            label_visibility="collapsed",
                            key="search_selectbox"
                        )
                    with c_clear:
                        def clear_search():
                            st.session_state["search_selectbox"] = None
                        st.button("Clear", on_click=clear_search)

                    st.divider()

                    if selected_label:
                        results = search_df[search_df['Search_Label'] == selected_label]
                        results = results.drop(columns=['Search_Label'])
                        
                        if not results.empty:
                            for i, row in results.iterrows():
                                card_title = str(row[name_col])
                                with st.expander(f"📦 {card_title}", expanded=True):
                                    hidden_keywords = ['price', 'cost', 'srp', 'msrp', 'rrp', 'margin']
                                    all_cols = results.columns.tolist()
                                    price_cols = [c for c in all_cols if any(k in c.lower() for k in hidden_keywords)]
                                    public_cols = [c for c in all_cols if c not in price_cols and c != 'Search_Label']
                                    
                                    for col in public_cols:
                                        val = str(row[col]).strip()
                                        if val and val.lower() != 'nan':
                                            st.write(f"**{col}:** {row[col]}")
                                    
                                    if price_cols:
                                        st.markdown("---")
                                        show_price = st.toggle("Show Price 💰", key=f"toggle_{i}")
                                        if show_price:
                                            cols = st.columns(len(price_cols))
                                            for idx, p_col in enumerate(price_cols):
                                                val = row[p_col]
                                                try: val = f"{float(val):,.2f}"
                                                except: pass
                                                cols[idx].metric(label=p_col, value=val)
            else:
                if 'df' in locals() and df.empty: 
                    st.warning("Database is empty. Please upload a file in the Admin tab.")

        # --- TAB 2: BROWSE FULL CATEGORY ---
        with tab_browse:
            try: cats = dm.get_categories()
            except: cats = []
            if not cats:
                st.warning("No categories found.")
            else:
                cat_sel = st.selectbox("Select Category to View", cats)
                if not df.empty and 'category' in df.columns:
                    cat_data = df[df['category'] == cat_sel]
                    if not cat_data.empty:
                        st.write(f"**Total Items:** {len(cat_data)}")
                        st.dataframe(cat_data, use_container_width=True)
                        output = BytesIO()
                        with pd.ExcelWriter(output) as writer:
                            cat_data.to_excel(writer, index=False)
                        st.download_button(
                            label=f"⬇️ Download '{cat_sel}' Pricebook",
                            data=output.getvalue(),
                            file_name=f"{cat_sel}_Pricebook.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.info(f"No data found for category: {cat_sel}")
                else:
                    st.info("No product data available or 'category' column missing.")

   # =======================================================
    # 2. QUOTE GENERATOR (UPDATED SEARCH LOGIC)
    # =======================================================
    elif menu == "Quote Generator (New)":
        st.header("📝 Create Quote")
        
        # Load Products
        try: df = dm.get_all_products_df()
        except: df = pd.DataFrame()

        # Layout: Split into "Details" and "Line Items"
        c_details, c_items = st.columns([1, 2])
        
        with c_details:
            st.subheader("1. Client Details")
            with st.container(border=True):
                q_client = st.text_input("Client Name / Company")
                q_email = st.text_input("Client Email")
                q_date = st.date_input("Date", date.today())
                q_expire = st.date_input("Expiration Date", date.today())
                q_terms = st.text_area("Terms & Conditions", "Payment due within 30 days.")

        with c_items:
            st.subheader("2. Line Items")
            
            # --- TABBED INTERFACE FOR ADDING ITEMS ---
            tab_add_db, tab_add_manual = st.tabs(["Search Database", "➕ Add Custom Item"])
            
            # A. Search Database (Improved Logic)
            with tab_add_db:
                if not df.empty:
                    # --- 1. REUSE ROBUST LOGIC FROM MAIN TAB ---
                    def col_has_data(dataframe, col_name):
                        if col_name not in dataframe.columns: return False
                        s = dataframe[col_name].astype(str).str.strip()
                        is_empty = s.str.lower().isin(['nan', 'none', '', 'nat'])
                        return not is_empty.all()

                    valid_data_cols = [c for c in df.columns if col_has_data(df, c)]
                    
                    if not valid_data_cols:
                        st.error("Data loaded, but columns appear empty.")
                    else:
                        # Find Name Column
                        name_col = None
                        for col in valid_data_cols:
                            if 'product' in col.lower() and 'name' in col.lower():
                                name_col = col
                                break
                        if not name_col:
                            for col in valid_data_cols:
                                if 'model' in col.lower():
                                    name_col = col
                                    break
                        if not name_col: name_col = valid_data_cols[0]

                        # Create Clean Search Labels
                        search_df = df.copy()
                        forbidden_in_search = [
                            'price', 'cost', 'srp', 'msrp', 'rrp', 'margin', 
                            'date', 'time', 'last_updated', 'timestamp',
                            'category', 'class', 'group', 'segment' 
                        ]

                        def make_search_label(row):
                            main_name = str(row[name_col]) if pd.notnull(row[name_col]) else ""
                            label_parts = [main_name.strip()]

                            for col in valid_data_cols:
                                if col == name_col: continue
                                if any(k in col.lower() for k in forbidden_in_search): continue
                                
                                val = str(row[col]).strip()
                                if val and val.lower() not in ['nan', 'none', '']:
                                    if val not in label_parts:
                                        label_parts.append(val)
                            
                            return " | ".join(filter(None, label_parts))

                        search_df['Search_Label'] = search_df.apply(make_search_label, axis=1)
                        search_options = sorted([x for x in search_df['Search_Label'].unique().tolist() if x])

                        # --- 2. SEARCH WIDGET ---
                        sel_label = st.selectbox(
                            "Find Product", 
                            options=search_options, 
                            index=None, 
                            placeholder="Type Name, SKU or Specs..."
                        )
                        
                        # --- 3. AUTO-FILL DETAILS ---
                        if sel_label:
                            # Get the full row data
                            row = search_df[search_df['Search_Label'] == sel_label].iloc[0]
                            
                            # Intelligent Price Detection
                            price_guess = 0.0
                            # Look for columns with 'price', 'msrp', 'srp', 'cost'
                            price_cols = [c for c in df.columns if any(x in c.lower() for x in ['price', 'msrp', 'srp', 'cost'])]
                            if price_cols:
                                # Pick the first one that looks like a number
                                for p_col in price_cols:
                                    try:
                                        val_str = str(row[p_col]).replace('$', '').replace(',', '').strip()
                                        if val_str and val_str.lower() != 'nan':
                                            price_guess = float(val_str)
                                            break
                                    except: continue

                            # Intelligent Description Detection
                            desc_guess = ""
                            desc_cols = [c for c in df.columns if any(x in c.lower() for x in ['desc', 'spec', 'detail'])]
                            if desc_cols:
                                desc_guess = str(row[desc_cols[0]])
                            
                            # Display Inputs
                            st.caption(f"Selected: **{row[name_col]}**")
                            c1, c2, c3 = st.columns(3)
                            add_qty = c1.number_input("Qty", 1, 1000, 1)
                            add_price = c2.number_input("Unit Price", value=price_guess)
                            add_disc = c3.number_input("Discount %", 0, 100, 0)
                            
                            if st.button("Add to Quote", key="btn_add_db"):
                                item = {
                                    "name": str(row[name_col]),
                                    "desc": desc_guess,
                                    "qty": add_qty,
                                    "price": add_price,
                                    "discount": add_disc,
                                    "total": (add_price * add_qty) * (1 - add_disc/100)
                                }
                                st.session_state['quote_items'].append(item)
                                st.success(f"Added: {row[name_col]}")
                                time.sleep(0.5)
                                st.rerun()

            # B. Add Manual Item (Logged)
            with tab_add_manual:
                st.info("Item not in database? Add it here. (Action will be logged)")
                with st.form("manual_add"):
                    m_name = st.text_input("Product Name")
                    m_desc = st.text_input("Description")
                    c1, c2, c3 = st.columns(3)
                    m_qty = c1.number_input("Qty", 1, 1000, 1)
                    m_price = c2.number_input("Unit Price ($)", 0.0)
                    m_disc = c3.number_input("Discount %", 0, 100, 0)
                    
                    if st.form_submit_button("Add Custom Item"):
                        if m_name:
                            item = {
                                "name": m_name,
                                "desc": m_desc,
                                "qty": m_qty,
                                "price": m_price,
                                "discount": m_disc,
                                "total": (m_price * m_qty) * (1 - m_disc/100)
                            }
                            st.session_state['quote_items'].append(item)
                            dm.log_action(st.session_state['user'], "Manual Quote Item", f"Added: {m_name} | ${m_price}")
                            st.success(f"Added Custom: {m_name}")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("Name required")

        st.divider()
        
        # --- 3. QUOTE REVIEW (Editable Table) ---
        st.subheader("3. Review & Finalize")
        
        if st.session_state['quote_items']:
            q_df = pd.DataFrame(st.session_state['quote_items'])
            
            edited_df = st.data_editor(
                q_df, 
                num_rows="dynamic", 
                column_config={
                    "total": st.column_config.NumberColumn("Total", disabled=True),
                    "price": st.column_config.NumberColumn("Unit Price", format="$%.2f"),
                },
                use_container_width=True,
                key="editor_quote"
            )
            
            final_total = 0
            items_to_save = []
            for index, row in edited_df.iterrows():
                line_total = (row['price'] * row['qty']) * (1 - row['discount']/100)
                final_total += line_total
                
                row_data = row.to_dict()
                row_data['total'] = line_total
                items_to_save.append(row_data)

            st.metric("Grand Total", f"${final_total:,.2f}")
            
            c_save, c_clear = st.columns([1, 5])
            
            if c_save.button("💾 Save Quote", type="primary"):
                if not q_client:
                    st.error("Please enter Client Name.")
                else:
                    quote_payload = {
                        "client_name": q_client,
                        "client_email": q_email,
                        "total_amount": final_total,
                        "items": items_to_save
                    }
                    new_id = dm.save_quote(quote_payload, st.session_state['user'])
                    st.success(f"Quote Saved! ID: {new_id}")
                    st.session_state['quote_items'] = []
                    time.sleep(2)
                    st.rerun()
            
            if c_clear.button("Clear All"):
                st.session_state['quote_items'] = []
                st.rerun()
                
        else:
            st.info("No items in quote yet.")

    # =======================================================
    # 3. UPLOAD (DIRECT - NO MAPPING)
    # =======================================================
    elif menu == "Upload (Direct)":
        st.header("📂 File Upload (Direct)")
        st.info("Files uploaded here are saved with their original table structure.")
        
        c_left, c_right = st.columns([1, 1])
        with c_left:
            cats = dm.get_categories()
            if not cats: cats = ["Default"]
            cat_sel = st.selectbox("Select Category", cats)
        with c_right:
            new_cat = st.text_input("New Category Name")
            if st.button("Add Cat"):
                if new_cat:
                    dm.add_category(new_cat, st.session_state['user'])
                    st.success(f"Added '{new_cat}'")
                    st.rerun()
        st.divider()

        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        has_headers = st.checkbox("My file has a header row (e.g. 'SKU', 'Name')", value=True)
        
        if files:
            for file in files:
                st.markdown(f"### 📄 {file.name}")
                try:
                    header_arg = 0 if has_headers else None
                    if file.name.endswith('csv'): 
                        df = pd.read_csv(file, header=header_arg)
                    else: 
                        df = pd.read_excel(file, header=header_arg)
                    
                    df = df.dropna(how='all').dropna(axis=1, how='all')
                    st.write("Preview (Ready to Save):", df.head(3))
                    
                    if st.button(f"☁️ Save '{file.name}'", key=f"save_{file.name}"):
                        dm.save_products_dynamic(df, cat_sel, st.session_state['user'])
                        st.success(f"Saved {len(df)} rows to '{cat_sel}'!")
                        time.sleep(1)
                        st.rerun()
                except Exception as e:
                    st.error(f"Error processing file: {e}")

    # =======================================================
    # 4. DATA UPDATE (DIRECT - NO MAPPING)
    # =======================================================
    elif menu == "Data Update (Direct)":
        st.header("🔄 Update Existing Category")
        st.info("Upload a new file to identify changes (New vs EOL).")
        
        cats = dm.get_categories()
        cat_sel = st.selectbox("Category to Update", cats)
        
        up_file = st.file_uploader("Upload New Pricebook")
        has_headers_up = st.checkbox("File has headers", value=True, key="up_headers")
        
        if up_file:
            try:
                header_arg = 0 if has_headers_up else None
                if up_file.name.endswith('csv'): df = pd.read_csv(up_file, header=header_arg)
                else: df = pd.read_excel(up_file, header=header_arg)
                
                df = df.dropna(how='all').dropna(axis=1, how='all')
                
                st.write("File Preview:", df.head(3))
                
                st.markdown("### Select Unique ID")
                st.caption("Select the column that identifies unique products (e.g. SKU).")
                
                default_idx = 0
                cols = list(df.columns)
                for i, col in enumerate(cols):
                    if 'sku' in str(col).lower() or 'model' in str(col).lower():
                        default_idx = i
                        break
                        
                key_col = st.selectbox("Unique ID Column:", cols, index=default_idx)

                if st.button("Analyze Differences & Update"):
                    res = dm.update_products_dynamic(df, cat_sel, st.session_state['user'], key_col)
                    if "error" in res:
                        st.error(res["error"])
                    else:
                        st.success(f"Update Complete! New Items: {res['new']}, Marked EOL: {res['eol']}")
                        
            except Exception as e:
                st.error(f"Error reading file: {e}")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()

