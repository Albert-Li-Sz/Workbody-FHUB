// Reconstruct the exact ordered bundle used by wb_dashboard.DashboardAssets.
const fs = require('fs');
const path = require('path');
function htmlSource(){
  const root = path.join(__dirname, '..', 'dashboard_static');
  const bundles = JSON.parse(fs.readFileSync(path.join(root, 'bundles.json'), 'utf8'));
  let html = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
  html = html.replace(/<script src="dashboard_static\/([^"/]+)\.js" data-bundle="([^"]+)"><\/script>/g,
    (_, file, name) => '<script>' + bundles[name].map(file => fs.readFileSync(path.join(root,file),'utf8')).join('') + '</script>');
  return html.replace(/<link([^>]*?) rel="stylesheet" href="dashboard_static\/([^"/]+)\.css">/g,
    (_, attrs, name) => '<style' + attrs + '>' + fs.readFileSync(path.join(root, name + '.css'), 'utf8') + '</style>');
}
module.exports = {htmlSource};
