(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let snapshot = null, generation = 0, controller = null;
  async function api(route, signal) {
    let response;
    try { response = await fetch(route, {signal}); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw Error('无法连接本机工具箱，请确认工具箱仍在运行后重试');
    }
    if (response.status === 401) { location.href = '/login'; throw Error('请重新登录'); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw Error(data.error || (response.status === 404 ? '题目已不存在，请重新检索' : '读取失败，请重试'));
    }
    return response.json();
  }
  function render(data) {
    snapshot = data;
    $('bank-summary').textContent = data.total ? `共 ${data.total} 道${data.query ? '匹配' : '题库'}题目${data.query ? ' · 关键词：'+data.query : ''} · 每题可单独显示答案` : '没有找到匹配题目，可修改关键词或点击“查看全部”。';
    $('bank-results').innerHTML = data.items.map(q => `<article class="card drill-question-card bank-item" data-question-id="${q.id}"><div class="qhead"><span class="pill">题目 #${q.id}</span><span class="muted">${q.type === 'multi' ? '多选题' : q.type === 'judge' ? '判断题' : '单选题'}${q.module ? ' · '+esc(q.module) : ''}</span></div><h2 class="stem">${esc(q.stem)}</h2><div class="bank-options">${q.options.map(o => `<div class="option"><strong>${esc(o.key)}</strong><span>${esc(o.text)}</span></div>`).join('')}</div><button class="bank-reveal" aria-expanded="false" aria-controls="bank-answer-${q.id}">显示答案</button><div id="bank-answer-${q.id}" class="bank-answer" aria-live="polite" hidden></div></article>`).join('');
    for (const card of $('bank-results').querySelectorAll('.bank-item')) {
      const button = card.querySelector('.bank-reveal'), answer = card.querySelector('.bank-answer');
      let cached = null;
      button.addEventListener('click', async () => {
        if (button.disabled) return;
        if (!answer.hidden && cached) {
          answer.hidden = true; button.textContent = '显示答案'; button.setAttribute('aria-expanded','false'); return;
        }
        button.disabled = true; button.textContent = '正在读取…';
        try {
          if (!cached) cached = await api(`/api/question-bank/${card.dataset.questionId}/answer`);
          if (!card.isConnected) return;
          answer.innerHTML = `<div class="review"><strong>正确答案：${esc(cached.correct.join('、'))}</strong><p class="drill-explanation">解析：${esc(cached.explanation || '题库暂未提供解析。')}</p><p class="muted">来源：${esc(cached.source || '未标注')}</p></div>`;
          answer.hidden = false; button.textContent = '收起答案'; button.setAttribute('aria-expanded','true');
        } catch (error) {
          if (!card.isConnected) return;
          answer.textContent = error.message; answer.hidden = false;
          button.textContent = '重试显示答案'; button.setAttribute('aria-expanded','true');
        } finally { button.disabled = false; }
      });
    }
    $('bank-pagination').hidden = data.total === 0;
    $('bank-page').textContent = `第 ${data.page} / ${data.pages} 页`;
    $('bank-prev').disabled = data.page <= 1;
    $('bank-next').disabled = data.page >= data.pages;
  }
  async function load(page, query) {
    const token = ++generation;
    if (controller) controller.abort();
    controller = new AbortController();
    $('bank-error').classList.add('hidden');
    $('bank-results').setAttribute('aria-busy','true');
    $('bank-summary').textContent = '正在检索题库…';
    $('bank-prev').disabled = true; $('bank-next').disabled = true;
    try {
      const data = await api('/api/question-bank?'+new URLSearchParams({page:String(page),q:query}),controller.signal);
      if (token === generation) render(data);
    } catch (error) {
      if (token !== generation || error.name === 'AbortError') return;
      $('bank-error').textContent = error.message; $('bank-error').classList.remove('hidden');
      $('bank-summary').textContent = snapshot ? '本次检索未完成，下面保留上次结果；请点击“检索题目”重试。' : '题库尚未读取，请点击“检索题目”重试。';
    } finally {
      if (token === generation) {
        $('bank-results').setAttribute('aria-busy','false');
        if (snapshot) {
          $('bank-prev').disabled = snapshot.page <= 1;
          $('bank-next').disabled = snapshot.page >= snapshot.pages;
        }
      }
    }
  }
  $('bank-search-form').addEventListener('submit', event => { event.preventDefault(); load(1,$('bank-query').value.trim()); });
  $('bank-clear').addEventListener('click', () => { $('bank-query').value=''; load(1,''); });
  $('bank-prev').addEventListener('click', () => { if (snapshot) load(snapshot.page-1,snapshot.query); });
  $('bank-next').addEventListener('click', () => { if (snapshot) load(snapshot.page+1,snapshot.query); });
  load(1,'');
})();
