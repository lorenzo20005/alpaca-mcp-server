import asyncio, json, re
from pathlib import Path
from urllib.parse import urljoin
from playwright.async_api import async_playwright

OUT=Path('yupoo_output'); OUT.mkdir(exist_ok=True)
fixed=[
('P1180-3311-A','https://scarlettluxury.x.yupoo.com/albums/189867318'),
('P1180-3311-B','https://scarlettluxury.x.yupoo.com/albums/189867316'),
('P950-2501','https://scarlettluxury.x.yupoo.com/albums/223410610?isSubCate=false&referrercate=4064059&uid=1')]
wanted=['P1030 - 5251','P1050 - 0571','P1050 - 1112','P1050 - 3831','P1100 - 1091','P1200 - 4731','P1100 - 0991']

def clean(s): return re.sub(r'[^A-Za-z0-9._-]+','_',s).strip('_')[:100]

async def resolve(page):
    await page.goto('https://scarlettluxury.x.yupoo.com/albums/?page=1',wait_until='domcontentloaded',timeout=90000)
    await page.wait_for_timeout(5000)
    links=await page.locator('a[href*="/albums/"]').evaluate_all("els=>els.map(a=>({text:(a.innerText||a.textContent||'').trim(),href:a.href}))")
    out=[]; used=set()
    for code in wanted:
        c=[x for x in links if code.lower() in x['text'].lower() and x['href'] not in used]
        out.append((clean(code),c[0]['href'] if c else None))
        if c: used.add(c[0]['href'])
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
        urls=[]
        for u in seen:
            lu=u.lower()
            if any(x in lu for x in ['avatar','logo','favicon','qrcode','qr_code','weibo','icon']): continue
            if ('yupoo' in lu or 'photo' in lu) and (re.search(r'\.(jpg|jpeg|png|webp)(\?|$)',lu) or 'photo.yupoo.com' in lu): urls.append(u)
        urls=list(dict.fromkeys(sorted(urls))); r['imageUrls']=urls
        folder=OUT/clean(label); folder.mkdir(exist_ok=True)
        for i,u in enumerate(urls[:30],1):
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
        p0=await context.new_page(); resolved=await resolve(p0); await p0.close()
        results=[]
        for label,url in fixed+resolved:
            print('SCRAPE',label,url,flush=True); results.append(await scrape(context,label,url))
        await browser.close(); (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(results,ensure_ascii=False,indent=2))
asyncio.run(main())
