/**
 * TAHRIX Agent — Flow-Based Streaming Frontend
 * 
 * Consumes a hybrid polling API for LLM streaming with reasoning,
 * tool calls, and content rendered in the exact order produced by the LLM.
 * 
 * Required: mdRender() function, esc() function, $() selector, API/TOKEN constants
 */

// ─── CSS (add to your stylesheet) ──────────────────────────────────────────
/*
.ta-loading-dots{display:flex;align-items:center;gap:4px;padding:4px 8px;font-size:7px;color:var(--text3)}
.ta-loading-dots .ldot{width:4px;height:4px;border-radius:50%;background:var(--cyan);animation:ldot 1.4s infinite ease-in-out both}
.ta-loading-dots .ldot:nth-child(1){animation-delay:-0.32s}
.ta-loading-dots .ldot:nth-child(2){animation-delay:-0.16s}
@keyframes ldot{0%,80%,100%{transform:scale(0);opacity:.5}40%{transform:scale(1);opacity:1}}
.ta-reasoning{font-size:7px;color:var(--text3);padding:4px 8px;margin:2px 0;border-left:2px solid var(--amber);background:var(--amber-dim);border-radius:0 4px 4px 0;max-height:60px;overflow-y:auto;line-height:1.4;cursor:pointer}
.ta-reasoning.collapsed{max-height:14px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.ta-tool-call{font-size:7px;color:var(--cyan);padding:3px 8px;margin:2px 0;background:var(--bg4);border:1px solid var(--border2);border-radius:4px;display:flex;align-items:center;gap:4px}
.ta-tool-call .tc-icon{font-size:8px}
.ta-tool-call .tc-name{font-weight:600;letter-spacing:.5px}
.ta-tool-call .tc-status{margin-left:auto;font-size:6px;color:var(--text3)}
.ta-tool-call .tc-status.done{color:var(--green)}
.ta-tool-call .tc-status.fail{color:var(--red)}
.ta-typing::after{content:'▊';animation:blink 1s step-end infinite;color:var(--cyan)}
@keyframes blink{50%{opacity:0}}
.ta-token-badge{display:flex;justify-content:flex-end;padding:2px 4px;font-size:6px;color:var(--text3);gap:6px}
.ta-token-badge span{background:var(--bg4);padding:1px 4px;border-radius:3px;border:1px solid var(--border2)}
*/

// ─── HTML Structure ─────────────────────────────────────────────────────────
/*
<div id="ta-body"><!-- chat messages container --></div>
<input id="ta-input" placeholder="Ask the agent...">
*/

// ─── JavaScript ─────────────────────────────────────────────────────────────

let _taHistory = [];

// Create a streaming message placeholder - flow-based rendering
// Events are appended in the order they arrive from the LLM
function createStreamMessage(){
  const body = $('ta-body');
  const div = document.createElement('div');
  div.className = 'ta-msg agent';
  div.innerHTML = `<span class="ta-msg-role">AI AGENT</span>
    <div class="ta-flow"></div>
    <div class="ta-token-badge" style="display:none"></div>`;
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
  const flowEl = div.querySelector('.ta-flow');
  return {
    el: div,
    flowEl: flowEl,
    badgeEl: div.querySelector('.ta-token-badge'),
    fullContent: '',
    fullReasoning: '',
    // Track current active elements for appending text
    activeReasoningEl: null,
    activeContentEl: null,
    activeToolName: null,
    activeToolStatusEl: null,
  };
}

async function sendTaMessage(){
  const input = $('ta-input');
  const msg = input.value.trim();
  if(!msg) return;
  addTaMessage(msg, true);  // your function to add user message bubble
  input.value = '';
  input.disabled = true;

  // Create streaming placeholder with loading animation
  const stream = createStreamMessage();
  const loadingDots = document.createElement('div');
  loadingDots.className = 'ta-loading-dots';
  loadingDots.innerHTML = '<div class="ldot"></div><div class="ldot"></div><div class="ldot"></div>';
  stream.flowEl.appendChild(loadingDots);
  stream._loadingDots = loadingDots;

  try{
    await streamTaMessage(msg, stream);
  }catch(e){
    if(stream._loadingDots) stream._loadingDots.style.display='none';
    const errEl = document.createElement('div');
    errEl.style.color = 'var(--red)';
    errEl.style.fontSize = '9px';
    errEl.textContent = 'Error: ' + e.message;
    stream.flowEl.appendChild(errEl);
  }

  input.disabled = false;
  input.focus();
}

async function streamTaMessage(msg, stream){
  const payload = { message: msg, case_id: caseId || null };
  if(_taHistory.length > 0) payload.history = _taHistory.slice(-20);

  // 1) Create streaming job
  const createResp = await fetch(`${API}/agent/chat-stream-job`,{
    method:'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+TOKEN},
    body: JSON.stringify(payload)
  });

  if(!createResp.ok) throw new Error('HTTP ' + createResp.status);

  const {job_id, meta} = await createResp.json();
  // Use meta to update context bar, memory bar, etc.

  // 2) Poll for incremental chunks (every 500ms for smooth streaming)
  let lastChunkIdx = 0;
  let usageData = null;
  const pollDelay = ms => new Promise(r => setTimeout(r, ms));

  for(let attempt = 0; attempt < 120; attempt++){  // max 60s
    await pollDelay(500);

    const pollResp = await fetch(`${API}/agent/chat-stream-job/${job_id}`,{
      headers:{'Authorization':'Bearer '+TOKEN}
    });
    if(!pollResp.ok) continue;

    const status = await pollResp.json();

    // Process new chunks since last poll — flow-based rendering
    const chunks = status.chunks || [];
    for(let i = lastChunkIdx; i < chunks.length; i++){
      const chunk = chunks[i];
      switch(chunk.type){
        case 'reasoning':
          stream.fullReasoning += chunk.text;
          if(!stream.activeReasoningEl){
            if(stream._loadingDots) stream.flowEl.appendChild(stream._loadingDots);
            if(stream.activeContentEl){ stream.activeContentEl.classList.remove('ta-typing'); stream.activeContentEl = null; }
            if(stream._followUpEl){ stream._followUpEl.remove(); stream._followUpEl = null; }
            const rEl = document.createElement('div');
            rEl.className = 'ta-reasoning';
            stream.flowEl.insertBefore(rEl, stream._loadingDots);
            stream.activeReasoningEl = rEl;
          }
          stream.activeReasoningEl.textContent = '💭 ' + stream.fullReasoning;
          stream.activeReasoningEl.onclick = () => stream.activeReasoningEl.classList.toggle('collapsed');
          break;

        case 'content':
          stream.fullContent += chunk.text;
          if(!stream.activeContentEl){
            if(stream._loadingDots) stream.flowEl.appendChild(stream._loadingDots);
            if(stream.activeReasoningEl){
              stream.activeReasoningEl.classList.add('collapsed');
              stream.activeReasoningEl = null;
            }
            if(stream._followUpEl){ stream._followUpEl.remove(); stream._followUpEl = null; }
            const cEl = document.createElement('div');
            cEl.className = 'ta-msg-content ta-typing';
            stream.flowEl.insertBefore(cEl, stream._loadingDots);
            stream.activeContentEl = cEl;
          }
          stream.activeContentEl.innerHTML = mdRender(stream.fullContent);
          $('ta-body').scrollTop = $('ta-body').scrollHeight;
          break;

        case 'tool_call': {
          if(stream._loadingDots) stream.flowEl.appendChild(stream._loadingDots);
          if(stream.activeContentEl){ stream.activeContentEl.classList.remove('ta-typing'); stream.activeContentEl = null; }
          if(stream.activeReasoningEl){ stream.activeReasoningEl.classList.add('collapsed'); stream.activeReasoningEl = null; }
          const tcDiv = document.createElement('div');
          tcDiv.className = 'ta-tool-call';
          tcDiv.innerHTML = `<span class="tc-icon">🔧</span><span class="tc-name">${esc(chunk.name)}</span><span class="tc-status">running...</span>`;
          stream.flowEl.insertBefore(tcDiv, stream._loadingDots);
          stream.activeToolName = chunk.name;
          stream.activeToolStatusEl = tcDiv.querySelector('.tc-status');
          break;
        }

        case 'tool_result': {
          if(stream.activeToolStatusEl && stream.activeToolName === chunk.name){
            stream.activeToolStatusEl.textContent = '✓ done';
            stream.activeToolStatusEl.className = 'tc-status done';
            stream.activeToolName = null;
            stream.activeToolStatusEl = null;
          }
          break;
        }

        case 'follow_up': {
          // Reset accumulated text — follow-up is a new LLM call
          stream.fullReasoning = '';
          stream.fullContent = '';
          // Remove first call's content & reasoning DOM — they'll be replaced by follow-up
          if(stream.activeContentEl){ stream.activeContentEl.remove(); stream.activeContentEl = null; }
          if(stream.activeReasoningEl){ stream.activeReasoningEl.remove(); stream.activeReasoningEl = null; }
          const oldContent = stream.flowEl.querySelectorAll('.ta-msg-content');
          oldContent.forEach(el => el.remove());
          const oldReasoning = stream.flowEl.querySelectorAll('.ta-reasoning');
          oldReasoning.forEach(el => el.remove());
          if(stream._loadingDots) stream.flowEl.appendChild(stream._loadingDots);
          const fuDiv = document.createElement('div');
          fuDiv.className = 'ta-reasoning';
          fuDiv.style.borderLeftColor = 'var(--cyan)';
          fuDiv.style.background = 'var(--bg4)';
          fuDiv.textContent = '🔄 ' + chunk.text;
          stream.flowEl.insertBefore(fuDiv, stream._loadingDots);
          stream._followUpEl = fuDiv;
          break;
        }
      }
    }
    lastChunkIdx = chunks.length;

    // Fallback: sync accumulated content if chunks were trimmed or no active block
    if(status.content && status.content.length > stream.fullContent.length){
      stream.fullContent = status.content;
      if(!stream.activeContentEl){
        if(stream.activeReasoningEl){ stream.activeReasoningEl.classList.add('collapsed'); stream.activeReasoningEl = null; }
        const cEl = document.createElement('div');
        cEl.className = 'ta-msg-content ta-typing';
        stream.flowEl.appendChild(cEl);
        stream.activeContentEl = cEl;
      }
      stream.activeContentEl.innerHTML = mdRender(stream.fullContent);
      $('ta-body').scrollTop = $('ta-body').scrollHeight;
    }
    if(status.reasoning && status.reasoning.length > stream.fullReasoning.length){
      stream.fullReasoning = status.reasoning;
      if(!stream.activeReasoningEl){
        const rEl = document.createElement('div');
        rEl.className = 'ta-reasoning';
        stream.flowEl.appendChild(rEl);
        stream.activeReasoningEl = rEl;
      }
      stream.activeReasoningEl.textContent = '💭 ' + stream.fullReasoning;
      stream.activeReasoningEl.onclick = () => stream.activeReasoningEl.classList.toggle('collapsed');
    }
    // Update tool call statuses from Redis state
    if(status.tool_calls){
      for(const tc of status.tool_calls){
        if(tc.status === 'done'){
          const tcDivs = stream.flowEl.querySelectorAll('.ta-tool-call');
          for(const div of tcDivs){
            const nameEl = div.querySelector('.tc-name');
            const statusEl = div.querySelector('.tc-status');
            if(nameEl && nameEl.textContent === tc.name && statusEl && statusEl.textContent === 'running...'){
              statusEl.textContent = '✓ done';
              statusEl.className = 'tc-status done';
            }
          }
        }
      }
    }

    // Check if done
    if(status.status === 'done'){
      usageData = status.usage;
      if(stream.activeContentEl) stream.activeContentEl.classList.remove('ta-typing');
      if(stream.activeReasoningEl) stream.activeReasoningEl.classList.add('collapsed');
      if(stream._loadingDots) stream._loadingDots.style.display='none';

      // Token badge
      const inTk = usageData ? usageData.prompt_tokens : (meta?.input_tokens_est || '—');
      const outTk = usageData ? usageData.completion_tokens : (meta?.output_tokens_est || '—');
      stream.badgeEl.style.display = 'flex';
      stream.badgeEl.innerHTML = `<span>In: ${inTk} tk</span><span>Out: ${outTk} tk</span>`;

      // Save to history
      _taHistory.push({role: 'user', content: msg});
      _taHistory.push({role: 'assistant', content: stream.fullContent});
      if(_taHistory.length > 20) _taHistory = _taHistory.slice(-20);
      return;
    }

    if(status.status === 'error'){
      if(stream.activeContentEl) stream.activeContentEl.classList.remove('ta-typing');
      if(stream._loadingDots) stream._loadingDots.style.display='none';
      const errEl = document.createElement('div');
      errEl.style.color = 'var(--red)';
      errEl.style.fontSize = '9px';
      errEl.textContent = 'Error: ' + (status.content || 'Unknown error');
      stream.flowEl.appendChild(errEl);
      return;
    }
  }

  // Timeout
  if(stream.activeContentEl) stream.activeContentEl.classList.remove('ta-typing');
  if(stream._loadingDots) stream._loadingDots.style.display='none';
  const errEl = document.createElement('div');
  errEl.style.color = 'var(--red)';
  errEl.style.fontSize = '9px';
  errEl.textContent = 'Error: AI response timed out.';
  stream.flowEl.appendChild(errEl);
}
