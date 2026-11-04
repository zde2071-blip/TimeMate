// The local edition keeps only the mail and agenda workspaces.
function renderChatModel() {}
$('account-email').textContent='本地版';
$('settings-account-email').textContent='本地版';
$('nav-settings').textContent='设置';
$('account-avatar').setAttribute('aria-label','设置');
$('settings-personal-label').closest('section').hidden=true;
$('settings-nav-agents').closest('section').hidden=true;
