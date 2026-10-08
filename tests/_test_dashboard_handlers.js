/* The dashboard must stay free of inline event handlers.
 *
 * M4 D3 stage 2 moved every on* attribute to a data-action / data-on pair
 * dispatched by the page's own delegated listener, so the CSP can drop
 * 'unsafe-inline'. A control whose registry entry is missing fails only in
 * the browser, only when that exact control is used - this sweep reads the
 * shipped dashboard.html and checks the whole wiring statically.
 *
 * Run with Node: node tests/_test_dashboard_handlers.js
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = require('./dashboard_source').htmlSource();

// 1. No inline event handlers may remain - the strict CSP depends on it.
const inline = [...html.matchAll(
  /\son(?:click|change|input|submit|keydown|keyup|blur|focus|scroll)\s*=\s*"/g)];
assert.strictEqual(inline.length, 0,
  `inline handlers must be gone, found ${inline.length}`);

// 2. Every data-action must have an ACTION_HANDLERS entry.
const actions = new Set();
for (const [, name] of html.matchAll(/data-action="([A-Za-z_$][\w$]*)"/g)) actions.add(name);
assert.ok(actions.size >= 70,
  `only ${actions.size} data-action values found; the extraction broke, not the page`);

const registryMatch = html.match(/const ACTION_HANDLERS = \{([\s\S]*?)\n\};/);
assert.ok(registryMatch, 'ACTION_HANDLERS registry not found');
const registry = new Map();
for (const [, name, value] of
     registryMatch[1].matchAll(/^\s*([A-Za-z_$][\w$]*):\s*(.*?),?\s*$/gm)) {
  registry.set(name, value);
}
const missing = [...actions].filter(name => !registry.has(name)).sort();
assert.deepStrictEqual(missing, [],
  `data-action values with no handler: ${missing.join(', ')}`);

// 3. Every registry body must call a function the page defines.
const defined = new Set();
for (const [, name] of html.matchAll(/function\s+([A-Za-z_$][\w$]*)\s*\(/g)) defined.add(name);
for (const [, name] of html.matchAll(
     /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\()/g)) {
  defined.add(name);
}
// `window.name = function(...)` is the other way this page defines a handler;
// the theme block's applyTheme / selectTheme / toggleThemeMenu all use it.
// Whether such a name is actually reachable from an inline attribute is a
// scope question this textual sweep cannot answer - _test_dashboard_theme.js
// executes the theme block and checks that.
for (const [, name] of html.matchAll(/window\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\()/g)) {
  defined.add(name);
}
const KEYWORDS = new Set(['if', 'for', 'while', 'switch', 'return', 'typeof', 'new',
                          'Number', 'String', 'Boolean', 'Math', 'JSON']);
const unresolved = [];
for (const [name, body] of registry) {
  for (const [, called] of body.matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
    if (!KEYWORDS.has(called) && !defined.has(called)) {
      unresolved.push(`${name} -> ${called}`);
    }
  }
}
assert.deepStrictEqual(unresolved, [],
  `registry calls functions the page never defines: ${unresolved.join(', ')}`);

// 4. Every data-on value must be one the dispatcher listens for.
const ON_EVENTS = new Set(['click', 'change', 'input', 'keydown', 'scroll']);
const badOn = [...html.matchAll(/data-on="([a-z]+)"/g)]
  .map(m => m[1]).filter(value => !ON_EVENTS.has(value));
assert.deepStrictEqual(badOn, [], `unknown data-on events: ${badOn.join(', ')}`);
for (const type of ON_EVENTS) {
  assert.ok(html.includes(`'${type}'`), `dispatcher must listen for ${type}`);
}

// 5. The reported regression case, pinned directly (issue #66).
assert.ok(/data-action="openLoginModal"/.test(html),
  'the empty-state login button must dispatch openLoginModal');
assert.ok(!/onclick=/.test(html), 'nothing may keep an onclick attribute');

// A retired exit must stay disabled until it is explicitly rebound. Exercise
// the real editor as well: removing neighbouring settings must not break the
// model restrictions or the blank-key convention on an existing key.
const keySource = html.slice(html.indexOf('const REALM_CHOICES'), html.indexOf('let PROXY_SLOTS'));
const elements = {keyList: {innerHTML: ''}, deletedKeySection: {innerHTML: ''}};
const rows = [{id: 'retired', name: 'Retired', realm: 'opencode', enabled: false,
               masked: 'synthetic-mask', key: '', models: ['deepseek*']}];
const saves = [];
const editor = new Function('document', 'API_KEY_ROWS', 'DELETED_KEY_ROWS', 'DELETED_KEY_IDS', 'esc',
  'postJSON', 'loadSettings', 'toast', keySource +
  '; return {renderKeyRows, openEditKey, saveSingleKey, toggleKeyRow};')(
    {getElementById: id => elements[id] || null}, rows, [], [], String,
    async (url, payload) => saves.push(JSON.parse(JSON.stringify(payload))),
    () => {}, () => {});

(async () => {
  editor.renderKeyRows();
  assert.ok(elements.keyList.innerHTML.includes('出口已移除'));
  assert.ok(elements.keyList.innerHTML.includes('deepseek*'));
  await editor.toggleKeyRow(0);
  assert.strictEqual(rows[0].enabled, false);
  assert.strictEqual(saves.length, 0, 'a retired key cannot be enabled directly');
  editor.openEditKey(0);
  assert.ok(elements.keyList.innerHTML.includes('出口已移除，请选择新出口'));
  assert.ok(elements.keyList.innerHTML.includes('editKeyModels_0'));
  elements.editKeyName_0 = {value: 'Rebound'};
  elements.editKeyRealm_0 = {value: 'cn'};
  elements.editKeyValue_0 = {value: ''};
  elements.editKeyModels_0 = {value: ' DEEPSEEK*; GPT-6-ASTRA, deepseek* '};
  await editor.saveSingleKey(0);
  assert.strictEqual(saves[0].api_keys[0].realm, 'cn');
  assert.strictEqual(saves[0].api_keys[0].key, '', 'blank must preserve the stored secret');
  assert.deepStrictEqual(saves[0].api_keys[0].models, ['deepseek*', 'gpt-6-astra']);
  await editor.toggleKeyRow(0);
  assert.strictEqual(saves[1].api_keys[0].enabled, true);
  editor.renderKeyRows();
  assert.ok(elements.keyList.innerHTML.includes('固定国内版出口'));
  console.log(`dashboard handler and key editor assertions passed (${actions.size} actions, ${registry.size} handlers)`);
})().catch(error => { console.error(error); process.exit(1); });
