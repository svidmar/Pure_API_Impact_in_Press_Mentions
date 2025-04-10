import streamlit as st
import pandas as pd
import requests
import datetime
import re
import time
import csv
from bs4 import BeautifulSoup
from io import StringIO

# --- Page Config ---
st.set_page_config(page_title="Screening Tool – Societal Impact in Pure Press Mentions", layout="wide")
st.title("Screening Tool – Societal Impact in Pure Press Mentions")

# --- Constants ---
KEYWORD_FILE = "impact_keywords_final_da.csv"


st.markdown("""
This tool helps identify press clippings in Pure that *may* indicate societal impact by searching for relevant trigger words in titles and descriptions, and by checking for links to related research projects and publications. It highlights mentions that might be connected to impactful research, surfacing potential candidates for closer review.
 

**How it works:**
1. Enter a Pure instance domain.
2. Enter a Pure API key with access to the Press/Media WS endpoint. The API key is only used during the active session and is not stored.
3. Choose a start date — the app will fetch all press clippings from that date to today.
4. Use predefined danish impact keywords (loaded from file), and/or
5. Optionally, add extra keywords manually.
6. Click **Search** to find clippings with the chosen trigger words/phrases

**About the impact score:**
Each clipping is given a score from 1 to 3, based on how many potential impact indicators are present:
- The title mentions one or more impact-related keywords (1/3)
- The description also contains impact-related keywords (2/3)
- The clipping is also related to projects or publications in Pure (3/3)


**Tip:** You can download your filtered results as a CSV file.

**Disclaimer:** This is only a support tool. Press mentions are just one possible — and often incomplete — indication of societal impact. The results should not be seen as definitive evidence, but as a starting point for further qualitative assessment.

""")

# --- Helper Functions ---
def get_clippings(api_key, start_date):
    headers = {"Accept": "application/json", "api-key": api_key}
    size = 100
    offset = 0
    results = []
    progress_text = st.empty()

    while True:
        params = {
            "order": "created",
            "orderBy": "descending",
            "size": size,
            "offset": offset,
            "locale": "da_DK"
        }
        try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.get(API_BASE_URL, headers=headers, params=params)
                    if response.status_code == 500:
                        st.warning(f"Server error (500) on attempt {attempt + 1}. Retrying...")
                        time.sleep(2)
                        continue
                    break  # Exit retry loop on success or non-500 status
                except requests.exceptions.RequestException as e:
                    st.error(f"Network error while fetching data: {e}")
                    return results
            else:
                st.error("Maximum retry attempts reached. Unable to fetch data.")
                return results
        except requests.exceptions.RequestException as e:
            st.error(f"Network error while fetching data: {e}")
            return results

        if response.status_code == 401:
            st.error("Unauthorized access. Please check if your API key is correct and active.")
            return []
        elif response.status_code == 500:
            st.error("Server error (500). Try again later or reduce the number of clippings requested.")
            return results
        elif response.status_code != 200:
            st.error(f"API error {response.status_code}: {response.reason}")
            return []

        data = response.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            created_date = item.get("info", {}).get("createdDate", "")[:10]
            if created_date >= start_date:
                results.append(item)
            else:
                return results

        offset += size
        progress_text.text(f"Fetched {len(results)} clippings so far...")
        time.sleep(0.34)

    progress_text.empty()
    return results

def match_impact_keywords(text, keywords):
    matches = []
    for word in keywords:
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            matches.append(word)
    return matches

def extract_description(item):
    descriptions = item.get("descriptions", [])
    for d in descriptions:
        for t in d.get("value", {}).get("text", []):
            if t.get("locale") == "da_DK":
                full_text = BeautifulSoup(t.get("value", ""), "html.parser").get_text()
                return full_text.split("(Resumé leveret af Infomedia)")[0].strip()
    return ""

def extract_text_from_field(field):
    return field.get("text", [{}])[0].get("value", "") if field else ""

def highlight_keywords(text, keywords):
    for word in keywords:
        text = re.sub(rf"\b({re.escape(word)})\b", r"**\1**", text, flags=re.IGNORECASE)
    return text

# --- Input Section ---
default_domain = "vbn.aau.dk"
pure_domain = st.text_input("Enter your Pure domain (e.g., vbn.aau.dk):", value=default_domain)
api_key = st.text_input("Enter your Pure API key", type="password")
start_date = st.date_input("Select start date", datetime.date.today())

API_BASE_URL = f"https://{pure_domain}/ws/api/524/press-media"


# --- Load keywords from file ---
use_file_keywords = st.checkbox("Include keywords from file", value=True)

try:
    df_keywords = pd.read_csv(KEYWORD_FILE)
    file_keywords = df_keywords["phrase"].dropna().tolist()
except Exception as e:
    st.error(f"Error loading keyword file: {e}")
    file_keywords = []

if use_file_keywords:
    with st.expander("📂 View loaded keywords from file (click to expand)"):
        st.write(", ".join(file_keywords))
else:
    file_keywords = []

user_extra = st.text_area("Add extra impact keywords or phrases (comma-separated, Danish)")
extra_keywords = [w.strip() for w in user_extra.split(",") if w.strip()]
impact_keywords = file_keywords + extra_keywords

run_analysis = st.button("Search")

# --- Store and preserve results for filtering and sorting ---
if "clipping_results" not in st.session_state:
    st.session_state.clipping_results = []

if run_analysis and api_key and start_date:
    with st.spinner("Fetching press clippings..."):
        clippings = get_clippings(api_key, start_date.strftime("%Y-%m-%d"))

    export_data = []
    for clip in clippings:
        title = extract_text_from_field(clip.get("title"))
        uuid = clip.get("uuid")
        url = f"https://vbn.aau.dk/da/clippings/{uuid}"
        description = extract_description(clip)

        keyword_matches = match_impact_keywords(f"{title} {description}", impact_keywords)
        if not keyword_matches:
            continue

        related_projects = clip.get("relatedProjects", [])
        related_outputs = clip.get("relatedResearchOutputs", [])
        references = clip.get("references", [])
        reference_count = sum(1 for ref in references if ref.get("pureId"))

        score = 0
        if match_impact_keywords(title, impact_keywords):
            score += 1
        if match_impact_keywords(description, impact_keywords):
            score += 1
        if related_projects or related_outputs:
            score += 1

        projects_links = ", ".join([
            f"[{extract_text_from_field(p.get('name'))}](https://vbn.aau.dk/da/projects/{p.get('uuid')})"
            for p in related_projects
        ])
        publications_links = ", ".join([
            f"[{extract_text_from_field(p.get('name'))}](https://vbn.aau.dk/da/publications/{p.get('uuid')})"
            for p in related_outputs
        ])

        export_data.append({
            "UUID": uuid,
            "Title": title,
            "URL": url,
            "Keywords found": ", ".join(keyword_matches),
            "Description": description,
            "Impact score": score,
            "Reference count": reference_count,
            "Projects": projects_links,
            "Publications": publications_links
        })

    st.session_state.clipping_results = export_data

# --- Display and filter results ---
st.markdown("""
### Results
""")

if st.session_state.clipping_results:
    st.markdown(f"**Total results before filtering:** {len(st.session_state.clipping_results)}")
if st.session_state.clipping_results:
    st.subheader("Filter and Sort Results")
    only_with_projects = st.checkbox("Only show clippings with related projects")
    only_with_publications = st.checkbox("Only show clippings with related publications")
    keyword_filter = st.text_input("Only show results containing keyword (optional)").strip().lower()
    sort_by = st.selectbox("Sort by", ["Impact score (desc)", "Reference count (desc)", "Title (A-Z)"])

    filtered_data = []
    total_filtered = 0
    for item in st.session_state.clipping_results:
        if only_with_projects and not item["Projects"]:
            continue
        if only_with_publications and not item["Publications"]:
            continue
        if keyword_filter and keyword_filter not in item["Keywords found"].lower():
            continue
        filtered_data.append(item)
        total_filtered += 1

    if sort_by == "Impact score (desc)":
        filtered_data.sort(key=lambda x: x["Impact score"], reverse=True)
    elif sort_by == "Reference count (desc)":
        filtered_data.sort(key=lambda x: x["Reference count"], reverse=True)
    elif sort_by == "Title (A-Z)":
        filtered_data.sort(key=lambda x: x["Title"].lower())

    for clip in filtered_data:
        st.markdown(f"### [{clip['Title']}]({clip['URL']})")

        # UUID display with copy button
        st.markdown(f"""
        <div style='font-size: 0.8em; color: gray; margin-bottom: 5px;'>
            UUID: <code id="uuid-{clip['UUID']}">{clip['UUID']}</code>
            <button title="Copy to clipboard" onclick="navigator.clipboard.writeText('{clip['UUID']}')" style="margin-left: 5px; cursor: pointer;">📋</button>
        </div>
        """, unsafe_allow_html=True)


        bolded = ', '.join([f"**{kw.strip()}**" for kw in clip['Keywords found'].split(",")])
        st.markdown(f"**Impact keywords found**: {bolded}")

        score = clip["Impact score"]
        score_label = "🟢" if score == 3 else "🟡" if score == 2 else "🟠"
        st.markdown(f"**Estimated impact score:** {score_label} {score} / 3")

        st.markdown(f"**Reference count:** {clip['Reference count']}")
        st.markdown("**Description:**")
        st.markdown(highlight_keywords(clip['Description'], impact_keywords))

        if clip['Projects']:
            st.markdown("**Related projects:**")
            st.markdown(clip['Projects'], unsafe_allow_html=True)
        if clip['Publications']:
            st.markdown("**Related publications:**")
            st.markdown(clip['Publications'], unsafe_allow_html=True)

        st.markdown("---")

    st.markdown(f"**Results after filtering:** {total_filtered}")

    if filtered_data:
        csv_buffer = StringIO()
        keys = filtered_data[0].keys()
        dict_writer = csv.DictWriter(csv_buffer, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(filtered_data)
        csv_data = csv_buffer.getvalue().encode("utf-8")
        st.download_button(
            label="Download results as CSV",
            data=csv_data,
            file_name="press_clippings_with_impact.csv",
            mime="text/csv"
        )
    else:
        st.info("No results to display based on the current filters.")

elif run_analysis:
    st.warning("Please enter your Pure API key and choose a start date.")
