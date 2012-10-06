%def body_block():
  <h2>ChromeOS Local Test Results</h2>
  The following are accepted url patterns:
  <ul>
  <li><a href="/logs">/logs</a></li>
  <li><a href="/tests">/tests</a></li>
  </ul>
%end

%rebase master {'title': 'Help', 'body_block': body_block}
