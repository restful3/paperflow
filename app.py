"""
PaperFlow Streamlit Viewer
A web interface for viewing converted academic papers in Korean and English
"""

import streamlit as st
import os
import base64
from pathlib import Path
from streamlit_pdf_viewer import pdf_viewer


# Page configuration
st.set_page_config(
    page_title="PaperFlow Viewer",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for beautiful UI
st.markdown("""
<style>
    /* Remove Streamlit default padding */
    .main .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0rem !important;
    }

    /* Main title styling */
    h1 {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 800;
        letter-spacing: -0.5px;
    }

    /* Card container styling */
    .paper-card {
        background: white;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.06);
        border: 1px solid rgba(0, 0, 0, 0.05);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        height: 100%;
        margin-bottom: 12px;
    }

    .paper-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 16px rgba(102, 126, 234, 0.12);
        border-color: rgba(102, 126, 234, 0.2);
    }

    /* Paper title styling */
    .paper-title {
        color: #1a202c;
        font-size: 0.95rem;
        font-weight: 600;
        margin-bottom: 8px;
        line-height: 1.3;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Format badge styling */
    .format-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.65rem;
        font-weight: 600;
        margin-right: 4px;
        margin-bottom: 4px;
    }

    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
        font-size: 0.85rem;
        transition: all 0.3s ease;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.25);
    }

    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.35);
    }

    /* Info box styling */
    .stAlert {
        border-radius: 12px;
        border-left: 4px solid #667eea;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background-color: #f7fafc;
        border-radius: 12px 12px 0 0;
        padding: 12px 24px;
        font-weight: 600;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
    }

    /* Download button styling */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
        border-radius: 10px;
        font-weight: 600;
    }

    /* Divider styling */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(90deg, transparent, #667eea, transparent);
        margin: 2rem 0;
    }

    /* Paper count badge */
    .paper-count {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 8px 20px;
        border-radius: 24px;
        font-weight: 700;
        display: inline-block;
        margin-bottom: 24px;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.25);
    }

    /* Refresh button special styling */
    div[data-testid="column"]:last-child .stButton > button {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    }
</style>
""", unsafe_allow_html=True)


# Initialize session state
if 'selected_paper' not in st.session_state:
    st.session_state.selected_paper = None
if 'view' not in st.session_state:
    st.session_state.view = 'list'
if 'selected_format' not in st.session_state:
    st.session_state.selected_format = None
if 'html_font_size' not in st.session_state:
    st.session_state.html_font_size = 100
if 'split_ratio' not in st.session_state:
    st.session_state.split_ratio = 50  # HTML 비율 (기본 50%)


def get_paper_list():
    """
    Scan the outputs directory and return list of paper folders.
    Returns list of tuples: (folder_name, folder_path)
    """
    outputs_dir = Path("outputs")

    if not outputs_dir.exists():
        return []

    papers = []
    for item in outputs_dir.iterdir():
        if item.is_dir():
            papers.append((item.name, str(item)))

    # Sort alphabetically
    papers.sort(key=lambda x: x[0])
    return papers


def get_paper_files(paper_path):
    """
    Get available files for a paper.
    Returns dict with 'html', 'pdf', 'md_ko', 'md_en' keys
    """
    paper_dir = Path(paper_path)
    files = {
        'html': None,
        'pdf': None,
        'md_ko': None,
        'md_en': None
    }

    for file in paper_dir.iterdir():
        if file.is_file():
            if file.name.endswith('_ko.html'):
                files['html'] = str(file)
            elif file.name.endswith('.pdf'):
                files['pdf'] = str(file)
            elif file.name.endswith('_ko.md'):
                files['md_ko'] = str(file)
            elif file.name.endswith('.md') and not file.name.endswith('_ko.md'):
                files['md_en'] = str(file)

    return files


def display_html(html_path, font_size=100):
    """
    Display HTML file using iframe with injected CSS to hide TOC and headers
    Args:
        html_path: Path to HTML file
        font_size: Font size percentage (default 100)
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Add CSS to hide TOC, headers, and top padding, plus adjustable font size
        custom_css = f"""
        <style>
            /* Adjustable font size */
            body, #quarto-content, .content, #quarto-document-content, p, div, span, li, td, th {{
                font-size: {font_size}% !important;
            }}
            /* Hide TOC sidebar */
            #TOC, .sidebar, nav#TOC, #quarto-sidebar, .quarto-sidebar-toggle-contents {{
                display: none !important;
            }}
            /* Hide title block */
            .quarto-title-block, header.quarto-title-block, header#title-block-header {{
                display: none !important;
            }}
            /* Remove top padding/margin */
            body, #quarto-content, main, .main, #quarto-document-content {{
                margin-top: 0 !important;
                padding-top: 0 !important;
            }}
            /* Adjust content to full width with minimal padding */
            body, #quarto-content, .content, #quarto-document-content, main, .main {{
                max-width: 100% !important;
                margin-left: 0 !important;
                margin-right: 0 !important;
                padding-left: 0.5em !important;
                padding-right: 0.5em !important;
            }}
            /* Container full width */
            .container, .container-fluid, article {{
                max-width: 100% !important;
                padding-left: 0.5em !important;
                padding-right: 0.5em !important;
            }}
            /* Remove any top margin from first element */
            body > *:first-child, main > *:first-child {{
                margin-top: 0 !important;
            }}
        </style>
        """

        # Insert custom CSS before closing head tag
        if '</head>' in html_content:
            html_content = html_content.replace('</head>', custom_css + '</head>')
        else:
            # If no head tag, add it at the beginning
            html_content = custom_css + html_content

        # Use st.components.v1.html with tall height for natural scrolling
        st.components.v1.html(html_content, height=3000, scrolling=True)

    except Exception as e:
        st.error(f"HTML 파일을 불러올 수 없습니다: {str(e)}")

    return html_content if 'html_content' in locals() else None


def display_pdf(pdf_path):
    """
    Display PDF file using streamlit-pdf-viewer with very tall height
    """
    try:
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        # Display PDF with very tall height to minimize internal scrolling
        # User can scroll the page naturally
        pdf_viewer(
            pdf_bytes,
            width=900,
            height=3000,  # Very tall to show more content
            render_text=True
        )

    except Exception as e:
        st.error(f"PDF 파일을 불러올 수 없습니다: {str(e)}")
        pdf_bytes = None

    return pdf_bytes if 'pdf_bytes' in locals() else None


def display_markdown(md_path):
    """
    Display markdown file
    """
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        st.markdown(md_content, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"마크다운 파일을 불러올 수 없습니다: {str(e)}")


def render_paper_list():
    """
    Render the home screen with list of papers
    """
    # Header with refresh button
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("📚 PaperFlow Viewer")
    with col2:
        if st.button("🔄 새로고침", use_container_width=True):
            st.rerun()

    st.markdown("### 변환된 논문 목록")
    st.markdown("---")

    papers = get_paper_list()

    if not papers:
        st.info("📂 `outputs/` 디렉토리에 논문이 없습니다.")
        st.markdown("**사용 방법:**")
        st.code("./run_batch_venv.sh", language="bash")
        return

    # Paper count badge
    st.markdown(f'<div class="paper-count">📚 총 {len(papers)}개의 논문</div>', unsafe_allow_html=True)

    # Display papers in a grid using columns (3 per row for compact view)
    cols_per_row = 3
    for i in range(0, len(papers), cols_per_row):
        cols = st.columns(cols_per_row, gap="medium")

        for j in range(cols_per_row):
            idx = i + j
            if idx < len(papers):
                paper_name, paper_path = papers[idx]

                with cols[j]:
                    # Check available formats
                    files = get_paper_files(paper_path)
                    formats_html = []
                    if files['html']:
                        formats_html.append('<span class="format-badge">🇰🇷 한국어</span>')
                    if files['pdf']:
                        formats_html.append('<span class="format-badge">🇬🇧 English</span>')

                    # Create a beautiful card using HTML
                    card_html = f'''
                    <div class="paper-card">
                        <div class="paper-title">📄 {paper_name}</div>
                        <div style="margin-bottom: 8px;">
                            {''.join(formats_html)}
                        </div>
                    </div>
                    '''
                    st.markdown(card_html, unsafe_allow_html=True)

                    # View button (more compact)
                    if st.button("📖 보기", key=f"view_{idx}", use_container_width=True):
                        st.session_state.selected_paper = paper_path
                        st.session_state.view = 'detail'
                        st.rerun()


def render_paper_detail():
    """
    Render the detail screen for a selected paper
    """
    paper_path = st.session_state.selected_paper
    paper_name = os.path.basename(paper_path)

    # Get available files
    files = get_paper_files(paper_path)

    # Build format options
    format_options = {}

    if files['html']:
        format_options['🇰🇷 한국어 (HTML)'] = ('html', files['html'])

    if files['pdf']:
        format_options['🇬🇧 영어 (PDF)'] = ('pdf', files['pdf'])
    elif files['md_en']:
        format_options['🇬🇧 영어 (Markdown)'] = ('md_en', files['md_en'])

    if not format_options:
        st.error("표시할 파일이 없습니다.")
        return

    # Sidebar for navigation and format selection
    with st.sidebar:
        st.markdown("### 📄 논문 뷰어")

        # Back to list button
        if st.button("⬅️ 목록으로 돌아가기", use_container_width=True):
            st.session_state.view = 'list'
            st.session_state.selected_paper = None
            st.session_state.selected_format = None
            st.rerun()

        st.markdown("---")
        st.markdown(f"**현재 논문:**")
        st.info(paper_name)

        st.markdown("---")
        st.markdown("**보기 형식 선택:**")

        # Radio buttons for format selection
        format_names = list(format_options.keys())

        # Add "둘다 보기" option if both HTML and PDF are available
        if files['html'] and files['pdf']:
            format_names.append("🔄 둘다 보기 (한국어 + 영어)")

        # Initialize selected format if not set
        if st.session_state.selected_format is None:
            st.session_state.selected_format = format_names[0]

        selected_format_name = st.radio(
            "형식",
            format_names,
            index=format_names.index(st.session_state.selected_format) if st.session_state.selected_format in format_names else 0,
            label_visibility="collapsed"
        )

        st.session_state.selected_format = selected_format_name

        # Font size control - only show for HTML-containing formats
        if selected_format_name in ["🇰🇷 한국어 (HTML)", "🔄 둘다 보기 (한국어 + 영어)"]:
            st.markdown("---")
            st.markdown("**📏 글자 크기:**")

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                if st.button("➖ 작게", use_container_width=True, key="font_decrease"):
                    if st.session_state.html_font_size > 100:
                        st.session_state.html_font_size -= 2
                        st.rerun()
            with col2:
                st.markdown(f"<div style='text-align: center; padding: 8px; font-weight: bold;'>{st.session_state.html_font_size}%</div>",
                            unsafe_allow_html=True)
            with col3:
                if st.button("➕ 크게", use_container_width=True, key="font_increase"):
                    if st.session_state.html_font_size < 110:
                        st.session_state.html_font_size += 2
                        st.rerun()

        # Screen ratio control - only show for dual view mode
        if selected_format_name == "🔄 둘다 보기 (한국어 + 영어)":
            st.markdown("---")
            st.markdown("**📐 화면 비율:**")

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                if st.button("◀ 한국어", use_container_width=True, key="ratio_increase"):
                    if st.session_state.split_ratio < 80:
                        st.session_state.split_ratio += 10
                        st.rerun()
            with col2:
                html_ratio = st.session_state.split_ratio
                pdf_ratio = 100 - html_ratio
                st.markdown(f"<div style='text-align: center; padding: 8px; font-weight: bold;'>{html_ratio}:{pdf_ratio}</div>",
                            unsafe_allow_html=True)
            with col3:
                if st.button("영어 ▶", use_container_width=True, key="ratio_decrease"):
                    if st.session_state.split_ratio > 20:
                        st.session_state.split_ratio -= 10
                        st.rerun()

    # Main content area - display selected format directly without header
    # Check if "둘다 보기" mode is selected
    if selected_format_name == "🔄 둘다 보기 (한국어 + 영어)":
        # Split screen with adjustable ratio: Korean HTML on left, English PDF on right
        html_ratio = st.session_state.split_ratio
        pdf_ratio = 100 - html_ratio
        col_left, col_right = st.columns([html_ratio, pdf_ratio])

        with col_left:
            display_html(files['html'], st.session_state.html_font_size)

        with col_right:
            display_pdf(files['pdf'])
    else:
        # Single view mode
        file_type, file_path = format_options[selected_format_name]

        # Display the content based on type (no title, just content)
        if file_type == 'html':
            display_html(file_path, st.session_state.html_font_size)
        elif file_type == 'pdf':
            display_pdf(file_path)
        elif file_type == 'md_en':
            display_markdown(file_path)



def main():
    """
    Main application entry point
    """
    # Route to appropriate view
    if st.session_state.view == 'list':
        render_paper_list()
    elif st.session_state.view == 'detail':
        render_paper_detail()


if __name__ == "__main__":
    main()
