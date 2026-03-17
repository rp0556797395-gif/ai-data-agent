import streamlit as st
import pandas as pd
import google.generativeai as genai
import plotly.express as px
import os
import ssl
import json
import re
import time

# --- 1. פתרון שגיאות SSL וחסימות רשת ---
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['PYTHONHTTPSVERIFY'] = '0'
if not os.environ.get('PYTHONHTTPSVERIFY', '') == '0':
    ssl._create_default_https_context = ssl._create_unverified_context

# --- 2. חיבור ל-AI (Gemini) ---
API_KEY = "GOOGLE_API_KEY"
genai.configure(api_key=API_KEY, transport='rest')


def get_available_model():
    """מנגנון לגילוי דינמי של המודל הזמין"""
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m_name in models:
            if '1.5-flash' in m_name:
                return m_name
        return models[0] if models else 'models/gemini-1.5-flash'
    except Exception:
        return 'models/gemini-1.5-flash'


def call_gemini(prompt):
    """שליחת בקשה ל-AI עם מנגנון הגנה מפני עומס ומכסות"""
    target_model = get_available_model()
    model = genai.GenerativeModel(target_model)

    try:
        response = model.generate_content(prompt)
        if response and response.text:
            return response.text
        return ""
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "quota" in err_msg.lower():
            return "QUOTA_EXCEEDED"
        return f"Error: {err_msg}"


# --- 3. ממשק האפליקציה ---
st.set_page_config(page_title="AI Data Agent 🤖", layout="wide")

st.title("🤖 סוכן נתונים אינטליגנטי")
st.write("העלי קובץ, בחרי פעולה ותני ל-AI לנהל את הנתונים.")

# העלאת קובץ ראשי
uploaded_file = st.file_uploader("בחרי קובץ ראשי (CSV או Excel)", type=["csv", "xlsx"])

if uploaded_file is not None:
    if 'df' not in st.session_state:
        try:
            if uploaded_file.name.endswith('.csv'):
                df_init = pd.read_csv(uploaded_file, sep=None, engine='python', encoding='utf-8-sig')
            else:
                df_init = pd.read_excel(uploaded_file)
            # ניקוי עמודות ריקות שנוצרות לעיתים באקסל
            st.session_state.df = df_init.loc[:, ~df_init.columns.str.contains('^Unnamed', case=False)]
        except Exception as e:
            st.error(f"שגיאה בטעינת הקובץ: {e}")

    if 'df' in st.session_state:
        current_df = st.session_state.df
        st.subheader("📊 תצוגת נתונים מלאה")
        st.dataframe(current_df)
        st.markdown("---")

        col1, col2 = st.columns([1, 2])
        with col1:
            target_col = st.selectbox("בחרי עמודה לעבודה:", current_df.columns)
            action_type = st.radio("מה ברצונך לעשות?", [
                "ניתוח נתונים (Insights)",
                "סוכן AI (מחיקה חכמה)",
                "מיזוג עם קובץ נוסף (Merge)"
            ])

        with col2:
            # --- ניתוח נתונים ---
            if action_type == "ניתוח נתונים (Insights)":
                if st.button("נתח והצג גרף 📊"):
                    with st.spinner("הסוכן חושב..."):
                        chart_data = current_df[target_col].value_counts().head(10).reset_index()
                        chart_data.columns = [target_col, 'כמות']
                        fig = px.bar(chart_data, x=target_col, y='כמות', color='כמות', title=f"התפלגות: {target_col}")
                        st.plotly_chart(fig, use_container_width=True)

                        prompt = f"Analyze these stats for {target_col}: {chart_data.to_string()}. Summarize in 2 Hebrew sentences."
                        res = call_gemini(prompt)
                        if res == "QUOTA_EXCEEDED":
                            st.warning(
                                "המכסה היומית של ה-AI הסתיימה. הגרף מוצג, אך לא ניתן להפיק תובנות טקסטואליות כרגע.")
                        else:
                            st.info(res)

            # --- מחיקה חכמה ---
            elif action_type == "סוכן AI (מחיקה חכמה)":
                user_query = st.text_input("מה למחוק? (למשל: 'שורות של לקוחות לא פעילים')")
                if st.button("בצע מחיקה ✨"):
                    with st.spinner("מעבד..."):
                        # שולחים רק דגימה כדי לחסוך במשאבים
                        unique_vals = current_df[target_col].dropna().unique().tolist()[:50]
                        prompt = f"From this list: {unique_vals}, which items match criteria: '{user_query}'? Return ONLY a JSON list of strings like [\"val1\", \"val2\"]."
                        res_text = call_gemini(prompt)

                        if res_text == "QUOTA_EXCEEDED":
                            st.error("מכסת ה-AI הסתיימה להיום. לא ניתן לבצע מחיקה חכמה כרגע.")
                        else:
                            try:
                                json_match = re.search(r'\[.*\]', res_text, re.DOTALL)
                                if json_match:
                                    to_delete = json.loads(json_match.group(0))
                                    if to_delete:
                                        st.session_state.df = current_df[
                                            ~current_df[target_col].astype(str).isin([str(x) for x in to_delete])]
                                        st.success(f"בוצע! נמחקו ערכים התואמים לחיפוש.")
                                        st.rerun()
                                    else:
                                        st.info("לא נמצאו פריטים שתואמים לתיאור שלך.")
                                else:
                                    st.error("ה-AI לא הצליח להחזיר רשימה תקינה.")
                            except Exception:
                                st.error("שגיאה בעיבוד התשובה מהשרת.")

            # --- מיזוג קבצים ---
            elif action_type == "מיזוג עם קובץ נוסף (Merge)":
                st.info("בחרת באפשרות מיזוג. העלי את הקובץ השני לחיבור.")
                second_file = st.file_uploader("העלי קובץ שני", type=["csv", "xlsx"], key="merge_file")

                if second_file:
                    try:
                        if second_file.name.endswith('.csv'):
                            df2 = pd.read_csv(second_file, sep=None, engine='python', encoding='utf-8-sig')
                        else:
                            df2 = pd.read_excel(second_file)

                        st.write("בחרי עמודות לחיבור (Key):")
                        col_m1 = st.selectbox("עמודה בקובץ הראשי:", current_df.columns)
                        col_m2 = st.selectbox("עמודה בקובץ השני:", df2.columns)

                        if st.button("מזג קבצים עכשיו 🤝"):
                            # פעולת המיזוג לא דורשת AI ולכן תמיד תעבוד!
                            merged_df = pd.merge(current_df, df2, left_on=col_m1, right_on=col_m2, how='left')
                            st.session_state.df = merged_df
                            st.success("המיזוג בוצע בהצלחה!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"שגיאה בטעינת הקובץ השני: {e}")

        st.markdown("---")
        st.subheader("📋 הטבלה המעודכנת")
        st.dataframe(st.session_state.df)
        csv = st.session_state.df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 הורדת קובץ סופי", data=csv, file_name="final_data.csv")
