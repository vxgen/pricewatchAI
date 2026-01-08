import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import difflib
import time

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
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Upload (Direct)", "Data Update"])
    
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
                # --- HELPER: ROBUST DATA CHECK ---
                def col_has_data(dataframe, col_name):
                    if col_name not in dataframe.columns: return False
                    s = dataframe[col_name].astype(str).str.strip()
                    is_empty = s.str.lower().isin(['nan', 'none', '', 'nat'])
                    return not is_empty.all()

                valid_data_cols = [c for c in df.columns if col_has_data(df, c)]
                
                if not valid_data_cols:
                    st.error("Data loaded, but all columns appear empty.")
                else:
                    # --- STEP A: FIND NAME COLUMN ---
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

                    # --- STEP B: BUILD CLEAN SEARCH LABEL ---
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

                    # --- STEP C: SEARCH WIDGET ---
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

                    # --- STEP D: SHOW RESULTS ---
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
    # 2. UPLOAD (DIRECT - NO MAPPING)
    # =======================================================
    elif menu == "Upload (Direct)":
        st.header("📂 File Upload (Direct)")
        
        # 1. Category Selection
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

        # 2. File Upload
        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        
        if files:
            for file in files:
                st.markdown(f"### 📄 {file.name}")
                try:
                    if file.name.endswith('csv'): 
                        df = pd.read_csv(file)
                    else: 
                        df = pd.read_excel(file)
                    
                    # Cleanup: Drop completely empty rows/cols
                    df = df.dropna(how='all').dropna(axis=1, how='all')
                    
                    st.write("Preview of original file (Ready to Save):", df.head(3))
                    
                    # Direct Save Button
                    if st.button(f"☁️ Save '{file.name}' to Database", key=f"save_{file.name}"):
                        # Pass the RAW dataframe to the backend.
                        # It will save the columns exactly as they are in the file.
                        dm.save_products_dynamic(df, cat_sel, st.session_state['user'])
                        st.success(f"Successfully saved {len(df)} rows to category '{cat_sel}'!")
                        
                        # Wait briefly then reload
                        time.sleep(1)
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"Error processing file: {e}")

    # =======================================================
    # 3. DATA UPDATE
    # =======================================================
    elif menu == "Data Update":
        st.header("🔄 Update Existing Category")
        st.info("Upload a new file to identify changes, new items, and EOL items.")
        
        cats = dm.get_categories()
        cat_sel = st.selectbox("Category to Update", cats)
        
        up_file = st.file_uploader("Upload New Pricebook")
        
        if up_file:
            if up_file.name.endswith('csv'): df = pd.read_csv(up_file)
            else: df = pd.read_excel(up_file)
            
            target_columns = dm.get_schema()
            
            st.subheader("Map Columns for Update")
            mapping = {}
            cols = st.columns(3)
            file_cols = ["(Skip)"] + list(df.columns)
            
            for i, target_col in enumerate(target_columns):
                match_found = None
                if target_col in df.columns: match_found = target_col
                if not match_found:
                    fuzzy_guess = find_best_match(target_col, list(df.columns))
                    if fuzzy_guess: match_found = fuzzy_guess
                
                default_idx = 0
                if match_found: default_idx = file_cols.index(match_found)

                with cols[i % 3]:
                    selected_col = st.selectbox(
                        f"Target: **{target_col}**", file_cols, index=default_idx, key=f"up_{target_col}")
                    if selected_col != "(Skip)":
                        mapping[target_col] = selected_col

            key_col = st.selectbox("Which target column is the Unique ID?", target_columns)

            if st.button("Analyze Differences & Update"):
                new_data = {}
                for target, source in mapping.items():
                    new_data[target] = df[source]
                clean_df = pd.DataFrame(new_data)
                
                if key_col not in clean_df.columns:
                    st.error(f"You must map the Key Column: {key_col}")
                else:
                    res = dm.update_products_dynamic(clean_df, cat_sel, st.session_state['user'], key_col)
                    if "error" in res:
                        st.error(res["error"])
                    else:
                        st.success(f"Update Complete! New Items: {res['new']}, Marked EOL: {res['eol']}")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()
