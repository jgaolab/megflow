
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import streamlit as st
from streamlit.components.v1 import html
from reports.utils import in_docker
from pathlib import Path
import re

# Set page configuration
st.set_page_config(
    page_title="NextFlow Reports",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Determine default directory
if in_docker():
    DEFAULT_NX_REPORT_DIR = Path("/output")
else:
    dataset_path = st.session_state.get("dataset_report_path", "./output")
    DEFAULT_NX_REPORT_DIR = Path(dataset_path) if dataset_path else Path("./output")

# Sidebar input for report directory
nx_file_path = Path(st.sidebar.text_input(
    "NextFlow Resource Report Directory:",
    value=str(DEFAULT_NX_REPORT_DIR),
    help="Enter the path to the directory containing NextFlow report files"
))

# Validate directory exists
if not nx_file_path.exists():
    st.error(f"❌ Directory not found: `{nx_file_path}`")
    st.info("Please enter a valid directory path in the sidebar.")
    st.stop()

if not nx_file_path.is_dir():
    st.error(f"❌ Path is not a directory: `{nx_file_path}`")
    st.stop()


def fix_html_navigation(html_content):
    """
    Fix HTML content to prevent navigation issues in iframe.
    Ensures all links open within the same iframe context.
    """
    # Add base target to keep navigation within iframe
    if '<head>' in html_content:
        base_tag = '<base target="_self">'
        html_content = html_content.replace('<head>', f'<head>{base_tag}')
    
    # Fix anchor links to work within iframe
    html_content = re.sub(
        r'href="#',
        r'href="javascript:void(0);" onclick="document.getElementById(\'',
        html_content
    )
    
    # Ensure CSS and JS paths are absolute or inline
    # This prevents relative path issues
    
    return html_content


def render_report_iframe(report_file, height=4500):
    """
    Render HTML report with proper iframe configuration.
    """
    try:
        with open(report_file, "r", encoding="utf-8") as file:
            html_content = file.read()
        
        # Fix navigation issues
        html_content = fix_html_navigation(html_content)
        
        # Display file info
        file_size = report_file.stat().st_size / 1024  # KB
        st.caption(f"📄 File size: {file_size:.2f} KB")
        
        # Render with scrolling enabled
        html(html_content, height=height, scrolling=True)
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error reading file: {str(e)}")
        return False


# Define report configurations
reports = [
    {
        "name": "Resource Report",
        "file": nx_file_path / "report.html",
        "description": "CPU, memory, and I/O usage statistics",
        "height": 4500
    },
    {
        "name": "Timeline Report",
        "file": nx_file_path / "timeline.html",
        "description": "Process execution timeline and dependencies",
        "height": 4500
    }
]

# Display reports
st.title("🔬 NextFlow Execution Reports")
st.markdown(f"**Report Directory:** `{nx_file_path}`")
st.markdown("---")

# Sidebar options
with st.sidebar:
    st.markdown("---")
    st.markdown("### ⚙️ Display Options")
    
    display_mode = st.radio(
        "View Mode:",
        ["Tabs", "Stacked"],
        help="Choose how to display multiple reports"
    )
    
    iframe_height = st.slider(
        "Report Height (px):",
        min_value=1000,
        max_value=8000,
        value=4500,
        step=500,
        help="Adjust iframe height for better viewing"
    )
    
    st.markdown("---")
    st.markdown("### 📊 Available Reports")
    for report in reports:
        status = "✅" if report["file"].exists() else "❌"
        st.markdown(f"{status} {report['name']}")

# Update heights based on slider
for report in reports:
    report["height"] = iframe_height

# Display based on selected mode
if display_mode == "Tabs":
    # Tab-based display
    available_reports = [r for r in reports if r["file"].exists()]
    
    if not available_reports:
        st.warning("⚠️ No report files found in the specified directory.")
        st.stop()
    
    tab_names = [report["name"] for report in available_reports]
    tabs = st.tabs(tab_names)
    
    for tab, report in zip(tabs, available_reports):
        with tab:
            st.subheader(report["name"])
            st.caption(report["description"])
            render_report_iframe(report["file"], report["height"])

else:
    # Stacked display
    for report in reports:
        if not report["file"].exists():
            st.warning(f"⚠️ {report['name']} not found: `{report['file'].name}`")
            continue
        
        st.subheader(report["name"])
        st.caption(report["description"])
        
        with st.expander(f"View {report['name']}", expanded=True):
            render_report_iframe(report["file"], report["height"])
        
        st.markdown("---")

# Add download option
st.markdown("---")
st.markdown("### 💾 Download Reports")

col1, col2 = st.columns(2)

for idx, report in enumerate(reports):
    col = col1 if idx == 0 else col2
    with col:
        if report["file"].exists():
            with open(report["file"], "rb") as file:
                st.download_button(
                    label=f"📥 {report['name']}",
                    data=file,
                    file_name=report["file"].name,
                    mime="text/html"
                )
