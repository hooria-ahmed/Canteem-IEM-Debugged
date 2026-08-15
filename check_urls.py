import os, re, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'canteen_config.settings')

import django
django.setup()

from django.urls import get_resolver

resolver = get_resolver()
valid_url_names = {k for k in resolver.reverse_dict.keys() if isinstance(k, str)}

template_dir = r'core/templates'
url_pattern = re.compile(r"""{%\s*url\s+'([^']+)'""")

found_names = set()
for fname in os.listdir(template_dir):
    if fname.endswith('.html'):
        content = open(os.path.join(template_dir, fname), encoding='utf-8').read()
        for m in url_pattern.finditer(content):
            found_names.add((m.group(1), fname))

broken = []
for name, fname in sorted(found_names):
    if name not in valid_url_names:
        broken.append(fname + ': ' + name)

if broken:
    print('BROKEN URL TAGS:')
    for b in broken:
        print(' -', b)
else:
    print('All template URL tags are valid!')
print('Total unique URL names checked:', len(found_names))
