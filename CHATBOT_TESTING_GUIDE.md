# PaperFlow Chatbot Testing Guide

## Prerequisites

1. Docker Compose environment running
2. At least one paper with markdown files (`.md` or `_ko.md`)
3. OpenAI-compatible API configured in `.env`:
   ```
   OPENAI_BASE_URL=your_api_base_url
   OPENAI_API_KEY=your_api_key
   TRANSLATION_MODEL=your_model_name  # e.g., gemini-claude-sonnet-4-5
   ```

## Test Phase 1: Backend API Testing

### 1.1 Start Services
```bash
cd /media/restful3/data/workspace/paperflow
docker compose up -d
docker compose logs -f viewer
```

### 1.2 Verify Dependencies Installed
```bash
docker compose exec viewer pip list | grep -E "sse-starlette|openai"
```

Expected output:
```
openai                    1.x.x
sse-starlette             2.1.0
```

### 1.3 Check for Import Errors
```bash
docker compose exec viewer python -c "
from viewer.app.models.chat import ChatMessage, ChatHistory, ChatRequest, ChatChunk
from viewer.app.services.chat import load_chat_history, save_chat_history, get_or_create_chunks
from viewer.app.services.rag import chunk_markdown, search_chunks, build_rag_context, generate_response_stream
print('✅ All imports successful!')
"
```

### 1.4 Test Chunking Function
```bash
docker compose exec viewer python -c "
from pathlib import Path
from viewer.app.services.rag import chunk_markdown

# Find first paper with markdown
outputs_dir = Path('/app/outputs')
for paper_dir in outputs_dir.iterdir():
    if paper_dir.is_dir():
        md_files = list(paper_dir.glob('*.md'))
        if md_files:
            chunks = chunk_markdown(md_files[0])
            print(f'✅ Chunked {md_files[0].name}: {len(chunks)} chunks')
            print(f'   First chunk heading: {chunks[0].heading}')
            print(f'   First chunk length: {len(chunks[0].content)} chars')
            break
"
```

### 1.5 Test Chat History Load/Save
```bash
docker compose exec viewer python -c "
from viewer.app.services.chat import load_chat_history, save_chat_history
from viewer.app.models.chat import ChatMessage
from datetime import datetime
from pathlib import Path

# Find first paper
outputs_dir = Path('/app/outputs')
paper_name = next(d.name for d in outputs_dir.iterdir() if d.is_dir())

# Load (should be empty)
history = load_chat_history(paper_name)
print(f'✅ Loaded history for {paper_name}: {len(history.messages)} messages')

# Add test message
history.messages.append(ChatMessage(
    role='user',
    content='Test message',
    timestamp=datetime.now()
))

# Save
save_chat_history(history)
print(f'✅ Saved history with {len(history.messages)} message(s)')

# Verify file created
chat_file = outputs_dir / paper_name / 'chat_history.json'
print(f'✅ Chat history file exists: {chat_file.exists()}')
"
```

## Test Phase 2: Frontend UI Testing

### 2.1 Access Viewer
1. Open browser: http://localhost:8000
2. Login with credentials from `.env` (`LOGIN_ID`, `LOGIN_PASSWORD`)
3. Navigate to any paper with markdown files

### 2.2 Verify Chatbot Button Visibility

**Desktop (viewport ≥ 768px):**
- [ ] Chatbot button visible at bottom-right corner
- [ ] Button shows only for papers with `.md` or `_ko.md` files
- [ ] Button hidden for papers without markdown
- [ ] Button has indigo background with hover effect
- [ ] Button shows chat icon (speech bubble)

**Mobile (viewport < 768px):**
- [ ] Button visible when top bar is visible
- [ ] Button fades out when top bar auto-hides on scroll down
- [ ] Button position: `bottom-6 right-6` when visible
- [ ] Button position: `bottom-20 right-6 opacity-0` when hidden
- [ ] Smooth transition (300ms)

Test mobile in Chrome DevTools:
1. F12 → Device Toolbar (Ctrl+Shift+M)
2. Select "iPhone SE" or "iPad Mini"
3. Scroll down in paper view → button should hide with top bar
4. Scroll up → button should show immediately

### 2.3 Verify Chatbot Panel Opening

**Desktop:**
1. Click chatbot button
2. [ ] Panel slides in from right side
3. [ ] Panel size: 384px wide (`w-96`), 600px tall
4. [ ] Panel positioned at `bottom-0 right-0` with margins
5. [ ] Panel has header with "Paper Chat" title
6. [ ] Panel has clear history button (🗑️)
7. [ ] Panel has close button (✕)
8. [ ] Chatbot button hidden when panel open

**Mobile:**
1. Tap chatbot button
2. [ ] Panel covers full screen (`inset-0`)
3. [ ] Top bar auto-shows when panel opens
4. [ ] Same header/buttons as desktop

### 2.4 Test Panel Interactions

**Opening:**
- [ ] Click/tap button → panel opens smoothly
- [ ] Input field auto-focuses on open
- [ ] Panel loads chat history if exists
- [ ] Empty panel shows no welcome message (just blank)

**Closing:**
- [ ] Click close button (✕) → panel closes
- [ ] Click outside panel (desktop) → panel closes
- [ ] Press ESC key → panel closes
- [ ] Chatbot button reappears after closing

## Test Phase 3: Chat Functionality

### 3.1 Send First Message
1. Open chatbot panel
2. Type question: "What is this paper about?"
3. Press Enter or click send button (➤)
4. Expected behavior:
   - [ ] Input clears immediately
   - [ ] User message appears in blue bubble (right-aligned)
   - [ ] Timestamp shows below user message
   - [ ] "Thinking..." indicator appears with bouncing dots
   - [ ] Assistant response streams word-by-word
   - [ ] Response appears in white bubble (left-aligned)
   - [ ] Auto-scroll to bottom during streaming

### 3.2 Verify RAG Context
Check that assistant response:
- [ ] References specific sections from the paper
- [ ] Uses information from paper content (not general knowledge)
- [ ] Mentions section headings if relevant
- [ ] Acknowledges if information is not in provided excerpts

### 3.3 Test Follow-up Questions
1. Ask: "Can you explain that in more detail?"
2. Expected behavior:
   - [ ] Assistant remembers context from previous message
   - [ ] Response builds on previous conversation
   - [ ] History preserved in panel

### 3.4 Test Chat History Persistence
1. Send 2-3 messages
2. Close panel and reopen
3. Expected behavior:
   - [ ] All previous messages visible
   - [ ] Timestamps preserved
   - [ ] Scroll position at bottom
   - [ ] Can continue conversation

### 3.5 Test Clear History
1. Click clear history button (🗑️)
2. Confirm deletion dialog
3. Expected behavior:
   - [ ] Confirmation dialog appears
   - [ ] After confirm: all messages cleared
   - [ ] Panel shows empty state
   - [ ] File `chat_history.json` deleted from paper directory

### 3.6 Test Paper Isolation
1. Chat with Paper A
2. Navigate to Paper B
3. Open chatbot
4. Expected behavior:
   - [ ] Empty chat (no messages from Paper A)
   - [ ] Can start new conversation
   - [ ] Return to Paper A → original chat history restored

## Test Phase 4: Error Handling

### 4.1 Test Missing Markdown
1. Navigate to paper without `.md` files (only PDF)
2. Expected behavior:
   - [ ] Chatbot button not visible
   - [ ] No errors in browser console

### 4.2 Test API Error
1. Stop Docker container (simulate API failure):
   ```bash
   docker compose stop viewer
   docker compose start viewer
   ```
2. Immediately try to send message
3. Expected behavior:
   - [ ] Error message displayed in panel
   - [ ] No crash or blank screen
   - [ ] Can retry after API recovers

### 4.3 Test Long Messages
1. Send very long question (>500 characters)
2. Expected behavior:
   - [ ] Message sends successfully
   - [ ] Response streams normally
   - [ ] Panel scrolls correctly

### 4.4 Test Special Characters
1. Send message with markdown syntax: "What about `code` and **bold**?"
2. Expected behavior:
   - [ ] Message displays correctly
   - [ ] Response may include markdown (rendered as plain text)
   - [ ] No XSS or injection issues

## Test Phase 5: Mobile-Specific Tests

### 5.1 Test Top Bar Integration
**Mobile viewport (<768px):**
1. Open paper with markdown
2. Scroll down in iframe → top bar hides
3. Expected behavior:
   - [ ] Chatbot button hides with top bar (opacity transition)
   - [ ] Smooth fade-out animation
   - [ ] Button at `bottom-20 right-6` when hidden

4. Tap anywhere → top bar shows
5. Expected behavior:
   - [ ] Chatbot button shows with top bar
   - [ ] Smooth fade-in animation
   - [ ] Button at `bottom-6 right-6` when visible

6. Open chatbot panel
7. Expected behavior:
   - [ ] Top bar forced visible (via `ensureTopBarVisible()`)
   - [ ] Panel covers full screen
   - [ ] Can still access close button

### 5.2 Test Touch Interactions
1. Tap chatbot button (not click)
2. [ ] Panel opens smoothly
3. Tap input field
4. [ ] Virtual keyboard appears
5. [ ] Input field scrolls into view (not covered by keyboard)
6. Type and send message
7. [ ] Keyboard doesn't obscure send button
8. Tap outside panel
9. [ ] Panel closes (click-away works)

### 5.3 Test Orientation Change
1. Open chatbot panel in portrait
2. Rotate device to landscape
3. [ ] Panel adjusts to full screen
4. [ ] Messages remain visible
5. [ ] No layout breaks

## Test Phase 6: Performance Tests

### 6.1 Test Large Papers
Use paper with >100 pages (large markdown):
1. Open chatbot
2. [ ] Chunking completes in <5 seconds
3. [ ] Chunks cached in `chat_chunks.json`
4. [ ] Second open: instant load (from cache)

### 6.2 Test Streaming Speed
1. Ask detailed question requiring long answer
2. Expected behavior:
   - [ ] First token arrives in <3 seconds
   - [ ] Tokens stream smoothly (no lag)
   - [ ] Total response time <30 seconds

### 6.3 Test Memory Usage
```bash
docker stats viewer --no-stream
```
- [ ] Memory usage stable during chat
- [ ] No memory leaks after multiple messages
- [ ] Container doesn't restart

## Test Phase 7: Integration Tests

### 7.1 Test with Paper Deletion
1. Open chatbot for Paper A
2. Send 2-3 messages
3. Delete Paper A via viewer interface
4. Expected behavior:
   - [ ] Paper deleted successfully
   - [ ] `chat_history.json` deleted
   - [ ] `chat_chunks.json` deleted
   - [ ] No orphaned files remain

### 7.2 Test with Archive/Restore
1. Chat with Paper A
2. Archive Paper A
3. Check `archives/Paper A/` directory:
   - [ ] `chat_history.json` moved with paper
   - [ ] `chat_chunks.json` moved with paper
4. Restore Paper A
5. Open chatbot:
   - [ ] Chat history restored
   - [ ] Can continue conversation

### 7.3 Test Multiple Papers Simultaneously
1. Open viewer in 2 browser tabs
2. Tab 1: Chat with Paper A
3. Tab 2: Chat with Paper B
4. Expected behavior:
   - [ ] Both chats work independently
   - [ ] No cross-contamination
   - [ ] History saves correctly for both

## Test Phase 8: Browser Compatibility

Test in multiple browsers:
- [ ] Chrome/Edge (Chromium)
- [ ] Firefox
- [ ] Safari (macOS/iOS)

For each browser, verify:
- [ ] Chatbot button visible
- [ ] Panel opens/closes
- [ ] Messages send/receive
- [ ] SSE streaming works
- [ ] No console errors

## Success Criteria

### Must Pass (Critical):
- [x] Backend dependencies installed (`sse-starlette`, `openai`)
- [ ] Chatbot button shows for papers with markdown
- [ ] Panel opens/closes smoothly
- [ ] Messages send and receive responses
- [ ] Chat history persists across sessions
- [ ] Papers isolated (no cross-talk)
- [ ] No errors in browser console
- [ ] No errors in Docker logs

### Should Pass (Important):
- [ ] Mobile top bar integration works
- [ ] Streaming response displays smoothly
- [ ] Clear history works correctly
- [ ] Archive/restore preserves chat
- [ ] Delete cleans up chat files
- [ ] Long papers chunk successfully

### Nice to Have (Optional):
- [ ] Works in all browsers
- [ ] Fast response time (<3s first token)
- [ ] Smooth animations on mobile
- [ ] No memory leaks

## Debugging Commands

### View Viewer Logs:
```bash
docker compose logs -f viewer
```

### Check Chat Files:
```bash
docker compose exec viewer ls -la /app/outputs/*/chat_*.json
```

### Test API Endpoint Directly:
```bash
# Get chat history
curl -X GET http://localhost:8000/api/papers/YourPaperName/chat/history \
  -H "Cookie: access_token=YOUR_JWT_TOKEN"

# Clear history
curl -X DELETE http://localhost:8000/api/papers/YourPaperName/chat/history \
  -H "Cookie: access_token=YOUR_JWT_TOKEN"
```

### Check Browser Console:
F12 → Console tab
- Look for network errors (red)
- Check SSE connection status
- Verify API responses

### Monitor SSE Stream:
F12 → Network tab → Filter: "chat" → Click request → EventStream tab
- Should show `type: token` events streaming
- Should end with `type: done`

## Known Issues & Workarounds

### Issue: Panel doesn't open
**Symptoms:** Click button, nothing happens
**Debug:**
1. Check browser console for errors
2. Verify `chatPanel()` function loaded: `console.log(typeof chatPanel)`
3. Check Alpine.js loaded: `console.log(typeof Alpine)`

### Issue: No streaming (blank response)
**Symptoms:** "Thinking..." indicator stays forever
**Debug:**
1. Check Network tab → chat endpoint → Response
2. Check if SSE events arriving
3. Verify `.env` has correct `OPENAI_BASE_URL` and `OPENAI_API_KEY`

### Issue: Button hidden on desktop
**Symptoms:** Button doesn't show even with markdown
**Debug:**
1. Check `hasMdKo` or `hasMdEn` value: `console.log(Alpine.store('...').hasMdKo)`
2. Verify paper has `.md` or `_ko.md` file
3. Check `x-show` directive in HTML

### Issue: Mobile button doesn't hide/show with top bar
**Symptoms:** Button stuck visible or invisible
**Debug:**
1. Check viewport size: `console.log(window.innerWidth)`
2. Verify `topBarVisible` state: `console.log(viewerApp.topBarVisible)`
3. Test `isMobile()` function: `console.log(chatButton.isMobile())`

## Reporting Issues

If tests fail, provide:
1. Browser name/version
2. Viewport size (mobile/desktop)
3. Error message (console + logs)
4. Steps to reproduce
5. Expected vs actual behavior

Example:
```
Browser: Chrome 120.0
Viewport: 375px (iPhone SE)
Error: "TypeError: Cannot read property 'messages' of undefined"
Console: [screenshot]
Logs: [docker compose logs output]

Steps:
1. Open paper "Example Paper"
2. Click chatbot button
3. Panel opens but empty
4. Send message "test"
5. Error appears in console

Expected: Message sends, response streams
Actual: Console error, no response
```
