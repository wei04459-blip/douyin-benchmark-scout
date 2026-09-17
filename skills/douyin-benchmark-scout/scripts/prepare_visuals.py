import sys,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import argparse
p=argparse.ArgumentParser(description='提取供代理初读的关键画面，不自动标记已看')
p.add_argument('--root',type=Path,required=True);R=p.parse_args().root.resolve()
db=json.loads((R/'竞品库.json').read_text())
q={'jobs':[{'source':{'aweme_id':aid},'artifacts':db['items'][aid].get('materials',{})} for aid in db['selected_ids']]}
ffmpeg=Path.home()/'.local/bin/ffmpeg'
font=ImageFont.truetype('/System/Library/Fonts/STHeiti Light.ttc',17)
for j in q['jobs']:
 if not Path(j.get('artifacts',{}).get('video_path','')).is_file():continue
 folder=R/'初读画面'/j['source']['aweme_id'];folder.mkdir(parents=True,exist_ok=True)
 if (folder/'画面总览.jpg').exists():
  old=json.loads((folder/'采样说明.json').read_text())
  if old['media_sha256']==j['artifacts']['media_sha256']:continue
  raise ValueError('原视频已变化，请另建画面版本并重新初读：'+j['source']['aweme_id'])
 v=j['artifacts']['video_path'];dur=j['artifacts']['media_duration_seconds'];times=[min(1,dur*.05),dur*.2,dur*.4,dur*.6,dur*.8,max(0,dur-2)]
 canvas=Image.new('RGB',(960,1150),'white')
 for n,t in enumerate(times):
  f=folder/f'{n+1:02}.jpg'
  subprocess.run([str(ffmpeg),'-nostdin','-v','error','-ss',str(t),'-i',v,'-frames:v','1','-vf','scale=480:-2','-q:v','3',str(f)],check=True)
  im=Image.open(f);im.thumbnail((320,530));x=(n%3)*320+(320-im.width)//2;y=(n//3)*575+35;canvas.paste(im,(x,y));ImageDraw.Draw(canvas).text(((n%3)*320+8,(n//3)*575+5),f'{t:.1f} 秒',font=font,fill='black')
 canvas.save(folder/'画面总览.jpg');(folder/'采样说明.json').write_text(json.dumps({'times':times,'video':v,'media_sha256':j['artifacts']['media_sha256']},ensure_ascii=False,indent=2))
 print(j['source']['aweme_id'],flush=True)
