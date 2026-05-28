# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import streamlit as st

# --- Professional CSS Styling ---
st.markdown("""
    <style>
    /* Global Typography */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        color: #1E293B;
    }

    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #F8FAFC;
        border-right: 1px solid #E2E8F0;
    }

    /* Header Styling */
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #0F172A;
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 1rem;
    }

    .header-icon {
        color: #3B82F6; /* Blue-500 */
    }



    .desc-text {
        font-size: 1.05rem;
        line-height: 1.6;
        color: #475569;
    }

    .section-label {
        text-transform: uppercase;
        font-size: 0.75rem;
        font-weight: 700;
        color: #94A3B8;
        letter-spacing: 0.05em;
        margin-bottom: 0.5rem;
        display: block;
    }
    
    /* Badge/Tag Styling */
    .highlight-badge {
        display: inline-flex;
        align-items: center;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.85rem;
        font-weight: 500;
        margin-right: 8px;
        margin-bottom: 8px;
        background-color: #EFF6FF; /* Blue-50 */
        color: #2563EB; /* Blue-600 */
        border: 1px solid #BFDBFE;
    }
    
    .highlight-badge:hover {
        background-color: #DBEAFE;
    }

 /* Link Card Styling for Sidebar */
    .link-card {
        display: flex;
        align-items: center;
        padding: 10px 12px;
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        margin-bottom: 8px;
        text-decoration: none;
        transition: all 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    
    .link-card:hover {
        background-color: #F1F5F9;
        border-color: #CBD5E1;
        transform: translateY(-1px);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }

    .link-text {
        font-weight: 600;
        color: #334155;
        font-size: 0.9rem;
    }
    
    /* Icon Styling in Link Card */
    .link-icon-svg {
        width: 20px;
        height: 20px;
        margin-right: 12px;
        fill: #334155; /* Slate-700 */
        transition: fill 0.2s;
    }
    
    .link-card:hover .link-icon-svg {
        fill: #0F172A; /* Slate-900 (Darker on hover) */
    }

    
    </style>
    """, unsafe_allow_html=True)
current_dir = os.path.dirname(os.path.abspath(__file__))

# --- 3. Content Data (Enriched with Icons) ---
CONTENT_MAP = {
    "Preprocessing": {
        "icon": "",
        "title": "Preprocessing",
        "video": os.path.join(current_dir, 'assets', '1.preproc.mp4'),
        "desc": "Interactive raw data inspection with real-time filtering capabilities. Dynamically adjust channel density and time windows to view specific segments, while editing artifact annotations.",
        "highlights": ["Real-time Filtering", "Waveform Inspection", "Artifact Annotation"]
    },
    "Artifacts - QuickCheck": {
        "icon": "",
        "title": "Artifact Detection & QuickCheck",
        "video": os.path.join(current_dir, 'assets', '2.artifact.mp4'),
        "desc": "A streamlined interface designed for rapid identification and marking of bad channels and segments, significantly accelerating the artifact annotation and recording process.",
        "highlights": ["Rapid Marking", "Edit bad channels and segments"]
    },
    "ICA": {
        "icon": "",
        "title": "Independent Component Analysis",
        "video": os.path.join(current_dir, 'assets', '3.ica.mp4'),
        "desc": "Interactive management of Independent Components (ICs). Review automatically flagged artifact components and manually select or deselect specific ICs for exclusion from the data.",
        "highlights": ["Component Review", "Artefact IC Auto-labeling"]
    },
    "Source Localization": {
        "icon": "🧠",
        "title": "Source Estimation",
        "video": os.path.join(current_dir, 'assets', '4.source.mp4'),
        "desc": "Interactive exploration of source estimation results. Visualize brain activity across specific timepoints and anatomical regions, with granular control over plotting parameters and thresholds.",
        "highlights": ["Timing Navigation", "Hemisphere layout selection", "Plot Controls"]
    },
}

# --- 4. Sidebar Logic ---
with st.sidebar:
    st.markdown("### 🧭 User Guide")
    st.info("Select a module below to watch the interactive walkthrough.")

    # Custom CSS styled radio button
    selected_module = st.radio(
        "Modules",
        options=CONTENT_MAP.keys(),
        label_visibility="collapsed"
    )

    st.markdown("---")
        # Github Link
    st.markdown("""
    <a href="https://github.com/LiaoPan/megprep" target="_blank" style="text-decoration: none;">
        <div class="link-card">
            <!-- GitHub SVG Icon -->
            <svg class="link-icon-svg" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.419-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>
            </svg>
            <span class="link-text">GitHub Repository</span>
    </a>
    """, unsafe_allow_html=True)

    # ReadTheDocs Link
    st.markdown("""
    <a href="https://megprep.readthedocs.io/en/latest/" target="_blank" style="text-decoration: none;">
        <div class="link-card">
            <!-- Solid 'Chrome Reader Mode' Icon - Matches visual weight of GitHub icon -->
            <svg class="link-icon-svg" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <!-- Outer Frame + Sidebar (Left) + Lines (Right) in one solid fill path -->
                <path d="M21 4H3c-1.1 0-2 .9-2 2v13c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zM9 19H3V6h6v13zm12 0h-10V6h10v13z M14 9.5h6v-1.5h-6v1.5zm0 2.5h6v-1.5h-6v1.5zm0 2.5h6v-1.5h-6v1.5z"/>
            </svg>
            <span class="link-text">Documentation</span>
        </div>
    </a>
    """, unsafe_allow_html=True)


# --- 5. Main Content Renderer ---

data = CONTENT_MAP[selected_module]

# 5.1 Header Section
st.markdown(f"""
    <div class="main-header">
        <span class="header-icon">{data['icon']}</span>
        {data['title']}
    </div>
""", unsafe_allow_html=True)

# 5.2 Video Section (Cinema Mode)
try:
    st.video(data["video"])
except Exception as e:
    st.error(f"Video source unavailable: {data['video']}")
st.markdown('</div>', unsafe_allow_html=True)

# Info Section
st.markdown('<span class="section-label">Description</span>', unsafe_allow_html=True)
st.markdown(f'<div class="desc-text">{data["desc"]}</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<span class="section-label">Key Features</span>', unsafe_allow_html=True)

# Render badges
badges_html = ""
for highlight in data["highlights"]:
    badges_html += f'<span class="highlight-badge">{highlight}</span>'

st.markdown(f'<div>{badges_html}</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# --- 6. Subtle Footer ---
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("""
    <div style="text-align: center; color: #94A3B8; font-size: 0.8rem;">
        MegPrep Analytics Platform • Interactive Documentation
    </div>
""", unsafe_allow_html=True)
