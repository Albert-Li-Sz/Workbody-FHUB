
/* Runs before <body> is parsed, so the page the user last had is the
   first one painted. Kept inline and dependency-free on purpose: an
   external or deferred script would run too late to avoid the flash. */
(function(){
  var THEME_KEY = 'wb-theme';
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function getPref(){
    try { return localStorage.getItem(THEME_KEY) || 'system'; } catch(e){ return 'system'; }
  }
  function resolve(pref){
    if(pref === 'dark' || pref === 'light') return pref;
    return (mq && mq.matches) ? 'dark' : 'light';
  }

  // 1. 初始化主题（防止闪烁）
  var savedTheme = getPref();
  var resolvedTheme = resolve(savedTheme);
  document.documentElement.setAttribute('data-theme', resolvedTheme);
  document.documentElement.setAttribute('data-theme-pref', savedTheme);
  document.documentElement.style.colorScheme = resolvedTheme;

  // 2. 主题切换核心与UI同步逻辑
  var svgSun = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"></path></svg>';
  var svgMoon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>';
  var svgMonitor = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>';

  function updateThemeUI(pref, resolved){
    var icon = document.getElementById('themeToggleIcon');
    var btn = document.getElementById('themeToggleBtn');
    if(!icon) return;
    if(pref === 'dark'){
      icon.innerHTML = svgMoon;
    } else if(pref === 'light'){
      icon.innerHTML = svgSun;
    } else {
      icon.innerHTML = svgMonitor;
    }
    ['light', 'dark', 'system'].forEach(function(val){
      var opt = document.getElementById('themeOpt' + val.charAt(0).toUpperCase() + val.slice(1));
      if(opt) opt.classList.toggle('active', pref === val);
    });
    var label = pref === 'dark' ? '深色' : (pref === 'light' ? '浅色' : '跟随系统 (' + (resolved === 'dark' ? '当前深色' : '当前浅色') + ')');
    if(btn) btn.title = '颜色主题: ' + label;
  }

  window.applyTheme = function(pref){
    var resolved = resolve(pref);
    document.documentElement.setAttribute('data-theme', resolved);
    document.documentElement.setAttribute('data-theme-pref', pref);
    document.documentElement.style.colorScheme = resolved;
    try { localStorage.setItem(THEME_KEY, pref); } catch(e){}
    updateThemeUI(pref, resolved);
  };

  window.selectTheme = function(pref, evt){
    if(evt){
      evt.preventDefault();
      evt.stopPropagation();
    }
    window.applyTheme(pref);
    var menu = document.getElementById('themeDropdown');
    var btn = document.getElementById('themeToggleBtn');
    if(menu) menu.classList.remove('open');
    if(btn) btn.setAttribute('aria-expanded', 'false');
  };

  window.toggleThemeMenu = function(evt){
    if(evt){
      evt.preventDefault();
      evt.stopPropagation();
    }
    var menu = document.getElementById('themeDropdown');
    var btn = document.getElementById('themeToggleBtn');
    if(!menu) return;
    var isOpen = menu.classList.toggle('open');
    if(btn) btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  };

  window.initThemeSystem = function(){
    var curPref = getPref();
    updateThemeUI(curPref, resolve(curPref));
    if(mq && mq.addEventListener){
      mq.addEventListener('change', function(){
        if(getPref() === 'system'){
          window.applyTheme('system');
        }
      });
    }
    document.addEventListener('click', function(e){
      var wrap = document.getElementById('themeDropdownWrap');
      if(wrap && !wrap.contains(e.target)){
        var menu = document.getElementById('themeDropdown');
        var btn = document.getElementById('themeToggleBtn');
        if(menu && menu.classList.contains('open')){
          menu.classList.remove('open');
          if(btn) btn.setAttribute('aria-expanded', 'false');
        }
      }
    });
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape'){
        var menu = document.getElementById('themeDropdown');
        var btn = document.getElementById('themeToggleBtn');
        if(menu && menu.classList.contains('open')){
          menu.classList.remove('open');
          if(btn) btn.setAttribute('aria-expanded', 'false');
        }
      }
    });
  };

  // 3. Tab 初始化
  var TABS = ['gateway','accounts','tasks','analytics','models','logs','settings'];
  var pick = null;
  try {
    var q = new URLSearchParams(location.search).get('tab');
    var s = localStorage.getItem('wb-proxy-main-tab');
    pick = [q, s].find(function(t){ return TABS.indexOf(t) !== -1; }) || 'gateway';
  } catch(e) { pick = 'gateway'; }
  window.__MAIN_TAB__ = pick;

  document.addEventListener('DOMContentLoaded', function(){
    TABS.forEach(function(t){
      var page = document.getElementById('page' + t.charAt(0).toUpperCase() + t.slice(1));
      if(page) page.classList.toggle('active', t === pick);
      var btn = document.getElementById('btnNav' + t.charAt(0).toUpperCase() + t.slice(1));
      if(btn) btn.classList.toggle('active', t === pick);
    });
    window.initThemeSystem();
  });
})();
