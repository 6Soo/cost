import re, pathlib
p = pathlib.Path(r'C:\Users\kkokk\.local\share\opencode\tool-output\tool_047507730001wnjdmZ2CqLuzuH')
t = p.read_text(encoding='utf-8', errors='ignore')
gids = re.findall(r'gid=(\d+)', t)
uniq = list(dict.fromkeys(gids))
print('gids:', uniq[:30])
# also try to find sheet names via bootstrap data
# Search for sheet names pattern
import json
# try to extract bootstrap
m = re.search(r'\"sheets\":\s*\[.*?\]', t, re.S)
if m:
    print(m.group(0)[:3000])
else:
    print('no sheets block')
    # print snippet around gid
    idx = t.find('gid=')
    print(t[idx-500:idx+2000][:2000])
