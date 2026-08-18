import asyncio, json, re
from pathlib import Path
from urllib.parse import urljoin
from playwright.async_api import async_playwright

OUT=Path('yupoo_output'); OUT.mkdir(exist_ok=True)
wanted=[
'P1030 - 5251','P1050 - 0571','P1050 - 1112','P950 - 2501','P1050 - 3831',
'P1100 - 1091','P1200 - 4731','P1100 - 0991','P1150 - 8481','P1000 - 3881']

def clean(s): return re.sub(r'[^A-Za-z0-9._-]+','_',s).strip('_')[:100]

async def resolve(page):
    await page.goto('https://scarlettluxury.x.yupoo.com/albums/?page=1',wait_until='domcontentloaded',timeout=90000)
    await page.wait_for_timeout(5000)
    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)'); await page.wait_for_timeout(2500)
    await page.evaluate('window.scrollTo(0,0)')
    links=await page.locator('a[href*="albums"]').evaluate_all("els=>els.map(a=>({text:(a.innerText||a.textContent||'').trim(),href:a.href,html:a.innerHTML}))")
    out=[]; used=set()
    for code in wanted:
        c=[x for x in links if code.lower() in (x['text']+' '+x['html']).lower() and '/albums/' in x['href'] and x['href'] not in used]
        if not c:
            href=await page.evaluate("""(code)=>{
              const els=[...document.querySelectorAll('body *')].filter(e=>(e.textContent||'').toLowerCase().includes(code.toLowerCase()));
              for(const e of els){
                let n=e;
                for(let i=0;i<8 && n;i++,n=n.parentElement){
                  if(n.tagName==='A' && n.href && n.href.includes('/albums/')) return n.href;
                  const a=n.querySelector && n.querySelector('a[href*="albums"]');
                  if(a && a.href && a.href.includes('/albums/')) return a.href;
                }
              }
              return null;
            }""", code)
            c=[{'href':href}] if href and href not in used else []
        href=c[0]['href'] if c else None
        out.append((clean(code),href));
        if href: used.add(href)
    print('RESOLVED',out,flush=True)
    return out

async def scrape(context,label,url):
    r={'label':label,'url':url,'title':None,'imageUrls':[],'savedFiles':[],'error':None}
    if not url: r['error']='unresolved'; return r
    page=await context.new_page(); seen=set()
    try:
        def resp(x):
            u=x.url; ct=(x.headers or {}).get('content-type','')
            if ('image' in ct.lower() or re.search(r'\.(jpg|jpeg|png|webp)(\?|$)',u,re.I)) and ('yupoo' in u.lower() or 'photo' in u.lower()): seen.add(u)
        page.on('response',resp)
        await page.goto(url,wait_until='domcontentloaded',timeout=90000); await page.wait_for_timeout(3500)
        for y in [600,1200,2400,5000,9000,15000,25000]:
            await page.evaluate(f'window.scrollTo(0,{y})'); await page.wait_for_timeout(700)
        r['title']=await page.title()
        attrs=await page.locator('img').evaluate_all("""els=>els.flatMap(img=>{const v=[];for(const a of ['src','data-src','data-original','data-origin-src','data-lazy-src','data-url','data-ks-lazyload']){const x=img.getAttribute(a);if(x)v.push(x)}if(img.currentSrc)v.push(img.currentSrc);const s=img.getAttribute('srcset');if(s)s.split(',').forEach(x=>v.push(x.trim().split(/\\s+/)[0]));return v})""")
        for v in attrs:
            if v and not v.startswith(('data:','blob:')): seen.add(urljoin(page.url,v))
        # Keep one highest-quality URL per Yupoo image hash, preferring original/big over medium/small/square.
        byhash={}; other=[]
        for u in seen:
            lu=u.lower()
            if any(x in lu for x in ['avatar','logo','favicon','qrcode','qr_code','weibo','icon','notaccess']): continue
            if not (('yupoo' in lu or 'photo' in lu) and (re.search(r'\.(jpg|jpeg|png|webp)(\?|$)',lu) or 'photo.yupoo.com' in lu)): continue
            m=re.search(r'photo\.yupoo\.com/[^/]+/([^/]+)/([^/?]+)',u,re.I)
            if m:
                h=m.group(1); fn=m.group(2).lower()
                score=4 if fn=='big.jpg' else 5 if fn not in ('medium.jpg','small.jpg','square.jpg','big.jpg') else 3 if fn=='medium.jpg' else 2 if fn=='small.jpg' else 1
                if h not in byhash or score>byhash[h][0]: byhash[h]=(score,u)
            else: other.append(u)
        urls=[v[1] for v in byhash.values()]+other
        urls=list(dict.fromkeys(sorted(urls))); r['imageUrls']=urls
        folder=OUT/clean(label); folder.mkdir(exist_ok=True)
        for i,u in enumerate(urls[:20],1):
            try:
                rr=await context.request.get(u,headers={'Referer':page.url},timeout=60000)
                if not rr.ok: continue
                body=await rr.body(); ct=(rr.headers or {}).get('content-type',''); ext='.png' if 'png' in ct else '.webp' if 'webp' in ct else '.jpg'
                fp=folder/f'{i:02d}{ext}'; fp.write_bytes(body)
                if fp.stat().st_size>5000: r['savedFiles'].append(str(fp))
                else: fp.unlink(missing_ok=True)
            except Exception: pass
    except Exception as e: r['error']=repr(e)
    finally: await page.close()
    return r

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--disable-blink-features=AutomationControlled'])
        context=await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36',viewport={'width':1440,'height':1200},locale='en-US')
        p0=await context.new_page(); targets=await resolve(p0); await p0.close()
        results=[]
        for label,url in targets:
            print('SCRAPE',label,url,flush=True); results.append(await scrape(context,label,url))
        await browser.close(); (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(results,ensure_ascii=False,indent=2))
asyncio.run(main())
