%# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
%# Use of this source code is governed by a BSD-style license that can be
%# found in the LICENSE file.
%def body_block():
  <div style="font-family: monospace">
    <h2>Index of logs/{{filepath}}</h2>
    <hr>
    <table>
    <tbody>
      <tr>
        <th>&nbsp;</th>
        <th style="text-align:left">Name</th>
        <th style="text-align:right">Date Modified</th>
      </tr>
      %for is_dir, link_part, time_part, _ in body_lines:
        <tr>
        <td>{{is_dir}}</td>
        <td style="text-align:left">{{!link_part}}</td>
        <td style="padding-left:20px">{{time_part}}</td>
        </tr>
      %end
    </tbody>
    </table>
  </div>
%end

# Trick to workaround template limitation of not allowing line breaks.
%tpl_vars = {}
%tpl_vars['title']= filepath if filepath else '/'
%tpl_vars['body_block'] = body_block
%rebase master tpl_vars
