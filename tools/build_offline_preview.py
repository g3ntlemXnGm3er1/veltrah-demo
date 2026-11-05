"""Inline a built recovery frontend; no network or execution of source assets."""
from pathlib import Path
import argparse,re
ROOT=Path(__file__).resolve().parent.parent
def build(output):
    dist=ROOT/'frontend/dist'
    text=(dist/'index.html').read_text(encoding='utf-8')
    def asset(name):
        path=(dist/name.lstrip('./')).resolve()
        if not path.is_relative_to(dist.resolve()):raise ValueError('Asset must be inside frontend/dist')
        return path.read_text(encoding='utf-8')
    text=re.sub(r'<script[^>]*src="([^"]+)"[^>]*></script>',lambda m:'<script type="module">'+asset(m.group(1)).replace('</script','<\\/script')+'</script>',text)
    text=re.sub(r'<link[^>]*href="([^"]+\.css)"[^>]*>',lambda m:'<style>'+asset(m.group(1)).replace('</style','<\\/style')+'</style>',text)
    notices=(ROOT/'frontend/THIRD_PARTY_LICENSES_FRONTEND.txt').read_text(encoding='utf-8')
    if '-->' in notices:raise ValueError('Unexpected comment terminator in notices')
    text=text.replace('</head>','<!-- Third-party notices retained.\n'+notices+'\n-->\n</head>')
    text=text.replace('<title>Veltrah · Local interaction recovery</title>','<title>Veltrah · Offline browser fixture preview</title>')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(text,encoding='utf-8');return output
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'Veltrah_Demo_Offline.html');args=parser.parse_args();print(build(args.output))
