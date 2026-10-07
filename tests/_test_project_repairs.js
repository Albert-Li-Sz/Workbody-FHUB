'use strict';
const assert = require('assert');
const path = require('path');
const {spawnSync} = require('child_process');

const run = spawnSync(process.execPath, [path.join(__dirname, '..', 'scripts', 'audit_project_ui.js')],
                      {encoding:'utf8', timeout:10000});
assert.strictEqual(run.status, 0, run.stdout + run.stderr);
const result = JSON.parse(run.stdout);
assert.deepStrictEqual(result.findings, []);
assert.strictEqual(result.observations.valid_session_cleared_on_wrong_current_password, false);
assert.strictEqual(result.observations.invalid_session_cleared, true);
assert.strictEqual(result.observations.url_password_login_triggered, false);
assert.strictEqual(result.observations.url_password_removed, true);
console.log('project audit frontend regressions passed');
