// Renders video.html frame by frame and pipes the frames to ffmpeg -> cloudstruck_video.mp4
const {chromium}=require('playwright');const {spawn}=require('child_process');
(async()=>{const FPS=30,DUR=180,dir=__dirname;
const ff=spawn('ffmpeg',['-y','-f','image2pipe','-framerate',String(FPS),'-c:v','mjpeg','-i','-','-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-preset','medium',dir+'/'+(process.argv[3]||'cloudstruck_video')+'.mp4'],{stdio:['pipe','ignore','inherit']});
const b=await chromium.launch();const p=await b.newPage({viewport:{width:1920,height:1080}});
await p.goto('file://'+dir+'/'+(process.argv[2]||'video')+'.html');await p.waitForTimeout(500);
for(let i=0;i<FPS*DUR;i++){await p.evaluate(t=>render(t),i/FPS);const buf=await p.screenshot({type:'jpeg',quality:92});if(!ff.stdin.write(buf))await new Promise(r=>ff.stdin.once('drain',r));}
ff.stdin.end();await b.close();})();
