/* Navigation only changes the view; saved work and running tasks stay intact. */
(() => {
  const views = { create: 'create-view', history: 'history-view', workbench: 'workbench-view' };
  const titles = { create: '新建作业', history: '历史任务', workbench: '课程资料' };
  const menu = document.querySelector('.mobile-menu');
  const sidebar = document.querySelector('.sidebar');
  const mobile = window.matchMedia('(max-width: 720px)');
  function syncSidebar() { sidebar.inert = mobile.matches && !document.body.classList.contains('sidebar-open'); }
  function closeMenu() {
    document.body.classList.remove('sidebar-open');
    menu.setAttribute('aria-expanded', 'false');
    syncSidebar();
  }
  function showView(view, section) {
    for (const [key, id] of Object.entries(views)) $(id).hidden = key !== view;
    const title = section === 'question-review' ? '作业审核' : section === 'planning' ? '自定义组卷' : titles[view];
    $('view-title').textContent = title;
    $('workbench-title').textContent = title;
    $('workbench-view').dataset.section = section || 'question-review';
    document.querySelectorAll('.nav-item').forEach(button => {
      const active = button.dataset.view === view && (view !== 'workbench' || button.dataset.section === section);
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    closeMenu();
    if (view === 'workbench') {
      $('manual-workbench').open = true;
    }
    window.scrollTo(0, 0);
  }
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    showView(button.dataset.view, button.dataset.section);
    if (button.dataset.view === 'create') {
      $('agent-prompt').value = '';
      $('prompt').value = '';
      $('agent-name').value = '';
      $('workspace-feedback').textContent = '';
      $('workspace-feedback').classList.remove('error');
      $('agent-prompt').dispatchEvent(new Event('input', { bubbles: true }));
      document.dispatchEvent(new Event('courseagent:new-assignment'));
      $('agent-prompt').focus();
    }
  }));
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    $('agent-prompt').value = button.dataset.example;
    $('agent-prompt').dispatchEvent(new Event('input', { bubbles: true }));
    $('agent-prompt').focus();
  }));
  $('attach-material').onclick = () => $('upload').click();
  $('agent-local').addEventListener('change', () => {
    $('delivery-mode').textContent = $('agent-local').checked ? '仅本地生成' : '交付头歌未发布试卷';
  });
  $('agent-prompt').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault();
      $('agent-start').click();
    }
  });
  menu.onclick = () => {
    const open = document.body.classList.toggle('sidebar-open');
    menu.setAttribute('aria-expanded', String(open));
    syncSidebar();
  };
  document.querySelector('.sidebar-overlay').onclick = closeMenu;
  document.addEventListener('courseagent:open-workbench', event => showView('workbench', event.detail?.section));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) { closeMenu(); menu.focus(); } });
  mobile.addEventListener('change', syncSidebar);
  syncSidebar();
  document.addEventListener('courseagent:sources-changed', () => {
    $('composer-sources').innerHTML = sources.map(source => `<span class="source-chip">${esc(source.name)}</span>`).join('');
  });
  if (sources.length) document.dispatchEvent(new Event('courseagent:sources-changed'));
})();
