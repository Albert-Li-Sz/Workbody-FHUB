/* Markdown preview and prompt-source editing, without browser dependencies.
 * The browser QA additionally checks DOMPurify against active HTML/URLs.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '..', 'dashboard_static');
const marked = require(path.join(root, 'markdown_marked.js'));
const esc = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const elements = {};
const source = fs.readFileSync(path.join(root, 'settings.js'), 'utf8');
const context = vm.createContext({marked, esc, document:{getElementById:id=>elements[id] || null}});
vm.runInContext(source, context);

const raw = '# 助手\n\n**验证**\n\n| 步骤 | 结果 |\n| --- | --- |\n| 测试 | 成功 |\n\n```js\nconst x = "<raw>";\n```\n\n<script>alert(1)</script>\n\n![私密](https://example.com/track)';
const fallback = context.renderPromptMarkdown(raw);
assert.ok(fallback.startsWith('<pre>'));
assert.ok(!fallback.includes('<script>'));
let sanitized = 0;
context.DOMPurify = {isSupported:true, sanitize(html, options){
  sanitized++;
  assert.ok(options.ALLOWED_TAGS.includes('table'));
  assert.ok(!options.ALLOWED_TAGS.includes('script'));
  return html;
}};
const html = context.renderPromptMarkdown(raw);
assert.strictEqual(sanitized, 1);
assert.ok(html.includes('<h1>助手</h1>'));
assert.ok(html.includes('<strong>验证</strong>'));
assert.ok(html.includes('<table>'));
assert.ok(html.includes('const x = &quot;&lt;raw&gt;&quot;;'));
assert.ok(!html.includes('<script>'));
assert.ok(!html.includes('<img'));

elements.promptMarkdownPreview = {innerHTML:'', querySelectorAll:()=>[]};
elements.promptSourceStatus = {textContent:'', classList:{toggle(){}}};
elements.adv_prompt_text = {value:'  # Preserve\n\n'};
elements.adv_prompt_file = {value:''};
elements.adv_prompt_mode = {value:'custom'};
elements.adv_prompt_retry_on_content_rejection = {checked:false};
vm.runInContext('ADVANCED_SETTINGS_DATA = {prompt:{file:""}, prompt_preview:{default_text:"# Builtin"}}', context);
context.updatePromptPreview();
assert.ok(elements.promptMarkdownPreview.innerHTML.includes('Preserve'));
const config = context.readAdvancedSettingsGroup('prompt');
assert.strictEqual(config.text, '  # Preserve\n\n', 'saving must retain Markdown whitespace');
assert.strictEqual(config.mode, 'custom');

elements.adv_prompt_text.value = '';
context.updatePromptPreview();
assert.ok(elements.promptMarkdownPreview.innerHTML.includes('Builtin'));
elements.adv_prompt_file.value = '/new/prompt.md';
context.updatePromptPreview();
assert.ok(elements.promptSourceStatus.textContent.includes('保存后读取'));
assert.ok(!elements.promptMarkdownPreview.innerHTML.includes('Builtin'));
vm.runInContext('ADVANCED_SETTINGS_DATA = {prompt:{file:"/new/prompt.md"}, prompt_preview:{text:"",error:"missing file"}}', context);
context.updatePromptPreview();
assert.ok(elements.promptSourceStatus.textContent.includes('读取失败'));
assert.ok(elements.promptSourceStatus.textContent.includes('保留客户端提示词'));
elements.adv_prompt_mode.value = 'passthrough';
context.updatePromptPreview();
assert.ok(elements.promptSourceStatus.textContent.includes('网关提示词不应用'));
console.log('prompt Markdown, source status and lossless editing assertions passed');
