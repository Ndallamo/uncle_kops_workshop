from pathlib import Path
p = Path('templates/workshop/invoice_detail.html')
text = p.read_text(encoding='utf-8')
old = '\\n    {% if invoice.notes %}\\n    <div class="card">\\n      <div class="card-title">Notes</div>\\n      <p style="font-size:14px; line-height:1.6; margin-top:12px;">{{ invoice.notes }}</p>\\n    </div>\\n    {% endif %}\\n  </div>\\n'
new = '\n    {% if invoice.notes %}\n    <div class="card">\n      <div class="card-title">Notes</div>\n      <p style="font-size:14px; line-height:1.6; margin-top:12px;">{{ invoice.notes }}</p>\n    </div>\n    {% endif %}\n  </div>\n'
if old not in text:
    print('old snippet not found')
    print(repr(old))
    print('---')
    print(text[text.find('    </div>\\n    </div>'):text.find('    </div>\\n    </div>')+300])
else:
    p.write_text(text.replace(old, new), encoding='utf-8')
    print('replaced notes snippet')
