(() => {
  const mode = window.drillMode;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let current = null, snapshot = null, busy = false, pending = Promise.resolve(), draftSaved = true, draftVersion = 0;
  function showError(message) { $('drill-error').textContent = message; $('drill-error').classList.remove('hidden'); }
  function clearError() { $('drill-error').classList.add('hidden'); }
  async function api(route, body, method = 'POST') {
    let response;
    try {
      response = await fetch(route, body === undefined ? {} : {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    } catch (error) { throw Error('无法连接本机工具箱，请确认工具箱仍在运行后重试'); }
    if (response.status === 401) { location.href = '/login'; throw Error('请重新登录'); }
    const data = await response.json();
    if (!response.ok) throw Error(data.error || '操作未完成，请重试');
    return data;
  }
  function letters(values) { return values.length ? values.join('、') : '未选择'; }
  function render(data, fromServer = true) {
    if (fromServer) draftSaved = true;
    snapshot = data; current = data.round;
    $('drill-welcome').hidden = !!current;
    $('drill-panel').hidden = !current;
    if (!current) {
      const available = mode === 'all' ? data.bank_count : data.wrong_book.active;
      $('welcome-title').textContent = mode === 'all' ? '把整个题库刷一遍' : (available ? '集中复习待掌握的错题' : '暂无待复习错题');
      $('welcome-description').textContent = mode === 'all' ? `题库现有 ${available} 题。本轮随机排序，每题只出现一次，提交后显示答案和已有解析。` : (available ? `当前有 ${available} 道待复习错题。答对后标记已掌握，历史错误记录保留。` : '刷题答错的题目会自动记录在这里；已掌握题目可在错题本中查看。');
      $('drill-start').disabled = available === 0;
      $('drill-start').textContent = mode === 'all' ? '开始本轮刷题' : '开始错题重练';
      return;
    }
    const q = current.question;
    const answered = current.answered_count, total = current.total;
    $('round-title').textContent = `第 ${current.round_number} 轮${mode === 'wrong' ? '错题重练' : '全题库刷题'}`;
    $('round-progress').textContent = `${answered} / ${total}`;
    $('round-meter').value = total ? answered / total * 100 : 0;
    $('round-position').textContent = current.finished ? '本轮所有题目均已作答' : `当前第 ${current.current_position + 1} 题 · 尚余 ${total - answered} 题未作答`;
    $('round-correct').textContent = current.correct_count;
    $('round-wrong').textContent = current.wrong_count;
    $('bank-change').hidden = mode !== 'all' || data.bank_count === total;
    $('save-status').textContent = draftSaved ? '进度已保存至本机账号' : '选项尚未保存，请检查连接或点击提交重试';
    if (!q) return;
    $('drill-favorite').textContent = q.favorited ? '★ 已收藏 · 取消收藏' : '☆ 收藏本题';
    $('drill-favorite').setAttribute('aria-pressed', String(q.favorited));
    $('drill-favorite').disabled = busy;
    const label = q.type === 'multi' ? '多选题' : q.type === 'judge' ? '判断题' : '单选题';
    let html = `<div class="qhead"><span class="pill">第 ${current.current_position + 1} / ${total} 题</span><span class="muted">${label}${q.module ? ' · '+esc(q.module) : ''}</span></div><h2 class="stem">${esc(q.stem)}</h2>`;
    html += q.options.map(option => {
      const selected = q.selected.includes(option.key);
      const correct = q.submitted && q.correct.includes(option.key);
      const wrong = q.submitted && selected && !correct;
      return `<label class="option ${selected?'selected':''} ${correct?'correct-choice':''} ${wrong?'wrong-choice':''}"><input type="${q.type==='multi'?'checkbox':'radio'}" name="drill-choice" value="${esc(option.key)}" ${selected?'checked':''} ${q.submitted?'disabled':''}><strong>${esc(option.key)}</strong><span>${esc(option.text)}</span></label>`;
    }).join('');
    $('drill-question').innerHTML = html;
    $('drill-question').querySelectorAll('input').forEach(input => input.addEventListener('change', saveDraft));
    $('drill-feedback').innerHTML = q.submitted ? `<div class="review ${q.is_correct?'':'bad'}"><strong>${q.is_correct?'回答正确':'回答错误，已记入错题本'}</strong><p>你的答案：${esc(letters(q.selected))}</p><p>正确答案：${esc(letters(q.correct))}</p><p class="drill-explanation">解析：${esc(q.explanation || '题库暂未提供解析。')}</p><p class="muted">来源：${esc(q.source || '未标注')}</p></div>` : '';
    $('answer-hint').textContent = q.submitted ? '答案已保存；可随时退出后继续。' : (q.type === 'multi' ? '选择所有符合的选项，再提交。' : '请选择一个答案，再提交。');
    $('drill-submit').hidden = q.submitted;
    $('drill-submit').disabled = false;
    $('drill-next').hidden = !q.submitted || current.finished;
    $('drill-next').disabled = false;
    $('round-complete').hidden = !current.finished;
    if (current.finished) {
      $('round-summary').textContent = `已刷完本轮 ${total} 题，答对 ${current.correct_count} 题、答错 ${current.wrong_count} 题，正确率 ${Math.round(current.correct_count / total * 100)}%。`;
      $('drill-new-round').textContent = mode === 'all' ? '开始新一轮' : (data.wrong_book.active ? '再练待复习错题' : '暂无待复习错题');
      $('drill-new-round').disabled = mode === 'wrong' && data.wrong_book.active === 0;
    }
  }
  function selected() { return Array.from(document.querySelectorAll('input[name="drill-choice"]:checked'), input => input.value); }
  function saveDraft() {
    if (!current || current.question.submitted || busy) return;
    const id = current.id, index = current.current_position, answer = selected();
    const version = ++draftVersion;
    draftSaved = false;
    current.question.selected = answer.slice();
    document.querySelectorAll('#drill-question .option').forEach(label => label.classList.toggle('selected', label.querySelector('input').checked));
    $('save-status').textContent = '正在保存已选选项…';
    pending = pending.then(async () => {
      try {
        await api(`/api/drill/${id}/draft`, {index,answer});
        if (version === draftVersion) {
          draftSaved = true;
          $('save-status').textContent = '已选选项和进度已保存';
        }
      } catch (error) {
        if (version === draftVersion) {
          draftSaved = false;
          $('save-status').textContent = '选项尚未保存，请检查连接或点击提交重试';
        }
        showError(error.message);
      }
    });
  }
  async function action(callback) {
    if (busy) return;
    busy = true; clearError();
    const controls = Array.from(document.querySelectorAll('#drill-start,#drill-submit,#drill-next,#drill-new-round,#drill-favorite,#drill-question input'));
    controls.forEach(control => control.disabled = true);
    try { await pending; render(await callback()); }
    catch (error) { showError(error.message); }
    finally {
      busy = false;
      if (snapshot) render(snapshot, false);
    }
  }
  $('drill-start').addEventListener('click', () => action(() => api('/api/drill/start',{mode})));
  $('drill-favorite').addEventListener('click', async () => {
    if (!current || busy) return;
    busy = true; clearError();
    document.querySelectorAll('#drill-submit,#drill-next,#drill-new-round,#drill-favorite,#drill-question input').forEach(control => control.disabled = true);
    try {
      await pending;
      const q = current.question;
      const result = await api(`/api/favorites/${q.id}`, {}, q.favorited ? 'DELETE' : 'POST');
      q.favorited = result.favorited;
      $('favorite-save-status').textContent = result.favorited ? '已保存至我的收藏集' : '已取消收藏';
    } catch (error) { showError(error.message); }
    finally { busy = false; if (snapshot) render(snapshot, false); }
  });
  $('drill-new-round').addEventListener('click', () => action(() => api('/api/drill/start',{mode})));
  $('drill-submit').addEventListener('click', () => {
    const answer = selected();
    if (!answer.length) { showError('请先选择答案'); return; }
    const id = current.id, index = current.current_position;
    action(() => api(`/api/drill/${id}/answer`,{index,answer}));
  });
  $('drill-next').addEventListener('click', () => {
    const id = current.id, index = current.current_position;
    action(() => api(`/api/drill/${id}/next`,{index}));
  });
  api('/api/drill/current?mode='+encodeURIComponent(mode)).then(render).catch(error => showError(error.message));
})();
