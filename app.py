"""
PaperFlow Streamlit Viewer
A web interface for viewing converted academic papers in Korean and English
"""

import streamlit as st
import os
import base64
import re
import json
from pathlib import Path
from streamlit_pdf_viewer import pdf_viewer
from dotenv import load_dotenv
from datetime import datetime, timedelta
from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

# Load environment variables
load_dotenv()


def get_session_id():
    """
    Get current Streamlit session ID
    Returns None if context is not available
    """
    try:
        ctx = get_script_run_ctx()
        if ctx is None:
            return None
        return ctx.session_id
    except Exception:
        return None


def get_session_file():
    """
    Get session file path for current session
    Each browser/tab gets its own session file
    """
    # Create sessions directory if it doesn't exist
    sessions_dir = Path(".sessions")
    sessions_dir.mkdir(exist_ok=True)

    session_id = get_session_id()
    if session_id:
        return sessions_dir / f"session_{session_id}.json"
    # Fallback to default if session ID unavailable
    return sessions_dir / "session_default.json"


def save_session(username):
    """Save login session to file (session-specific)"""
    session_file = get_session_file()
    session_data = {
        "username": username,
        "login_time": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=30)).isoformat()
    }
    try:
        with open(session_file, 'w') as f:
            json.dump(session_data, f)
    except Exception as e:
        print(f"Failed to save session: {e}")


def load_session():
    """Load login session from file (session-specific)"""
    session_file = get_session_file()
    if not session_file.exists():
        return None

    try:
        with open(session_file, 'r') as f:
            session_data = json.load(f)

        # Check if session is expired
        expires_at = datetime.fromisoformat(session_data["expires_at"])
        if datetime.now() > expires_at:
            # Session expired, delete file
            delete_session()
            return None

        return session_data["username"]
    except Exception as e:
        print(f"Failed to load session: {e}")
        return None


def delete_session():
    """Delete login session file (session-specific)"""
    session_file = get_session_file()
    try:
        if session_file.exists():
            session_file.unlink()
    except Exception as e:
        print(f"Failed to delete session: {e}")


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

    /* Login form styling */
    .stForm {
        background: white;
        padding: 2.5rem;
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(102, 126, 234, 0.15);
        border: 2px solid rgba(102, 126, 234, 0.1);
    }

    /* Login input fields */
    .stTextInput input {
        border-radius: 10px;
        border: 2px solid #e2e8f0;
        padding: 12px;
        font-size: 0.95rem;
    }

    .stTextInput input:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }

    /* Login button styling */
    .stForm .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: 700;
        font-size: 1rem;
        padding: 12px;
        border-radius: 10px;
        margin-top: 1rem;
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
if 'show_log' not in st.session_state:
    st.session_state.show_log = False
if 'show_upload' not in st.session_state:
    st.session_state.show_upload = False
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_tab' not in st.session_state:
    st.session_state.current_tab = 'unread'  # 'unread' or 'archived'


def render_login_page():
    """
    Render the login page
    """
    # Center container
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔐 PaperFlow")
        st.markdown("### 로그인이 필요합니다")
        st.markdown("<br>", unsafe_allow_html=True)

        # Login form
        with st.form("login_form", clear_on_submit=True):
            username = st.text_input("아이디", placeholder="아이디를 입력하세요")
            password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")

            st.markdown("<br>", unsafe_allow_html=True)
            submit = st.form_submit_button("🚀 로그인", use_container_width=True)

            if submit:
                # Get credentials from environment variables
                correct_id = os.getenv("LOGIN_ID")
                correct_password = os.getenv("LOGIN_PASSWORD")

                # Check credentials
                if username == correct_id and password == correct_password:
                    st.session_state.logged_in = True
                    st.session_state.username = username

                    # Save session to file (expires in 30 days)
                    save_session(username)

                    st.success("✅ 로그인 성공!")
                    st.rerun()
                else:
                    st.error("❌ 아이디 또는 비밀번호가 올바르지 않습니다")

        st.markdown("<br><br>", unsafe_allow_html=True)
        st.info("💡 관리자에게 계정 정보를 문의하세요")


def get_latest_log():
    """
    Get the latest log file from logs directory.
    Returns tuple: (log_path, log_content) or (None, None) if no logs found
    """
    logs_dir = Path("logs")

    if not logs_dir.exists():
        return None, None

    # Find all log files with pattern paperflow_*.log
    log_files = list(logs_dir.glob("paperflow_*.log"))

    if not log_files:
        return None, None

    # Sort by modification time, most recent first
    log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    latest_log = log_files[0]

    try:
        with open(latest_log, 'r', encoding='utf-8') as f:
            log_content = f.read()
        return latest_log, log_content
    except Exception as e:
        return latest_log, f"로그 파일을 읽을 수 없습니다: {str(e)}"


def get_paper_list(directory='outputs'):
    """
    Scan the specified directory and return list of paper folders.
    Args:
        directory: 'outputs' or 'archives'
    Returns list of tuples: (folder_name, folder_path)
    """
    target_dir = Path(directory)

    if not target_dir.exists():
        return []

    papers = []
    for item in target_dir.iterdir():
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


def archive_paper(paper_path):
    """
    Move paper from outputs/ to archives/
    Returns: (success: bool, message: str)
    """
    try:
        paper_path = Path(paper_path)
        paper_name = paper_path.name

        # Create archives directory if it doesn't exist
        archives_dir = Path("archives")
        archives_dir.mkdir(exist_ok=True)

        # Destination path
        dest_path = archives_dir / paper_name

        # Check if already exists in archives
        if dest_path.exists():
            return False, f"⚠️ {paper_name}이(가) 이미 아카이브에 존재합니다."

        # Move the entire folder
        import shutil
        shutil.move(str(paper_path), str(dest_path))

        return True, f"✓ {paper_name}이(가) 읽은 논문으로 이동되었습니다."

    except Exception as e:
        return False, f"❌ 이동 실패: {str(e)}"


def restore_paper(paper_path):
    """
    Move paper from archives/ to outputs/
    Returns: (success: bool, message: str)
    """
    try:
        paper_path = Path(paper_path)
        paper_name = paper_path.name

        # Create outputs directory if it doesn't exist
        outputs_dir = Path("outputs")
        outputs_dir.mkdir(exist_ok=True)

        # Destination path
        dest_path = outputs_dir / paper_name

        # Check if already exists in outputs
        if dest_path.exists():
            return False, f"⚠️ {paper_name}이(가) 이미 읽을 논문 목록에 존재합니다."

        # Move the entire folder
        import shutil
        shutil.move(str(paper_path), str(dest_path))

        return True, f"✓ {paper_name}이(가) 읽을 논문으로 복원되었습니다."

    except Exception as e:
        return False, f"❌ 복원 실패: {str(e)}"


def get_paper_stats():
    """
    Get statistics about papers
    Returns: dict with counts
    """
    outputs_dir = Path("outputs")
    archives_dir = Path("archives")

    unread_count = len([d for d in outputs_dir.iterdir() if d.is_dir()]) if outputs_dir.exists() else 0
    archived_count = len([d for d in archives_dir.iterdir() if d.is_dir()]) if archives_dir.exists() else 0

    return {
        'unread_count': unread_count,
        'archived_count': archived_count,
        'total_count': unread_count + archived_count
    }


def display_html(html_path, font_size=100, dual_view=False):
    """
    Display HTML file using iframe with injected CSS to hide TOC and headers
    Args:
        html_path: Path to HTML file
        font_size: Font size percentage (default 100)
        dual_view: If True, use fixed height for side-by-side view (default False)
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
            /* Adjust content to full width with minimal padding and center alignment */
            body, #quarto-content, .content, #quarto-document-content, main, .main {{
                max-width: 100% !important;
                width: 100% !important;
                margin: 0 auto !important;
                padding-left: 1em !important;
                padding-right: 1em !important;
                box-sizing: border-box !important;
            }}
            /* Container full width with center alignment */
            .container, .container-fluid, article {{
                max-width: 100% !important;
                width: 100% !important;
                margin: 0 auto !important;
                padding-left: 1em !important;
                padding-right: 1em !important;
                box-sizing: border-box !important;
            }}
            /* Force all main content blocks to be centered */
            #quarto-content > * {{
                margin-left: auto !important;
                margin-right: auto !important;
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

        # Choose height based on view mode
        # Dual view: fixed height for independent left/right scrolling
        # Single view: very tall height to minimize outer page scroll
        height = 3000 if dual_view else 50000
        st.components.v1.html(html_content, height=height, scrolling=True)

    except Exception as e:
        st.error(f"HTML 파일을 불러올 수 없습니다: {str(e)}")

    return html_content if 'html_content' in locals() else None


def display_pdf(pdf_path, dual_view=False):
    """
    Display PDF file using streamlit-pdf-viewer
    Args:
        pdf_path: Path to PDF file
        dual_view: If True, use fixed height for side-by-side view (default False)
    """
    try:
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        # Choose height based on view mode
        # Dual view: fixed height for independent left/right scrolling
        # Single view: very tall height to minimize outer page scroll
        height = 3000 if dual_view else 50000
        pdf_viewer(
            pdf_bytes,
            height=height,
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
    # Header: Title on the left, buttons on the right
    st.title("📚 PaperFlow Viewer")

    # Buttons aligned to the right
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = None
            # Delete session file
            delete_session()
            st.rerun()
    with col2:
        if st.button("📤 업로드", use_container_width=True):
            st.session_state.show_upload = not st.session_state.show_upload
            st.rerun()
    with col3:
        if st.button("📋 로그", use_container_width=True):
            st.session_state.show_log = not st.session_state.show_log
            st.rerun()
    with col4:
        if st.button("🔄 새로고침", use_container_width=True):
            st.rerun()

    # Upload UI expander (shown when show_upload is True)
    if st.session_state.show_upload:
        with st.expander("📤 PDF 파일 업로드", expanded=True):
            st.markdown("**업로드할 PDF 파일을 선택하세요** (여러 파일 동시 업로드 가능)")

            uploaded_files = st.file_uploader(
                "PDF 파일 선택",
                type=['pdf'],
                accept_multiple_files=True,
                label_visibility="collapsed"
            )

            if uploaded_files:
                newones_dir = Path("newones")
                newones_dir.mkdir(exist_ok=True)

                upload_results = []

                for uploaded_file in uploaded_files:
                    file_path = newones_dir / uploaded_file.name

                    # Check for duplicates
                    if file_path.exists():
                        upload_results.append({
                            'name': uploaded_file.name,
                            'status': 'duplicate',
                            'message': f"⚠️ **{uploaded_file.name}**: 이미 존재하는 파일입니다 (덮어쓰기됨)"
                        })
                    else:
                        upload_results.append({
                            'name': uploaded_file.name,
                            'status': 'new',
                            'message': f"✅ **{uploaded_file.name}**: 업로드 완료"
                        })

                    # Save file
                    try:
                        with open(file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                    except Exception as e:
                        upload_results[-1]['status'] = 'error'
                        upload_results[-1]['message'] = f"❌ **{uploaded_file.name}**: 저장 실패 - {str(e)}"

                # Display results
                st.markdown("---")
                for result in upload_results:
                    if result['status'] == 'new':
                        st.success(result['message'])
                    elif result['status'] == 'duplicate':
                        st.warning(result['message'])
                    else:
                        st.error(result['message'])

                # Summary message
                success_count = sum(1 for r in upload_results if r['status'] in ['new', 'duplicate'])
                if success_count > 0:
                    st.info(f"ℹ️ **{success_count}개 파일 업로드 완료** - Watch mode가 5초 이내에 처리를 시작합니다")

    # Log viewer expander (shown when show_log is True)
    if st.session_state.show_log:
        log_path, log_content = get_latest_log()

        if log_path is None:
            st.info("📂 로그 파일이 없습니다.")
        else:
            with st.expander(f"📋 최신 로그: {log_path.name}", expanded=True):
                # Strip ANSI color codes
                clean_log = re.sub(r'\x1b\[[0-9;]*m', '', log_content)

                # Show last 100 lines for performance
                lines = clean_log.split('\n')
                if len(lines) > 100:
                    st.info(f"ℹ️ 총 {len(lines)}줄 중 마지막 100줄만 표시합니다. 전체 로그는 다운로드 버튼을 사용하세요.")
                    display_lines = lines[-100:]
                else:
                    display_lines = lines

                # Display log content in code block
                st.code('\n'.join(display_lines), language='log')

                # Download button for full log
                st.download_button(
                    label="💾 전체 로그 다운로드",
                    data=log_content,
                    file_name=log_path.name,
                    mime="text/plain",
                    use_container_width=True
                )

    # Tab navigation
    stats = get_paper_stats()

    tab1, tab2 = st.tabs([
        f"📚 읽을 논문 ({stats['unread_count']}개)",
        f"✅ 읽은 논문 ({stats['archived_count']}개)"
    ])

    # Unread papers tab
    with tab1:
        st.session_state.current_tab = 'unread'
        papers = get_paper_list('outputs')

        if not papers:
            st.info("📂 읽을 논문이 없습니다.")
            st.markdown("**사용 방법:**")
            st.code("./run_batch_venv.sh", language="bash")
        else:
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

                            # Check if paper is being processed (no HTML/PDF yet)
                            if not files['html'] and not files['pdf']:
                                formats_html.append('<span class="format-badge" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">🔄 처리중</span>')
                            else:
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

                            # Buttons row
                            btn_col1, btn_col2 = st.columns(2, gap="small")
                            with btn_col1:
                                if st.button("📖 보기", key=f"view_unread_{idx}", use_container_width=True):
                                    st.session_state.selected_paper = paper_path
                                    st.session_state.view = 'detail'
                                    st.rerun()
                            with btn_col2:
                                if st.button("✅ 완료", key=f"archive_{idx}", use_container_width=True):
                                    success, message = archive_paper(paper_path)
                                    if success:
                                        st.success(message)
                                        st.rerun()
                                    else:
                                        st.error(message)

    # Archived papers tab
    with tab2:
        st.session_state.current_tab = 'archived'
        papers = get_paper_list('archives')

        if not papers:
            st.info("📂 읽은 논문이 없습니다.")
        else:
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

                            # Create a beautiful card using HTML with archived style
                            card_html = f'''
                            <div class="paper-card archived" style="opacity: 0.95; background: #f7fafc;">
                                <div class="paper-title">📄 {paper_name}</div>
                                <div style="margin-bottom: 8px;">
                                    {''.join(formats_html)}
                                </div>
                            </div>
                            '''
                            st.markdown(card_html, unsafe_allow_html=True)

                            # Buttons row
                            btn_col1, btn_col2 = st.columns(2, gap="small")
                            with btn_col1:
                                if st.button("📖 보기", key=f"view_archived_{idx}", use_container_width=True):
                                    st.session_state.selected_paper = paper_path
                                    st.session_state.view = 'detail'
                                    st.rerun()
                            with btn_col2:
                                if st.button("↩️ 복원", key=f"restore_{idx}", use_container_width=True):
                                    success, message = restore_paper(paper_path)
                                    if success:
                                        st.success(message)
                                        st.rerun()
                                    else:
                                        st.error(message)


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
        format_names = []

        # Add "분할 보기" option first if both HTML and PDF are available
        if files['html'] and files['pdf']:
            format_names.append("🔄 분할 보기 (한국어 + 영어)")

        # Then add individual format options
        format_names.extend(list(format_options.keys()))

        # Initialize selected format if not set
        if st.session_state.selected_format is None:
            # Default to "분할 보기" if both HTML and PDF are available
            if files['html'] and files['pdf']:
                st.session_state.selected_format = "🔄 분할 보기 (한국어 + 영어)"
            else:
                st.session_state.selected_format = format_names[0]

        selected_format_name = st.radio(
            "형식",
            format_names,
            index=format_names.index(st.session_state.selected_format) if st.session_state.selected_format in format_names else 0,
            label_visibility="collapsed"
        )

        st.session_state.selected_format = selected_format_name

        # Font size control - only show for HTML-containing formats
        if selected_format_name in ["🇰🇷 한국어 (HTML)", "🔄 분할 보기 (한국어 + 영어)"]:
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
        if selected_format_name == "🔄 분할 보기 (한국어 + 영어)":
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

        # Archive/Restore button at the bottom of sidebar
        st.markdown("---")

        # Check if paper is in outputs or archives
        paper_path_obj = Path(paper_path)
        is_archived = paper_path_obj.parent.name == 'archives'

        if is_archived:
            # Show restore button for archived papers
            if st.button("↩️ 읽을 논문으로 복원", use_container_width=True, key="restore_detail"):
                success, message = restore_paper(paper_path)
                if success:
                    st.success(message)
                    # Update selected paper path to new location
                    st.session_state.selected_paper = str(Path("outputs") / paper_name)
                    st.rerun()
                else:
                    st.error(message)
        else:
            # Show archive button for unread papers
            if st.button("✅ 읽음으로 표시", use_container_width=True, key="archive_detail"):
                success, message = archive_paper(paper_path)
                if success:
                    st.success(message)
                    # Return to list view after archiving
                    st.session_state.view = 'list'
                    st.session_state.selected_paper = None
                    st.rerun()
                else:
                    st.error(message)

    # Main content area - display selected format directly without header
    # Check if "분할 보기" mode is selected
    if selected_format_name == "🔄 분할 보기 (한국어 + 영어)":
        # Split screen with adjustable ratio: Korean HTML on left, English PDF on right
        html_ratio = st.session_state.split_ratio
        pdf_ratio = 100 - html_ratio
        col_left, col_right = st.columns([html_ratio, pdf_ratio])

        with col_left:
            display_html(files['html'], st.session_state.html_font_size, dual_view=True)

        with col_right:
            display_pdf(files['pdf'], dual_view=True)
    else:
        # Single view mode
        file_type, file_path = format_options[selected_format_name]

        # Display the content based on type (no title, just content)
        if file_type == 'html':
            display_html(file_path, st.session_state.html_font_size, dual_view=False)
        elif file_type == 'pdf':
            display_pdf(file_path, dual_view=False)
        elif file_type == 'md_en':
            display_markdown(file_path)



def main():
    """
    Main application entry point
    """
    # Check for existing session file (auto-login)
    if not st.session_state.logged_in:
        saved_user = load_session()
        if saved_user:
            # Auto-login from session file
            st.session_state.logged_in = True
            st.session_state.username = saved_user

    # Check login status
    if not st.session_state.logged_in:
        render_login_page()
        return

    # Route to appropriate view
    if st.session_state.view == 'list':
        render_paper_list()
    elif st.session_state.view == 'detail':
        render_paper_detail()


if __name__ == "__main__":
    main()
