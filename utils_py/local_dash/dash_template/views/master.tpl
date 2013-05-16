%# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
%# Use of this source code is governed by a BSD-style license that can be
%# found in the LICENSE file.
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <meta http-equiv="pragma" content="no-cache">
    <title>{{title or 'No title'}} - ChromeOS Local Dash</title>
    <link rel="stylesheet" href="/static/css/default.css" type="text/css" />
    <link rel="alternate" type="application/rss+xml" title="RSS" href="rss">
    <script>
      var asdf = false;
      function StartTime(){
        if(asdf)clearTimeout(asdf)
        asdf = setTimeout("RefreshPage()",60000);
      }
      function RefreshPage(){
        clearTimeout(asdf)
        if(document.frmRefresh.CB1.checked) {
          if (document.frmRefresh.CB2.checked)
            document.location.href= "/regenerate?refreshing&regen";
          else
            document.location.href= "/?refreshing";
        }
      }
      function LoadPage(){
        if (document.location.href.indexOf("&regen") != -1)
          document.frmRefresh.CB2.checked=true;
        if (document.location.href.indexOf("?refr") != -1) {
          document.frmRefresh.CB1.checked=true;
          StartTime()
        }
      }
    </script>
  </head>
  <body onload="LoadPage()">
  <a name="pagetop"></a>
  %include header
  <hr/>
  <script type="text/javascript">
    function fixTooltip(event, box) {
      e = box.getElementsByTagName('span')[0];

      // Show the tooltip so we can get the width.
      e.style.display = 'block';

      // Use a slight offset so user can move to the next cell unhindered.
      offset = 5;

      // If the tooltip falls off the right side, move it left of mouse.
      x = event.clientX;
      if (x + e.offsetWidth > window.innerWidth)
        x = x - offset - e.offsetWidth;
      else
        x = x + offset;

      // If the tooltip falls off the bottom, move it above the mouse.
      y = event.clientY;
      if (y + e.offsetHeight > window.innerHeight)
        y = y - offset - e.offsetHeight;
      else
        y = y + offset;
      if (y < 0)
        y = 0;

      e.style.left = x + 'px';
      e.style.top = y + 'px';
    }

    function clearTooltip(box) {
      box.getElementsByTagName('span')[0].style.display = 'none';
    }
  </script>
  %body_block()
  %include footer
</body>
</html>
