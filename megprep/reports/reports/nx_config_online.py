
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nextflow Configuration Editor
A Streamlit application for editing Nextflow configuration files with syntax highlighting.
"""

import streamlit as st
from streamlit_ace import st_ace
from reports.utils import in_docker
from pathlib import Path


# ============================================================================
# File Operations
# ============================================================================

def load_nextflow_conf(file_path):
    """
    Load and return the content of a Nextflow configuration file.
    
    Args:
        file_path (Path): Path to the configuration file
        
    Returns:
        str: Content of the configuration file
        
    Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If the file cannot be read
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return content
    except FileNotFoundError:
        st.error(f"❌ Configuration file not found: {file_path}")
        raise
    except PermissionError:
        st.error(f"❌ Permission denied reading file: {file_path}")
        raise
    except Exception as e:
        st.error(f"❌ Error loading configuration: {str(e)}")
        raise


def save_nextflow_conf(file_path, content):
    """
    Save content to a Nextflow configuration file.
    
    Args:
        file_path (Path): Path to the configuration file
        content (str): Content to write to the file
        
    Raises:
        PermissionError: If the file cannot be written
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)
    except PermissionError:
        st.error(f"❌ Permission denied writing to file: {file_path}")
        raise
    except Exception as e:
        st.error(f"❌ Error saving configuration: {str(e)}")
        raise


def validate_file_path(file_path):
    """
    Validate if the file path exists and is accessible.
    
    Args:
        file_path (Path): Path to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not file_path.exists():
        return False
    if not file_path.is_file():
        st.warning(f"⚠️ Path exists but is not a file: {file_path}")
        return False
    return True


# ============================================================================
# Main Application
# ============================================================================

def main():
    """Main application function."""
    
    # Page configuration
    st.set_page_config(
        page_title="Nextflow Config Editor",
        page_icon="⚙️",
        layout="wide"
    )
    
    # Initialize session state
    if 'config_content' not in st.session_state:
        st.session_state.config_content = None
    if 'file_loaded' not in st.session_state:
        st.session_state.file_loaded = False
    
    # Header
    st.title("⚙️ Nextflow Configuration Editor")
    st.markdown("---")
    
    # Determine default configuration file path
    if in_docker():
        default_config_path = Path("/output") / "nextflow.config"
    else:
        dataset_path = st.session_state.get("dataset_report_path", ".")
        default_config_path = Path(dataset_path) / "nextflow.config"
    
    # Sidebar - File Selection
    with st.sidebar:
        st.header("📁 File Configuration")
        
        config_file_path = Path(st.text_input(
            "Configuration File Path:",
            value=str(default_config_path),
            help="Enter the path to your nextflow.config file"
        ))
        
        st.markdown("---")
        
        # File information
        if config_file_path.exists():
            st.success("✅ File found")
            file_stats = config_file_path.stat()
            st.info(f"**Size:** {file_stats.st_size:,} bytes")
        else:
            st.warning("⚠️ File not found")
            if st.button("Create New File"):
                try:
                    config_file_path.parent.mkdir(parents=True, exist_ok=True)
                    config_file_path.write_text("// New Nextflow Configuration\n", encoding='utf-8')
                    st.success("✅ New file created!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to create file: {str(e)}")
        
        st.markdown("---")
        
        # Editor settings
        st.header("🎨 Editor Settings")
        
        editor_theme = st.selectbox(
            "Theme:",
            options=['chaos', 'monokai', 'github', 'tomorrow', 'twilight', 'solarized_dark', 'solarized_light'],
            index=0
        )
        
        editor_height = st.slider(
            "Editor Height (px):",
            min_value=400,
            max_value=1200,
            value=800,
            step=50
        )
        
        keybinding = st.selectbox(
            "Keybinding:",
            options=['vscode', 'vim', 'emacs', 'sublime'],
            index=0
        )
    
    # Main content area
    if not validate_file_path(config_file_path):
        st.warning("⚠️ Please provide a valid configuration file path in the sidebar.")
        st.info("💡 **Tip:** You can create a new file using the sidebar button if the file doesn't exist.")
        return
    
    # Load configuration
    try:
        if st.session_state.config_content is None or not st.session_state.file_loaded:
            config_content = load_nextflow_conf(config_file_path)
            st.session_state.config_content = config_content
            st.session_state.file_loaded = True
        else:
            config_content = st.session_state.config_content
    except Exception:
        return
    
    # Editor section
    st.subheader("📝 Configuration Editor")
    
    # ACE editor
    edited_content = st_ace(
        language='hjson',
        value=config_content.strip(),
        auto_update=True,
        keybinding=keybinding,
        theme=editor_theme,
        height=editor_height,
        font_size=14,
        show_gutter=True,
        show_print_margin=False,
        wrap=True,
        readonly=False
    )
    
    # Update session state
    st.session_state.config_content = edited_content
    
    st.markdown("---")
    
    # Action buttons
    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
    
    with col1:
        if st.button("💾 Save Configuration", use_container_width=True, type="primary"):
            try:
                save_nextflow_conf(config_file_path, edited_content)
                st.success("✅ Configuration saved successfully!")
            except Exception:
                pass  # Error already displayed by save function
    
    with col2:
        if st.button("🔄 Reload from File", use_container_width=True):
            try:
                reloaded_content = load_nextflow_conf(config_file_path)
                st.session_state.config_content = reloaded_content
                st.info("ℹ️ Configuration reloaded from file.")
                st.rerun()
            except Exception:
                pass  # Error already displayed by load function
    
    with col3:
        if st.button("↩️ Reset Changes", use_container_width=True):
            st.session_state.config_content = load_nextflow_conf(config_file_path)
            st.info("ℹ️ Changes reset to last saved version.")
            st.rerun()
    
    with col4:
        if edited_content:
            st.download_button(
                label="📥 Download Config",
                data=edited_content,
                file_name="nextflow.config",
                mime="text/plain",
                use_container_width=True
            )
    
    # Footer
    st.markdown("---")
    st.caption("💡 **Tip:** Changes are autosaved in the editor. Click 'Save Configuration' to write to file.")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    main()
