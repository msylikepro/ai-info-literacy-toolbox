(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const cache = new Map();
  let items = [], position = 0, view = null, busy = false, loaded = false;
  async function api(route, method = 'GET', body) {
    let response;
    try {
      response = await fetch(route, {method, ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    } catch (error) { throw Error('无法连接本机工具箱，请确认工具箱仍在运行后重试'); }
    if (response.status === 401) { location.href = '/login'; throw Error('请重新登录'); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw Error(data.error || (response.status === 404 ? '本题已不在收藏集中，请刷新列表' : '操作未完成，请重试'));
    }
    return response.json();
  }
  function render() {
    $('favorite-empty').hidden = !loaded || items.length > 0;
    $('favorite-panel').hidden = !items.length || !view;
    $('favorite-status').textContent = busy ? '正在处理…' : (!loaded ? '未能读取收藏，请点击“刷新收藏集”重试。' : (items.length ? '收藏已保存在本机账号；本页作答仅用于复习。' : '收藏列表已读取'));
    $('favorite-refresh').disabled = busy;
    if (!view || !items.length) return;
    $('favorite-count').textContent = `${items.length} 题`;
    $('favorite-position').textContent = `第 ${position + 1} / ${items.length} 题`;
    $('favorite-numbers').innerHTML = items.map((item, index) => `<button class="number ${index === position ? 'active' : ''}" data-position="${index}" title="${esc(item.stem)}" ${index === position ? 'aria-current="true"' : ''}>${index + 1}</button>`).join('');
    $('favorite-numbers').querySelectorAll('button').forEach(button => button.addEventListener('click', () => run(() => load(Number(button.dataset.position)))));
    const q = view.question;
    const kind = q.type === 'multi' ? '多选题' : q.type === 'judge' ? '判断题' : '单选题';
    $('favorite-question').innerHTML = `<div class="qhead"><span class="muted">${kind}${q.module ? ' · '+esc(q.module) : ''}</span></div><h2 class="stem">${esc(q.stem)}</h2>` + q.options.map(option => {
      const selected = view.selected.includes(option.key);
      const correct = view.checked && view.answerVisible && view.feedback.correct.includes(option.key);
      const wrong = view.checked && view.answerVisible && selected && !correct;
      return `<label class="option ${selected ? 'selected' : ''} ${correct ? 'correct-choice' : ''} ${wrong ? 'wrong-choice' : ''}"><input type="${q.type === 'multi' ? 'checkbox' : 'radio'}" name="favorite-choice" value="${esc(option.key)}" ${selected ? 'checked' : ''}><strong>${esc(option.key)}</strong><span>${esc(option.text)}</span></label>`;
    }).join('');
    $('favorite-question').querySelectorAll('input').forEach(input => input.addEventListener('change', () => {
      view.selected = Array.from(document.querySelectorAll('input[name="favorite-choice"]:checked'), item => item.value);
      document.querySelectorAll('#favorite-question .option').forEach(label => label.classList.toggle('selected', label.querySelector('input').checked));
    }));
    if (view.answerVisible && view.feedback) {
      const r = view.feedback;
      $('favorite-feedback').innerHTML = `<div class="review ${view.checked && !r.is_correct ? 'bad' : ''}"><strong>${view.checked ? (r.is_correct ? '回答正确' : '回答错误，本次仅作复习') : '参考答案'}</strong>${view.checked ? `<p>你的答案：${esc(view.selected.join('、'))}</p>` : ''}<p>正确答案：${esc(r.correct.join('、'))}</p><p class="drill-explanation">解析：${esc(r.explanation || '题库暂未提供解析。')}</p><p class="muted">来源：${esc(r.source || '未标注')}</p></div>`;
    } else { $('favorite-feedback').innerHTML = ''; }
    $('favorite-submit').hidden = view.checked;
    $('favorite-reset').hidden = !view.checked && !view.feedback;
    $('favorite-reveal').textContent = view.answerVisible ? '收起答案' : '显示答案';
    document.querySelectorAll('#favorite-panel button,#favorite-panel input').forEach(control => control.disabled = busy);
    $('favorite-prev').disabled = busy || position === 0;
    $('favorite-next').disabled = busy || position === items.length - 1;
    if (view.checked) $('favorite-question').querySelectorAll('input').forEach(input => input.disabled = true);
  }
  async function load(index) {
    const item = items[index];
    if (!item) { view = null; return; }
    let target = cache.get(item.id);
    if (!target) {
      target = {question:await api(`/api/favorites/${item.id}`), selected:[], checked:false, answerVisible:false, feedback:null};
      cache.set(item.id, target);
    }
    position = index; view = target;
  }
  async function run(task) {
    if (busy) return;
    busy = true; $('favorite-error').classList.add('hidden'); render();
    try { await task(); }
    catch (error) { $('favorite-error').textContent = error.message; $('favorite-error').classList.remove('hidden'); }
    finally { busy = false; render(); }
  }
  async function refresh() {
    const formerId = view?.question.id;
    const listing = await api('/api/favorites');
    items = listing.items; loaded = true; cache.clear(); view = null;
    const priorPosition = items.findIndex(item => item.id === formerId);
    await load(priorPosition >= 0 ? priorPosition : Math.max(0, Math.min(position, items.length - 1)));
  }
  $('favorite-refresh').addEventListener('click', () => run(refresh));
  $('favorite-submit').addEventListener('click', () => run(async () => {
    if (!view.selected.length) throw Error('请先选择答案');
    view.feedback = await api(`/api/favorites/${view.question.id}/answer`, 'POST', {answer:view.selected});
    view.checked = true; view.answerVisible = true;
  }));
  $('favorite-reveal').addEventListener('click', () => run(async () => {
    if (!view.feedback) view.feedback = await api(`/api/favorites/${view.question.id}/reveal`, 'POST');
    view.answerVisible = !view.answerVisible;
  }));
  $('favorite-reset').addEventListener('click', () => run(async () => {
    view.selected = []; view.checked = false; view.answerVisible = false; view.feedback = null;
  }));
  $('favorite-prev').addEventListener('click', () => run(() => load(position - 1)));
  $('favorite-next').addEventListener('click', () => run(() => load(position + 1)));
  $('favorite-remove').addEventListener('click', () => run(async () => {
    const id = view.question.id;
    await api(`/api/favorites/${id}`, 'DELETE');
    items.splice(position, 1); cache.delete(id);
    // The removal has committed. A failed next GET must never leave the old
    // question actionable against the remaining list.
    view = null; position = Math.max(0, Math.min(position, items.length - 1));
    try { await load(position); }
    catch (error) { throw Error('本题已移出，但下一题读取失败。请点击“刷新收藏集”重试。'); }
  }));
  run(refresh);
})();
